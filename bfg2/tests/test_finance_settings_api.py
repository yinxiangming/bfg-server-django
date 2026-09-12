"""The finance settings endpoints a shop admin works with: tax rates, and the
currency list that every workspace on the platform shares."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Customer, StaffMember, StaffRole, User, Workspace
from bfg.finance.models import Currency, TaxRate, Wallet

CURRENCIES_URL = '/api/v1/finance/currencies/'
TAX_RATES_URL = '/api/v1/finance/tax-rates/'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Finance WS', slug='finance-ws', is_active=True)


def signed_in(user, workspace):
    api = APIClient()
    api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


@pytest.fixture
def admin_client(workspace):
    user = User.objects.create_user(username='fin-admin', email='admin@test.com', password='x')
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return signed_in(user, workspace)


@pytest.fixture
def shopper_client(workspace):
    user = User.objects.create_user(username='fin-shopper', email='shopper@test.com', password='x')
    Customer.objects.create(workspace=workspace, user=user, is_active=True)
    return signed_in(user, workspace)


@pytest.fixture
def superuser_client(workspace):
    user = User.objects.create_user(username='fin-root', email='root@test.com', password='x', is_superuser=True)
    return signed_in(user, workspace)


@pytest.fixture
def usd(db):
    return Currency.objects.create(code='USD', name='US Dollar', symbol='$', is_active=True)


def test_admin_can_create_a_tax_rate_for_their_workspace(admin_client, workspace):
    response = admin_client.post(TAX_RATES_URL, {'name': 'GST', 'rate': '15.00', 'country': 'NZ'}, format='json')

    assert response.status_code == 201, response.data
    assert TaxRate.objects.get(id=response.data['id']).workspace == workspace


@pytest.mark.parametrize('who', ['shopper_client', 'admin_client'])
def test_only_a_superuser_can_change_the_shared_currency_list(who, request, usd):
    client = request.getfixturevalue(who)

    assert client.get(CURRENCIES_URL).status_code == 200
    assert client.post(CURRENCIES_URL, {'code': 'XTS', 'name': 'Test', 'symbol': 'T'}, format='json').status_code == 403
    assert client.patch(f'{CURRENCIES_URL}{usd.id}/', {'symbol': 'US$'}, format='json').status_code == 403
    assert client.delete(f'{CURRENCIES_URL}{usd.id}/').status_code == 403
    usd.refresh_from_db()
    assert (usd.symbol, usd.is_active) == ('$', True)


def test_superuser_can_add_a_currency(superuser_client):
    response = superuser_client.post(CURRENCIES_URL, {'code': 'XTS', 'name': 'Test', 'symbol': 'T'}, format='json')

    assert response.status_code == 201, response.data


def test_deleting_a_currency_that_is_in_use_is_refused_with_a_reason(superuser_client, workspace, usd):
    buyer = User.objects.create_user(username='fin-buyer', email='buyer@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=buyer, is_active=True)
    Wallet.objects.create(
        workspace=workspace, customer=customer, currency=usd,
        cash_balance=Decimal('0'), credit_balance=Decimal('0'), credit_limit=Decimal('0'),
    )

    response = superuser_client.delete(f'{CURRENCIES_URL}{usd.id}/')

    assert response.status_code == 409
    assert 'USD' in response.data['detail']
    assert Currency.objects.filter(id=usd.id).exists()


def test_superuser_can_delete_a_currency_nothing_uses(superuser_client, usd):
    assert superuser_client.delete(f'{CURRENCIES_URL}{usd.id}/').status_code == 204
    assert not Currency.objects.filter(id=usd.id).exists()
