"""
Read-only mode: what a workspace whose plan has lapsed may still do.

The switch is off by default and these tests start from that, because the
dangerous failure here is not a write getting through — it is every workspace on
a deployment that has never sold anything being locked at once, since none of
them has an entitlement row.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory
from django.test.utils import override_settings
from django.urls import resolve
from django.utils import timezone
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from bfg.common.middleware import set_current_workspace
from bfg.common.models import APIKey, Customer, StaffMember, StaffRole, Workspace
from bfg.core.read_only import is_exempt
from bfg.platform.middleware import READ_ONLY_CODE, ReadOnlyWorkspaceMiddleware
from bfg.platform.models import WorkspaceEntitlement
from bfg.platform.services import entitlements, read_only
from bfg.shop.models import Order, Store

User = get_user_model()
pytestmark = pytest.mark.django_db

TAGS_URL = '/api/v1/customer-tags/'
ME_URL = '/api/v1/me/'
STOREFRONT_CONFIG_URL = '/api/v1/settings/storefront/'


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_caches():
    """Both the read-only answer and ``grace_days`` are cached across a minute."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def shop(db):
    return Workspace.objects.create(name='Lapsed', slug='lapsed', is_active=True)


@pytest.fixture
def staff(shop):
    user = User.objects.create_user(username='keeper', email='keeper@test.com', password='pw')
    role = StaffRole.objects.create(workspace=shop, name='Admin', code='admin', is_system=True)
    StaffMember.all_objects.create(workspace=shop, user=user, role=role, is_active=True)
    return user


@pytest.fixture
def staff_client(shop, staff):
    """Signed in for real, not through ``force_authenticate``.

    The middleware reads ``request.user`` before the view does, and some views
    (order status, for one) read the ``is_staff_member`` it works out from it.
    ``force_authenticate`` only reaches the DRF request, so the middleware would
    see an anonymous caller.
    """
    client = APIClient()
    client.force_login(staff)
    client.credentials(HTTP_X_WORKSPACE_ID=str(shop.id))
    return client


@pytest.fixture
def visitor(shop):
    """Anonymous, as a shopper is, with the workspace named by header."""
    client = APIClient()
    client.credentials(HTTP_X_WORKSPACE_ID=str(shop.id))
    return client


@pytest.fixture
def read_only_on(settings):
    settings.BFG_READ_ONLY_WHEN_UNENTITLED = True
    return settings


def entitle(workspace, *, months=1):
    """Give ``workspace`` the base plan, the way a payment would."""
    return entitlements.grant(workspace, months=months, reason='paid')


def lapsed_entitlement(workspace):
    """A base plan whose period, and its grace, ran out long ago."""
    return WorkspaceEntitlement.all_objects.create(
        workspace=workspace,
        key=WorkspaceEntitlement.KEY_BASE_PLAN,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() - timedelta(days=90),
    )


def refused_as_read_only(response) -> bool:
    return response.status_code == 403 and response.json().get('code') == READ_ONLY_CODE


# ── the switch ───────────────────────────────────────────────────────


def test_the_switch_is_off_unless_a_deployment_sets_it(shop):
    # No entitlement row anywhere, which is what a deployment that has never sold
    # anything looks like. Nothing may be read-only on the strength of that.
    assert read_only.enabled() is False
    assert read_only.is_read_only(shop) is False


def test_with_the_switch_off_nothing_is_asked_of_the_database(shop, django_assert_num_queries):
    with django_assert_num_queries(0):
        assert read_only.is_read_only(shop) is False


def test_with_the_switch_off_a_workspace_with_no_plan_still_writes(staff_client):
    response = staff_client.post(TAGS_URL, {'name': 'VIP'}, format='json')

    assert response.status_code == 201, response.data


def test_with_the_switch_off_the_middleware_stops_before_it_costs_anything(
    shop, django_assert_num_queries
):
    """Not one extra query on the request path of a deployment that has not opted in."""
    request = RequestFactory().post(TAGS_URL)
    request.workspace = shop
    match = resolve(TAGS_URL)

    with django_assert_num_queries(0):
        refusal = ReadOnlyWorkspaceMiddleware(lambda r: None).process_view(
            request, match.func, match.args, match.kwargs
        )

    assert refusal is None


# ── the decision ─────────────────────────────────────────────────────


def test_a_workspace_with_a_live_plan_is_not_read_only(read_only_on, shop):
    entitle(shop)

    assert read_only.is_read_only(shop) is False


def test_a_workspace_whose_plan_ran_out_past_its_grace_is_read_only(read_only_on, shop):
    lapsed_entitlement(shop)

    assert read_only.is_read_only(shop) is True


