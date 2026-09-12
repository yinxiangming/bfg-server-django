"""Finance settings a shop owns: the currencies it offers, its invoice settings,
and the address on its brand."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from bfg.common.models import Address, Customer, Settings, StaffMember, StaffRole, User, Workspace
from bfg.finance.models import Brand, Currency, Invoice, InvoiceSettings
from bfg.finance.services import InvoiceService

CURRENCIES_URL = '/api/v1/finance/currencies/'
INVOICE_SETTINGS_URL = '/api/v1/finance/invoice-settings/'
BRANDS_URL = '/api/v1/finance/brands/'
ADDRESSES_URL = '/api/v1/addresses/'


@pytest.fixture
def workspace(db):
    workspace = Workspace.objects.create(name='Shop WS', slug='shop-ws', is_active=True)
    Settings.objects.update_or_create(workspace=workspace, defaults={'default_currency': 'NZD'})
    return workspace


@pytest.fixture
def currencies(db):
    return {
        code: Currency.objects.create(code=code, name=code, symbol=symbol, is_active=True)
        for code, symbol in (('NZD', 'NZ$'), ('USD', '$'), ('AUD', 'A$'))
    }


def signed_in(user, workspace):
    api = APIClient()
    api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


def staff_client_for(workspace, username, role_code):
    user = User.objects.create_user(username=username, email=f'{username}@test.com', password='x')
    role, _ = StaffRole.objects.get_or_create(workspace=workspace, code=role_code, defaults={'name': role_code})
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return signed_in(user, workspace)


@pytest.fixture
def admin_client(workspace):
    return staff_client_for(workspace, 'shop-admin', 'admin')


@pytest.fixture
def staff_client(workspace):
    return staff_client_for(workspace, 'shop-staff', 'staff')


def rows_of(response):
    return response.data['results'] if isinstance(response.data, dict) else response.data


def by_code(response):
    return {row['code']: row for row in rows_of(response)}


def enabled_flags(client):
    return {code: row['is_enabled'] for code, row in by_code(client.get(CURRENCIES_URL)).items()}


# The currencies a shop offers

def test_a_shop_that_never_chose_offers_every_active_currency(admin_client, currencies):
    rows = by_code(admin_client.get(CURRENCIES_URL))

    assert {code: row['is_enabled'] for code, row in rows.items()} == {'NZD': True, 'USD': True, 'AUD': True}
    assert [code for code, row in rows.items() if row['is_default']] == ['NZD']


def test_switching_a_currency_off_leaves_it_out_of_the_enabled_list(admin_client, workspace, currencies):
    response = admin_client.post(f"{CURRENCIES_URL}{currencies['USD'].id}/disable/")

    assert response.status_code == 200, response.data
    assert response.data['is_enabled'] is False
    assert enabled_flags(admin_client) == {'NZD': True, 'USD': False, 'AUD': True}
    assert set(by_code(admin_client.get(CURRENCIES_URL, {'enabled': 'true'}))) == {'NZD', 'AUD'}
    assert sorted(Settings.objects.get(workspace=workspace).enabled_currencies) == ['AUD', 'NZD']


def test_switching_a_currency_back_on(admin_client, currencies):
    admin_client.post(f"{CURRENCIES_URL}{currencies['USD'].id}/disable/")

    response = admin_client.post(f"{CURRENCIES_URL}{currencies['USD'].id}/enable/")

    assert response.status_code == 200, response.data
    assert enabled_flags(admin_client)['USD'] is True


def test_the_default_currency_cannot_be_switched_off(admin_client, currencies):
    response = admin_client.post(f"{CURRENCIES_URL}{currencies['NZD'].id}/disable/")

    assert response.status_code == 400
    assert 'default currency' in response.data['detail']


def test_only_a_workspace_admin_chooses_the_currencies(staff_client, currencies):
    assert staff_client.post(f"{CURRENCIES_URL}{currencies['USD'].id}/disable/").status_code == 403


def test_another_shops_choice_does_not_leak(admin_client, currencies):
    other = Workspace.objects.create(name='Other WS', slug='other-ws', is_active=True)
    Settings.objects.update_or_create(workspace=other, defaults={'default_currency': 'NZD'})
    other_admin = staff_client_for(other, 'other-admin', 'admin')
    other_admin.post(f"{CURRENCIES_URL}{currencies['USD'].id}/disable/")

    assert enabled_flags(admin_client)['USD'] is True


def test_a_new_default_currency_is_switched_on_with_it(workspace, currencies):
    settings_obj = Settings.objects.get(workspace=workspace)
    settings_obj.enabled_currencies = ['NZD']
    settings_obj.save()

    settings_obj.default_currency = 'AUD'
    settings_obj.save(update_fields=['default_currency'])

    settings_obj.refresh_from_db()
    assert sorted(settings_obj.enabled_currencies) == ['AUD', 'NZD']


# Invoice settings

def test_admin_creates_the_invoice_settings_once(admin_client, workspace):
    payload = {'invoice_prefix': 'GS-', 'default_due_days': 14, 'default_footer': 'Thank you!', 'is_active': True}

    first = admin_client.post(INVOICE_SETTINGS_URL, payload, format='json')
    second = admin_client.post(INVOICE_SETTINGS_URL, payload, format='json')

    assert first.status_code == 201, first.data
    assert second.status_code == 400
    assert InvoiceSettings.objects.get(workspace=workspace).invoice_prefix == 'GS-'


def test_staff_read_the_invoice_settings_but_only_admins_change_them(admin_client, staff_client, workspace):
    admin_client.post(INVOICE_SETTINGS_URL, {'invoice_prefix': 'GS-', 'default_due_days': 14}, format='json')
    row = InvoiceSettings.objects.get(workspace=workspace)

    listed = staff_client.get(INVOICE_SETTINGS_URL)

    assert listed.status_code == 200
    assert [item['invoice_prefix'] for item in rows_of(listed)] == ['GS-']
    assert staff_client.patch(f'{INVOICE_SETTINGS_URL}{row.id}/', {'invoice_prefix': 'X-'}, format='json').status_code == 403
    assert admin_client.patch(f'{INVOICE_SETTINGS_URL}{row.id}/', {'invoice_prefix': 'X-'}, format='json').status_code == 200


def test_invoice_numbers_and_due_days_follow_the_settings(workspace):
    InvoiceSettings.objects.create(workspace=workspace, invoice_prefix='GS-', default_due_days=14)
    service = InvoiceService(workspace=workspace, user=None)

    assert service._generate_invoice_number() == 'GS-0001'
    assert service._default_due_days() == 14


def test_without_settings_invoices_keep_the_built_in_defaults(workspace):
    service = InvoiceService(workspace=workspace, user=None)

    assert service._generate_invoice_number() == 'INV-0001'
    assert service._default_due_days() == 30


def test_numbering_continues_from_the_last_invoice_with_the_prefix(workspace, currencies):
    InvoiceSettings.objects.create(workspace=workspace, invoice_prefix='GS-')
    buyer = User.objects.create_user(username='inv-buyer', email='inv-buyer@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=buyer, is_active=True)
    for number in ('GS-0007', 'INV-0042'):
        Invoice.objects.create(
            workspace=workspace, customer=customer, invoice_number=number, currency=currencies['NZD'],
            subtotal=Decimal('1'), tax=Decimal('0'), total=Decimal('1'),
            issue_date=date.today(), due_date=date.today(),
        )

    assert InvoiceService(workspace=workspace, user=None)._generate_invoice_number() == 'GS-0008'


# The address on a brand

def test_a_brand_takes_one_of_the_workspace_addresses(admin_client, workspace):
    address = Address.objects.create(
        workspace=workspace, full_name='GeekStudio', phone='021000000',
        address_line1='1 Queen Street', city='Auckland', country='NZ',
    )

    response = admin_client.post(BRANDS_URL, {'name': 'GeekStudio', 'address_id': address.id}, format='json')

    assert response.status_code == 201, response.data
    assert Brand.objects.get(id=response.data['id']).address == address
    assert response.data['address']['city'] == 'Auckland'


def test_a_brand_cannot_take_another_workspaces_address(admin_client):
    other = Workspace.objects.create(name='Other WS', slug='other-ws', is_active=True)
    foreign = Address.objects.create(
        workspace=other, full_name='Elsewhere', phone='1',
        address_line1='2 High Street', city='Wellington', country='NZ',
    )

    response = admin_client.post(BRANDS_URL, {'name': 'GeekStudio', 'address_id': foreign.id}, format='json')

    assert response.status_code == 400


def test_workspace_scope_lists_only_the_shops_own_addresses(workspace):
    root = User.objects.create_user(username='addr-root', email='addr-root@test.com', password='x', is_superuser=True)
    client = signed_in(root, workspace)
    own = Address.objects.create(
        workspace=workspace, full_name='Warehouse', phone='1',
        address_line1='3 Dock Road', city='Auckland', country='NZ',
    )
    buyer = User.objects.create_user(username='addr-buyer', email='addr-buyer@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=buyer, is_active=True)
    Address.objects.create(
        workspace=workspace, full_name='Buyer', phone='2', address_line1='4 Home Street',
        city='Auckland', country='NZ',
        content_type=ContentType.objects.get_for_model(Customer), object_id=customer.id,
    )

    response = client.get(ADDRESSES_URL, {'scope': 'workspace'})

    assert response.status_code == 200
    assert [row['id'] for row in rows_of(response)] == [own.id]
