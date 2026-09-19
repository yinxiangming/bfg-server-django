"""Direct staff order creation rejects foreign tenant relationships cleanly."""

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Address, Customer, User
from bfg.common.services import WorkspaceService
from bfg.shop.models import Store


@pytest.fixture
def direct_order_context(db):
    local_admin = User.objects.create_user(
        username='local-order-admin',
        email='local-order-admin@example.test',
        password='x',
    )
    foreign_admin = User.objects.create_user(
        username='foreign-order-admin',
        email='foreign-order-admin@example.test',
        password='x',
    )
    local_workspace = WorkspaceService(user=local_admin).create_workspace(
        name='Local Orders',
        slug='local-orders',
        owner_user=local_admin,
    )
    foreign_workspace = WorkspaceService(user=foreign_admin).create_workspace(
        name='Foreign Orders',
        slug='foreign-orders',
        owner_user=foreign_admin,
    )

    local_customer = Customer.objects.create(
        workspace=local_workspace,
        user=User.objects.create_user(username='local-customer'),
        is_active=True,
    )
    foreign_customer = Customer.objects.create(
        workspace=foreign_workspace,
        user=User.objects.create_user(username='foreign-customer'),
        is_active=True,
    )
    local_store = Store.objects.create(
        workspace=local_workspace,
        name='Local Store',
        code='local-store',
        is_active=True,
    )
    foreign_store = Store.objects.create(
        workspace=foreign_workspace,
        name='Foreign Store',
        code='foreign-store',
        is_active=True,
    )
    local_address = Address.objects.create(
        workspace=local_workspace,
        content_object=local_customer,
        full_name='Local Customer',
        phone='1234567890',
        address_line1='1 Local Street',
        city='Auckland',
        country='NZ',
    )
    foreign_address = Address.objects.create(
        workspace=foreign_workspace,
        content_object=foreign_customer,
        full_name='Foreign Customer',
        phone='1234567890',
        address_line1='2 Foreign Street',
        city='Wellington',
        country='NZ',
    )

    client = APIClient()
    client.force_authenticate(local_admin)
    client.credentials(HTTP_X_WORKSPACE_ID=str(local_workspace.id))
    return {
        'client': client,
        'local_customer': local_customer,
        'foreign_customer': foreign_customer,
        'local_store': local_store,
        'foreign_store': foreign_store,
        'local_address': local_address,
        'foreign_address': foreign_address,
    }


@pytest.mark.parametrize(
    ('foreign_field', 'expected_error'),
    [
        ('customer_id', 'customer_id'),
        ('store_id', 'store_id'),
        ('shipping_address_id', 'shipping_address_id'),
        ('billing_address_id', 'billing_address_id'),
    ],
)
def test_direct_order_rejects_foreign_tenant_relationships(
    direct_order_context,
    foreign_field,
    expected_error,
):
    context = direct_order_context
    payload = {
        'customer_id': context['local_customer'].id,
        'store_id': context['local_store'].id,
        'shipping_address_id': context['local_address'].id,
        'billing_address_id': context['local_address'].id,
        'status': 'pending',
        'payment_status': 'pending',
    }
    payload[foreign_field] = {
        'customer_id': context['foreign_customer'].id,
        'store_id': context['foreign_store'].id,
        'shipping_address_id': context['foreign_address'].id,
        'billing_address_id': context['foreign_address'].id,
    }[foreign_field]

    response = context['client'].post('/api/v1/shop/orders/', payload, format='json')

    assert response.status_code == 400, response.data
    assert list(response.data) == [expected_error]