def test_a_workspace_still_inside_its_grace_is_not_read_only(read_only_on, shop):
    WorkspaceEntitlement.all_objects.create(
        workspace=shop,
        key=WorkspaceEntitlement.KEY_BASE_PLAN,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        # Inside the 14 days ``grace_days`` defaults to.
        current_period_end=timezone.now() - timedelta(days=1),
    )

    assert read_only.is_read_only(shop) is False


def test_no_workspace_is_never_read_only(read_only_on):
    assert read_only.is_read_only(None) is False


def test_the_answer_is_reused_for_a_while(read_only_on, shop, django_assert_num_queries):
    lapsed_entitlement(shop)
    assert read_only.is_read_only(shop) is True

    with django_assert_num_queries(0):
        assert read_only.is_read_only(shop) is True


def test_a_question_that_cannot_be_answered_leaves_the_workspace_writable(
    read_only_on, shop, monkeypatch, caplog
):
    def explode(*args, **kwargs):
        raise RuntimeError('the database is on fire')

    monkeypatch.setattr(entitlements, 'is_entitled', explode)

    assert read_only.is_read_only(shop) is False
    assert any(record.levelname == 'ERROR' for record in caplog.records)
    # Nothing was cached, so the next request asks again rather than inheriting a
    # minute of a failure that may already be over.
    assert cache.get(f'platform:read-only:{shop.pk}') is None


def test_a_failure_to_decide_does_not_stop_a_write(read_only_on, shop, staff_client, monkeypatch):
    lapsed_entitlement(shop)
    monkeypatch.setattr(
        entitlements, 'is_entitled', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('down'))
    )

    response = staff_client.post(TAGS_URL, {'name': 'Still trading'}, format='json')

    assert response.status_code == 201, response.data


# ── paying again ─────────────────────────────────────────────────────


def test_a_new_period_makes_the_workspace_writable_again(read_only_on, shop, staff_client):
    """The next request after a payment is served, not the one a minute later.

    ``grant`` drops the cached answer itself, so this is what a renewal looks like
    from the outside with nothing else having to remember.
    """
    lapsed_entitlement(shop)
    assert refused_as_read_only(staff_client.post(TAGS_URL, {'name': 'Nope'}, format='json'))

    entitle(shop)

    response = staff_client.post(TAGS_URL, {'name': 'Back in business'}, format='json')
    assert response.status_code == 201, response.data


def test_a_period_written_without_forgetting_takes_up_to_the_cache_window(read_only_on, shop):
    """What anything writing a period *without* calling ``forget`` would look like.

    The documented cost of not paying a query on every write, and the reason
    ``forget`` exists for whatever else comes to settle a payment.
    """
    lapsed_entitlement(shop)
    assert read_only.is_read_only(shop) is True

    WorkspaceEntitlement.all_objects.create(
        workspace=shop,
        key=WorkspaceEntitlement.KEY_BASE_PLAN,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() + timedelta(days=30),
    )

    assert read_only.is_read_only(shop) is True
    read_only.forget(shop)
    assert read_only.is_read_only(shop) is False


# ── what the middleware refuses ──────────────────────────────────────


def test_reads_are_never_refused(read_only_on, shop, staff_client):
    lapsed_entitlement(shop)

    response = staff_client.get(TAGS_URL)

    assert response.status_code == 200


def test_a_write_is_refused_with_its_own_code(read_only_on, shop, staff_client):
    lapsed_entitlement(shop)

    response = staff_client.post(TAGS_URL, {'name': 'VIP'}, format='json')

    assert response.status_code == 403
    body = response.json()
    assert body['code'] == READ_ONLY_CODE
    assert body['detail']


def test_an_entitled_workspace_writes_with_the_switch_on(read_only_on, shop, staff_client):
    entitle(shop)

    response = staff_client.post(TAGS_URL, {'name': 'VIP'}, format='json')

    assert response.status_code == 201, response.data


@pytest.mark.parametrize('method', ['put', 'patch', 'delete'])
def test_every_unsafe_method_is_refused(read_only_on, shop, staff_client, method):
    lapsed_entitlement(shop)

    response = getattr(staff_client, method)(f'{TAGS_URL}1/', {}, format='json')

    assert refused_as_read_only(response)


def test_a_shopper_may_browse_but_not_register_or_order(read_only_on, shop, visitor):
    lapsed_entitlement(shop)

    assert visitor.get('/api/v1/store/products/').status_code == 200
    assert refused_as_read_only(
        visitor.post(
            '/api/v1/store/auth/register/',
            {'email': 'new@shopper.test', 'password': 'pw12345678'},
            format='json',
        )
    )
    assert refused_as_read_only(
        visitor.post('/api/v1/store/cart/add_item/', {'product': 1, 'quantity': 1}, format='json')
    )


