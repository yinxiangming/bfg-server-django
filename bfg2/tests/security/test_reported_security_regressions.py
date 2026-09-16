"""Regression tests for the September 2026 multi-tenant/payment audit."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError as APIValidationError

from bfg.common.models import (
    Customer,
    StaffMember,
    StaffRole,
    User,
    Workspace,
    WorkspaceDomain,
    upsert_custom_workspace_domain,
)
from bfg.common.models.core import media_upload_to
from bfg.common.serializers import MeSerializer
from bfg.delivery.models import FreightStatus, Package, TrackingEvent
from bfg.finance.exceptions import PaymentFailed
from bfg.finance.models import Currency, PaymentGateway, Refund, Transaction
from bfg.finance.serializers import PaymentGatewaySerializer
from bfg.finance.services.payment_service import PaymentService
from bfg.core.permissions import CanManagePayments, CanProcessRefunds
from bfg.finance.views import RefundViewSet
from bfg.shop.models import Cart, CartItem, Order, Product, ProductVariant, Store
from bfg.shop.services.cart_service import CartService
from bfg.shop.viewsets.media import _workspace_folder_path
from bfg.web.models import Inquiry
from bfg.web.services.inquiry_service import InquiryService


def _workspace(slug):
    return Workspace.objects.create(name=slug, slug=slug, is_active=True)


def _customer(workspace, username):
    user = User.objects.create_user(username=username, email=f'{username}@example.test', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    return user, customer


def _staff(user, workspace, code, permissions=None):
    role = StaffRole.objects.create(
        workspace=workspace,
        name=code,
        code=code,
        permissions=permissions or {},
    )
    return StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=True)


def _order(workspace, customer, *, number='ORD-SEC-1', total='10.00'):
    store = Store.all_objects.create(workspace=workspace, name='Main', code=f'main-{number}')
    return Order.all_objects.create(
        workspace=workspace,
        customer=customer,
        store=store,
        order_number=number,
        fulfillment_method='pickup',
        subtotal=Decimal(total),
        total=Decimal(total),
    )


@pytest.mark.django_db
def test_customer_processing_pending_offline_payment_does_not_mark_order_paid():
    workspace = _workspace('pending-payment')
    user, customer = _customer(workspace, 'pending-shopper')
    order = _order(workspace, customer)
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Bank transfer',
        gateway_type='bank_transfer',
        config={},
        test_config={},
    )
    service = PaymentService(workspace=workspace, user=user)
    payment = service.create_payment(customer, order.total, currency, gateway, order=order)

    processed = service.process_payment(payment)

    order.refresh_from_db()
    assert processed.status == 'pending'
    assert order.payment_status == 'pending'
    assert processed.completed_at is None


@pytest.mark.django_db
def test_authorized_manual_confirmation_can_complete_offline_payment():
    workspace = _workspace('manual-payment')
    user, customer = _customer(workspace, 'manual-payment-staff')
    order = _order(workspace, customer, number='ORD-MANUAL')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Pay in store',
        gateway_type='pay_in_store',
        config={},
        test_config={},
    )
    service = PaymentService(workspace=workspace, user=user)
    payment = service.create_payment(customer, order.total, currency, gateway, order=order)

    processed = service.process_payment(
        payment,
        {'reference': 'TILL-123'},
        manual_confirmation=True,
    )

    order.refresh_from_db()
    assert processed.status == 'completed'
    assert processed.gateway_transaction_id == 'TILL-123'
    assert order.payment_status == 'paid'


@pytest.mark.django_db
def test_refund_is_not_completed_without_explicit_gateway_success():
    workspace = _workspace('refund-fail-closed')
    user, customer = _customer(workspace, 'refund-staff')
    order = _order(workspace, customer, number='ORD-REFUND')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Bank transfer',
        gateway_type='bank_transfer',
        config={},
        test_config={},
    )
    service = PaymentService(workspace=workspace, user=user)
    payment = service.create_payment(customer, order.total, currency, gateway, order=order)
    payment.status = 'completed'
    payment.save(update_fields=['status'])

    with pytest.raises(PaymentFailed):
        service.create_refund(
            payment,
            Decimal('1.00'),
            idempotency_key='refund-fail-closed-1',
        )

    assert not Refund.objects.filter(payment=payment, status='completed').exists()


@pytest.mark.django_db(transaction=True)
def test_gateway_success_is_reused_when_local_payment_finalization_retries(monkeypatch):
    workspace = _workspace('payment-finalize-retry')
    user, customer = _customer(workspace, 'payment-finalize-user')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Card gateway',
        gateway_type='stripe',
        config={},
        test_config={},
    )
    service = PaymentService(workspace=workspace, user=user)
    payment = service.create_payment(customer, Decimal('10.00'), currency, gateway)
    calls = {'gateway': 0}

    def gateway_success(*_args, **_kwargs):
        calls['gateway'] += 1
        return {'success': True, 'status': 'succeeded', 'transaction_id': 'pi_safe_retry'}

    real_finalize = service._finalize_confirmed_payment
    monkeypatch.setattr(service, '_call_payment_gateway', gateway_success)
    monkeypatch.setattr(
        service,
        '_finalize_confirmed_payment',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('local failure')),
    )
    with pytest.raises(RuntimeError, match='local failure'):
        service.process_payment(payment)

    payment.refresh_from_db()
    assert payment.status == 'processing'
    assert payment.gateway_response['status'] == 'succeeded'

    monkeypatch.setattr(service, '_finalize_confirmed_payment', real_finalize)
    completed = service.process_payment(payment)
    assert completed.status == 'completed'
    assert calls['gateway'] == 1
    assert Transaction.objects.filter(payment=payment, transaction_type='payment').count() == 1


@pytest.mark.django_db
def test_order_rejects_a_second_active_payment_attempt():
    workspace = _workspace('single-active-payment')
    user, customer = _customer(workspace, 'single-active-user')
    order = _order(workspace, customer, number='ORD-SINGLE-ACTIVE')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Card gateway',
        gateway_type='stripe',
        config={},
        test_config={},
    )
    service = PaymentService(workspace=workspace, user=user)
    service.create_payment(customer, order.total, currency, gateway, order=order)

    with pytest.raises(PaymentFailed, match='active payment attempt'):
        service.create_payment(customer, order.total, currency, gateway, order=order)


@pytest.mark.django_db
def test_payment_create_maps_domain_validation_to_bad_request():
    workspace = _workspace('payment-api-validation')
    _, order_customer = _customer(workspace, 'payment-order-owner')
    staff = User.objects.create_superuser(
        username='payment-api-staff',
        email='payment-api-staff@example.test',
        password='x',
    )
    Customer.objects.create(workspace=workspace, user=staff, is_active=True)
    order = _order(workspace, order_customer, number='ORD-API-VALIDATION')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Card gateway',
        gateway_type='stripe',
        config={},
        test_config={},
    )
    client = APIClient()
    client.force_authenticate(user=staff)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))

    response = client.post(
        '/api/v1/finance/payments/',
        {
            'order_id': order.id,
            'gateway_id': gateway.id,
            'currency_id': currency.id,
            'amount': str(order.total),
        },
        format='json',
    )

    assert response.status_code == 400
    assert 'does not own this order' in str(response.data['detail'])


@pytest.mark.django_db
def test_storefront_payment_intent_rejects_zero_total_as_bad_request():
    workspace = _workspace('zero-total-payment-intent')
    user, customer = _customer(workspace, 'zero-total-shopper')
    order = _order(
        workspace,
        customer,
        number='ORD-ZERO-TOTAL',
        total='0.00',
    )
    Currency.objects.create(code='NZD', name='New Zealand Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Card gateway',
        gateway_type='stripe',
        config={},
        test_config={},
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))

    response = client.post(
        '/api/v1/store/payments/intent/',
        {'order_id': order.id, 'gateway_id': gateway.id},
        format='json',
    )

    assert response.status_code == 400
    assert 'greater than zero' in str(response.data['detail'])


@pytest.mark.django_db
def test_inactive_gateway_and_payment_method_cannot_be_used():
    from bfg.finance.models import PaymentMethod

    workspace = _workspace('inactive-payment-resources')
    user, customer = _customer(workspace, 'inactive-payment-user')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Inactive gateway',
        gateway_type='stripe',
        config={},
        test_config={},
        is_active=False,
    )
    service = PaymentService(workspace=workspace, user=user)

    with pytest.raises(PaymentFailed, match='inactive'):
        service.create_payment(customer, Decimal('10.00'), currency, gateway)

    gateway.is_active = True
    gateway.save(update_fields=['is_active'])
    method = PaymentMethod.objects.create(
        workspace=workspace,
        customer=customer,
        gateway=gateway,
        method_type='card',
        gateway_token='pm_inactive',
        is_active=False,
    )
    with pytest.raises(PaymentFailed, match='inactive'):
        service.create_payment(
            customer,
            Decimal('10.00'),
            currency,
            gateway,
            payment_method=method,
        )


@pytest.mark.django_db(transaction=True)
def test_gateway_success_is_reused_when_local_refund_finalization_retries(monkeypatch):
    workspace = _workspace('refund-finalize-retry')
    user, customer = _customer(workspace, 'refund-finalize-user')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Card gateway',
        gateway_type='stripe',
        config={},
        test_config={},
    )
    service = PaymentService(workspace=workspace, user=user)
    payment = service.create_payment(customer, Decimal('10.00'), currency, gateway)
    payment.status = 'completed'
    payment.save(update_fields=['status'])
    calls = {'gateway': 0}

    def refund_success(*_args, **_kwargs):
        calls['gateway'] += 1
        return {'success': True, 'status': 'succeeded', 'refund_id': 're_safe_retry'}

    real_finalize = service._finalize_confirmed_refund
    monkeypatch.setattr(service, '_call_refund_gateway', refund_success)
    monkeypatch.setattr(
        service,
        '_finalize_confirmed_refund',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('local failure')),
    )
    with pytest.raises(RuntimeError, match='local failure'):
        service.create_refund(
            payment,
            Decimal('3.00'),
            'retry-safe',
            idempotency_key='refund-retry-safe-1',
        )

    refund = Refund.objects.get(payment=payment)
    assert refund.status == 'processing'
    assert refund.gateway_refund_id == 're_safe_retry'

    monkeypatch.setattr(service, '_finalize_confirmed_refund', real_finalize)
    completed = service.create_refund(
        payment,
        Decimal('3.00'),
        'retry-safe',
        idempotency_key='refund-retry-safe-1',
    )
    assert completed.status == 'completed'
    assert calls['gateway'] == 1
    assert Transaction.objects.filter(payment=payment, transaction_type='refund').count() == 1

    replayed = service.create_refund(
        payment,
        Decimal('3.00'),
        'retry-safe',
        idempotency_key='refund-retry-safe-1',
    )
    assert replayed.pk == completed.pk
    assert calls['gateway'] == 1
    assert Transaction.objects.filter(payment=payment, transaction_type='refund').count() == 1


@pytest.mark.django_db(transaction=True)
def test_unknown_refund_outcome_retries_the_same_attempt(monkeypatch):
    workspace = _workspace('refund-unknown-retry')
    user, customer = _customer(workspace, 'refund-unknown-user')
    currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Card gateway',
        gateway_type='stripe',
        config={},
        test_config={},
    )
    service = PaymentService(workspace=workspace, user=user)
    payment = service.create_payment(customer, Decimal('10.00'), currency, gateway)
    payment.status = 'completed'
    payment.save(update_fields=['status'])
    seen_attempts = []

    def flaky_gateway(_gateway, _payment, refund):
        seen_attempts.append(refund.pk)
        if len(seen_attempts) == 1:
            raise ConnectionError('gateway response lost')
        return {'success': True, 'status': 'succeeded', 'refund_id': 're_after_timeout'}

    monkeypatch.setattr(service, '_call_refund_gateway', flaky_gateway)
    with pytest.raises(PaymentFailed, match='gateway response lost'):
        service.create_refund(
            payment,
            Decimal('2.00'),
            'timeout-safe',
            idempotency_key='refund-timeout-safe-1',
        )

    attempt = Refund.objects.get(payment=payment)
    assert attempt.status == 'processing'
    completed = service.create_refund(
        payment,
        Decimal('2.00'),
        'timeout-safe',
        idempotency_key='refund-timeout-safe-1',
    )
    assert completed.pk == attempt.pk
    assert completed.status == 'completed'
    assert seen_attempts == [attempt.pk, attempt.pk]


@pytest.mark.django_db
def test_workspace_write_permission_is_checked_against_target_workspace():
    workspace_a = _workspace('workspace-a')
    workspace_b = _workspace('workspace-b')
    user = User.objects.create_user(username='mixed-role', password='x')
    _staff(user, workspace_a, 'admin')
    _staff(user, workspace_b, 'customer_service')

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace_a.id))
    response = client.patch(
        f'/api/v1/workspaces/{workspace_b.id}/',
        {'name': 'PWNED'},
        format='json',
    )

    workspace_b.refresh_from_db()
    assert response.status_code == 403
    assert workspace_b.name == 'workspace-b'


@pytest.mark.django_db
def test_agent_refund_requires_payment_update_permission():
    workspace = _workspace('agent-refund-permission')
    read_user = User.objects.create_user(username='refund-reader', password='x')
    update_user = User.objects.create_user(username='refund-writer', password='x')
    _staff(read_user, workspace, 'reader', {'finance.payment': ['read']})
    _staff(update_user, workspace, 'writer', {'finance.payment': ['read', 'update']})
    permission = CanProcessRefunds()

    assert permission.has_permission(
        SimpleNamespace(user=read_user, workspace=workspace, is_staff_member=True),
        SimpleNamespace(),
    ) is False
    assert permission.has_permission(
        SimpleNamespace(user=update_user, workspace=workspace, is_staff_member=True),
        SimpleNamespace(),
    ) is True


def test_refund_endpoint_uses_update_permission_for_creation():
    view = RefundViewSet()
    view.action = 'create'

    permissions = view.get_permissions()

    assert any(isinstance(permission, CanProcessRefunds) for permission in permissions)
    assert not any(
        type(permission) is CanManagePayments
        for permission in permissions
    )


@pytest.mark.django_db
def test_package_and_tracking_event_lists_are_tenant_scoped():
    workspace_a = _workspace('delivery-a')
    workspace_b = _workspace('delivery-b')
    user, customer_a = _customer(workspace_a, 'delivery-agent')
    _, customer_b = _customer(workspace_b, 'delivery-customer-b')
    _staff(user, workspace_a, 'ops')
    order_a = _order(workspace_a, customer_a, number='ORD-A')
    order_b = _order(workspace_b, customer_b, number='ORD-B')
    status_a = FreightStatus.objects.create(
        workspace=workspace_a, code='packed-a', name='Packed', type='package', state='READY',
    )
    status_b = FreightStatus.objects.create(
        workspace=workspace_b, code='packed-b', name='Packed', type='package', state='READY',
    )
    package_a = Package.objects.create(
        order=order_a, package_number='PKG-A', state='READY', status=status_a,
    )
    package_b = Package.objects.create(
        order=order_b, package_number='PKG-B-SECRET', state='READY', status=status_b,
    )
    package_type = ContentType.objects.get_for_model(Package)
    TrackingEvent.objects.create(
        workspace=workspace_a,
        content_type=package_type,
        object_id=package_a.id,
        event_type='created',
        description='A event',
        event_time=order_a.created_at,
    )
    TrackingEvent.objects.create(
        workspace=workspace_b,
        content_type=package_type,
        object_id=package_b.id,
        event_type='created',
        description='B secret event',
        event_time=order_b.created_at,
    )

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace_a.id))
    packages = client.get('/api/v1/delivery/packages/').json()
    events = client.get('/api/v1/delivery/tracking-events/').json()
    package_rows = packages.get('results', packages) if isinstance(packages, dict) else packages
    event_rows = events.get('results', events) if isinstance(events, dict) else events

    assert [row['package_number'] for row in package_rows] == ['PKG-A']
    assert [row['description'] for row in event_rows] == ['A event']


@override_settings(MEDIA_ROOT='/tmp/bfg-security-media')
@pytest.mark.parametrize('folder', ['../escape', '..', '/absolute', 'nested/folder', r'nested\folder'])
def test_media_folder_paths_reject_traversal(folder):
    with pytest.raises(ValueError):
        _workspace_folder_path(7, folder)


def test_media_upload_path_rejects_traversal_as_defense_in_depth():
    media = SimpleNamespace(workspace_id=7, _upload_folder='../../escape')
    with pytest.raises(ValueError):
        media_upload_to(media, 'payload.txt')


@pytest.mark.django_db
def test_custom_domain_cannot_be_reassigned_to_another_workspace():
    owner = _workspace('domain-owner')
    attacker = _workspace('domain-attacker')
    domain = WorkspaceDomain.objects.create(
        workspace=owner,
        hostname='shop.example.test',
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    with pytest.raises(DjangoValidationError):
        upsert_custom_workspace_domain(
            attacker,
            'shop.example.test',
            is_primary=True,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        )

    domain.refresh_from_db()
    assert domain.workspace_id == owner.id


@pytest.mark.django_db
def test_unverified_custom_domain_is_not_used_for_tenant_resolution():
    from bfg.common.middleware import _get_workspace_by_domain

    workspace = _workspace('pending-domain')
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname='pending.example.test',
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_PENDING,
    )

    assert _get_workspace_by_domain('pending.example.test') is None


@pytest.mark.django_db
def test_gateway_serialization_masks_secrets_and_preserves_them_on_masked_update():
    workspace = _workspace('gateway-secrets')
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name='Stripe',
        gateway_type='stripe',
        config={
            'secret_key': 'sk_test_private',
            'webhook_secret': 'whsec_private',
            'publishable_key': 'pk_test_public',
        },
        test_config={'api_key': 'sk_test_other'},
    )

    data = PaymentGatewaySerializer(gateway).data
    assert data['config']['secret_key'] == '********'
    assert data['config']['webhook_secret'] == '********'
    assert data['config']['publishable_key'] == 'pk_test_public'
    assert data['test_config']['api_key'] == '********'

    serializer = PaymentGatewaySerializer(
        gateway,
        data={'config': data['config']},
        partial=True,
    )
    assert serializer.is_valid(), serializer.errors
    serializer.save()
    gateway.refresh_from_db()
    assert gateway.config['secret_key'] == 'sk_test_private'
    assert gateway.config['webhook_secret'] == 'whsec_private'


@pytest.mark.django_db
def test_me_profile_cannot_mass_assign_login_email_or_username():
    user = User.objects.create_user(
        username='original-user',
        email='original@example.test',
        password='x',
    )
    serializer = MeSerializer(
        user,
        data={
            'username': 'attacker-chosen',
            'email': 'attacker@example.test',
            'first_name': 'Updated',
        },
        partial=True,
    )
    assert serializer.is_valid(), serializer.errors
    serializer.save()
    user.refresh_from_db()
    assert user.username == 'original-user'
    assert user.email == 'original@example.test'
    assert user.first_name == 'Updated'


@pytest.mark.django_db
def test_cart_service_rejects_variant_from_another_product():
    workspace = _workspace('variant-owner')
    _, customer = _customer(workspace, 'variant-shopper')
    product = Product.objects.create(
        workspace=workspace, name='Expensive', slug='expensive', price=Decimal('100.00'),
    )
    cheap_product = Product.objects.create(
        workspace=workspace, name='Cheap', slug='cheap', price=Decimal('0.01'),
    )
    cheap_variant = ProductVariant.objects.create(
        product=cheap_product, name='Cheap variant', sku='CHEAP-1', price=Decimal('0.01'),
    )
    cart = Cart.objects.create(workspace=workspace, customer=customer)

    with pytest.raises(ValueError, match='does not belong'):
        CartService(workspace=workspace, user=customer.user).add_to_cart(
            cart,
            product,
            1,
            cheap_variant,
        )

    assert CartItem.objects.filter(cart=cart).count() == 0


@pytest.mark.django_db
def test_inquiry_cannot_be_assigned_to_user_from_another_workspace():
    workspace = _workspace('inquiry-owner')
    other_workspace = _workspace('inquiry-other')
    owner = User.objects.create_user(username='inquiry-owner-user', password='x')
    outsider = User.objects.create_user(username='inquiry-outsider', password='x')
    _staff(owner, workspace, 'admin')
    _staff(outsider, other_workspace, 'admin')
    inquiry = Inquiry.objects.create(
        workspace=workspace,
        name='Customer',
        email='customer@example.test',
        message='Help',
    )

    with pytest.raises(APIValidationError):
        InquiryService(workspace=workspace, user=owner).assign_inquiry(
            inquiry,
            outsider.id,
        )

    inquiry.refresh_from_db()
    assert inquiry.assigned_to_id is None