# ── API keys ─────────────────────────────────────────────────────────


_REST_FRAMEWORK_API_KEY = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'config.authentication.APIKeyAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
}


@pytest.fixture
def api_key_auth():
    """Point DRF at the API-key authenticator, as a deployment serving integrations does.

    ``api_settings.reload()`` alone is not enough — ``APIView.authentication_classes``
    was bound to the tuple read at import time. Copied from the API-key end-to-end
    tests, which explain it at greater length.
    """
    from rest_framework.views import APIView

    previous = APIView.authentication_classes
    with override_settings(REST_FRAMEWORK=_REST_FRAMEWORK_API_KEY):
        api_settings.reload()
        APIView.authentication_classes = api_settings.DEFAULT_AUTHENTICATION_CLASSES
        try:
            yield
        finally:
            APIView.authentication_classes = previous
            api_settings.reload()


@pytest.fixture
def api_key(shop, staff):
    set_current_workspace(shop)
    try:
        instance, secret = APIKey.create_key(shop, 'Integration', created_by=staff)
    finally:
        set_current_workspace(None)
    return instance.prefix, secret


def test_an_api_key_write_is_refused_too(read_only_on, shop, api_key_auth, api_key):
    """The path an integration writes on, and the one a guard is easiest to miss.

    No ``X-Workspace-ID``: the workspace middleware deliberately leaves an
    API-key request tenant-less and lets the authentication class bind the
    workspace from the key — which happens after every middleware has run.
    """
    lapsed_entitlement(shop)
    prefix, secret = api_key
    client = APIClient()

    response = client.post(
        TAGS_URL, {'name': 'VIP'}, format='json',
        HTTP_X_API_KEY=prefix, HTTP_X_API_SECRET=secret,
    )

    assert refused_as_read_only(response)


def test_an_api_key_write_goes_through_when_the_plan_is_live(
    read_only_on, shop, api_key_auth, api_key
):
    entitle(shop)
    prefix, secret = api_key
    client = APIClient()

    response = client.post(
        TAGS_URL, {'name': 'VIP'}, format='json',
        HTTP_X_API_KEY=prefix, HTTP_X_API_SECRET=secret,
    )

    assert response.status_code == 201, response.data


def test_an_api_key_read_is_not_refused(read_only_on, shop, api_key_auth, api_key):
    lapsed_entitlement(shop)
    prefix, secret = api_key
    client = APIClient()

    response = client.get(TAGS_URL, HTTP_X_API_KEY=prefix, HTTP_X_API_SECRET=secret)

    assert response.status_code == 200


# ── the whitelist ────────────────────────────────────────────────────

# Every write still allowed while a workspace is read only, spelled as the URL
# that reaches it. The reasons are on the views themselves and gathered in
# ``bfg.platform.middleware``; this is the list that proves each mark is
# actually wired to the route it was meant for.
EXEMPT_WRITES = [
    # Settling a platform bill, and the gateway confirming the payment (the
    # callback below). Without both, a lapsed workspace has no way back.
    '/api/v1/platform/console/workspaces/1/invoices/PLAT-1-202608/pay/',
    '/api/v1/platform/workspaces/1/checkout/',
    '/api/v1/platform/webhooks/stripe/',
    # Account operations. Somebody has to be able to get in and pay.
    '/api/v1/me/change-password/',
    '/api/v1/me/reset-password/',
    # Money a shopper has already parted with, reported by the gateway.
    '/api/v1/store/payments/callback/stripe/',
    # Getting goods to shoppers who have already paid.
    '/api/v1/delivery/carriers/1/ship_order/',
    '/api/v1/delivery/consignments/CN1/update_status/',
    '/api/v1/delivery/consignments/CN1/add_tracking_event/',
    '/api/v1/delivery/consignments/CN1/generate_label/',
]

REFUSED_WRITES = [
    # New business: a read-only shop takes none.
    '/api/v1/store/auth/register/',
    '/api/v1/store/cart/add_item/',
    '/api/v1/store/cart/checkout/',
    '/api/v1/store/cart/guest_checkout/',
    '/api/v1/shop/orders/',
    # Changing what is owed, rather than delivering what was bought.
    '/api/v1/shop/orders/1/mark-paid/',
    '/api/v1/shop/orders/1/refund/',
    '/api/v1/shop/orders/1/cancel/',
    '/api/v1/shop/orders/1/update_items/',
    # Read-only mode deletes nothing, and creates no shipments of its own.
    '/api/v1/delivery/consignments/',
    # The rest of the console: paying is the only write on it that is allowed.
    '/api/v1/platform/console/workspaces/1/extensions/reviews/activate/',
    # Ordinary shop administration.
    '/api/v1/customer-tags/',
    '/api/v1/shop/products/',
    '/api/v1/me/',
    # Writes that cost the deployment money or storage for a workspace that is
    # not paying for either.
    '/api/v1/store/analytics/collect/',
]


def _exempt(path, method='POST', **kwargs):
    match = resolve(path)
    request = getattr(RequestFactory(), method.lower())(path, **kwargs)
    return is_exempt(match.func, request, match.kwargs)


@pytest.mark.parametrize('path', EXEMPT_WRITES)
def test_each_allowed_write_is_marked_on_the_route_that_serves_it(path):
    assert _exempt(path) is True


@pytest.mark.parametrize('path', REFUSED_WRITES)
def test_nothing_else_is_marked(path):
    assert _exempt(path) is False


def test_an_export_needs_no_mark_because_it_is_a_read(read_only_on, shop, staff_client):
    """Every export in this library is a GET, so read-only mode never touches one."""
    lapsed_entitlement(shop)

    for path in ('/api/v1/web/sites/export/', '/api/v1/finance/invoices/', '/api/v1/shop/orders/'):
        assert not refused_as_read_only(staff_client.get(path)), path


def test_changing_your_own_password_is_still_allowed(read_only_on, shop, staff, staff_client):
    lapsed_entitlement(shop)

    response = staff_client.post(
        '/api/v1/me/change-password/',
        {'old_password': 'pw', 'new_password': 'newpw12345', 'confirm_password': 'newpw12345'},
        format='json',
    )

    assert response.status_code == 200, response.data


# ── fulfilling orders that were already paid for ─────────────────────


def _order(workspace, staff_user, payment_status):
    store = Store.objects.create(workspace=workspace, name='Shop', code=f'shop-{payment_status}')
    customer = Customer.objects.create(workspace=workspace, user=staff_user)
    return Order.objects.create(
        workspace=workspace,
        customer=customer,
        store=store,
        order_number=f'ORD-{payment_status}',
        payment_status=payment_status,
        subtotal=Decimal('10.00'),
        total=Decimal('10.00'),
    )


def test_a_paid_order_can_still_be_moved_along(read_only_on, shop, staff, staff_client):
    lapsed_entitlement(shop)
    order = _order(shop, staff, 'paid')

    response = staff_client.post(
        f'/api/v1/shop/orders/{order.pk}/update_status/', {'status': 'shipped'}, format='json'
    )

    assert not refused_as_read_only(response)
    assert response.status_code == 200, response.data


def test_an_unpaid_order_cannot(read_only_on, shop, staff, staff_client):
    lapsed_entitlement(shop)
    order = _order(shop, staff, 'pending')

    response = staff_client.post(
        f'/api/v1/shop/orders/{order.pk}/update_status/', {'status': 'shipped'}, format='json'
    )

    assert refused_as_read_only(response)


# ── what the clients are told ────────────────────────────────────────


def test_me_carries_the_flag_for_the_admin(read_only_on, shop, staff_client):
    lapsed_entitlement(shop)

    body = staff_client.get(ME_URL).json()

    assert body['workspace_read_only'] is True


def test_me_says_false_while_the_plan_is_live(read_only_on, shop, staff_client):
    entitle(shop)

    assert staff_client.get(ME_URL).json()['workspace_read_only'] is False


def test_me_says_false_when_the_deployment_has_not_switched_this_on(shop, staff_client):
    assert staff_client.get(ME_URL).json()['workspace_read_only'] is False


def test_the_storefront_config_tells_a_visitor(read_only_on, shop, visitor):
    lapsed_entitlement(shop)

    body = visitor.get(STOREFRONT_CONFIG_URL).json()

    assert body['read_only'] is True
    # The fields the storefront already reads are untouched.
    assert body['workspace_id'] == shop.id
    assert 'site_name' in body


def test_the_storefront_flag_is_not_stuck_behind_the_config_cache(read_only_on, shop, visitor):
    """The config is cached for minutes; whether the shop is trading is not."""
    lapsed_entitlement(shop)
    assert visitor.get(STOREFRONT_CONFIG_URL).json()['read_only'] is True

    entitle(shop)

    assert visitor.get(STOREFRONT_CONFIG_URL).json()['read_only'] is False
