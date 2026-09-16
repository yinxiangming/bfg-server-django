"""
The console's platform-administrator half: the numbers the deployment bills by.

``/api/v1/platform/console/variables/``, ``/meter-prices/``, ``/exchange-rates/``
and the two workspace paths ``/usage-cap/`` and ``/grants/`` are for the people who
run the deployment. Workspace owners share the rest of the console and none of
this, and are refused the same way for a workspace they own, one they do not and
one that does not exist.

Manifests are faked, as in ``test_console_workspaces``.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.extensions import registry
from bfg.common.extensions.manifest import SCOPE_PLATFORM, ExtensionManifest, Prerequisite
from bfg.common.models import StaffMember, StaffRole, Workspace, WorkspaceExtension
from bfg.finance.models import Currency, ExchangeRate
from bfg.platform.models import (
    MeterPrice,
    PlatformVariable,
    PlatformVariableChange,
    WorkspaceEntitlement,
    WorkspacePlatformProfile,
)
from bfg.platform.services import entitlements, exchange_rates, usage
from bfg.platform.services import platform_variables as variables
from bfg.platform.services.ownership import assign_workspace_owner

User = get_user_model()
pytestmark = pytest.mark.django_db

CONSOLE = '/api/v1/platform/console/'
VARIABLES = f'{CONSOLE}variables/'
METER_PRICES = f'{CONSOLE}meter-prices/'
RATES = f'{CONSOLE}exchange-rates/'
REFUSED_TO_OWNERS = {
    'code': 'platform_admin_required',
    'detail': 'Only platform administrators can use this part of the console.',
}

MANIFESTS = {
    'reviews': ExtensionManifest(key='reviews', name='Reviews', app_label='reviews_app'),
    'maps': ExtensionManifest(
        key='maps',
        name='Maps',
        app_label='maps_app',
        prerequisites=(
            Prerequisite(code='staff', message='Invite a member of staff first.', check=lambda workspace: False),
        ),
    ),
    'sign_in': ExtensionManifest(key='sign_in', name='Sign-in', scope=SCOPE_PLATFORM, app_label='sign_in_app'),
}


def usage_cap_url(workspace_id):
    return f'{CONSOLE}workspaces/{workspace_id}/usage-cap/'


def grants_url(workspace_id):
    return f'{CONSOLE}workspaces/{workspace_id}/grants/'


@pytest.fixture(autouse=True)
def fake_manifests(monkeypatch):
    monkeypatch.setattr(registry, '_discover', lambda: dict(MANIFESTS))
    registry.reset_cache()
    cache.clear()
    yield
    registry.reset_cache()
    cache.clear()


@pytest.fixture(autouse=True)
def platform_workspace(settings, db):
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = 'platform'
    return Workspace.objects.create(name='Platform', slug='platform', is_active=True)


def _user(username):
    return User.objects.create_user(username=username, email=f'{username}@example.com', password='x')


def join(workspace, user, role_code):
    role, _ = StaffRole.objects.get_or_create(workspace=workspace, code=role_code, defaults={'name': role_code})
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return user


@pytest.fixture
def operator(platform_workspace):
    return join(platform_workspace, _user('operator'), 'admin')


@pytest.fixture
def shop():
    workspace = Workspace.objects.create(name='Harbour Books', slug='harbour-books', is_active=True)
    assign_workspace_owner(workspace, _user('harbour-owner'))
    join(workspace, _user('harbour-admin'), 'admin')
    return workspace


@pytest.fixture
def shop_owner(shop):
    return User.objects.get(username='harbour-owner')


@pytest.fixture
def currencies(db):
    for code, name in (('USD', 'US Dollar'), ('NZD', 'New Zealand Dollar'), ('CNY', 'Chinese Yuan')):
        Currency.objects.update_or_create(
            code=code, defaults={'name': name, 'symbol': code, 'decimal_places': 2, 'is_active': True}
        )


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def priced(meter='vendor.lookup', cost='17.00', unit_size=1000, margin=None, days_ago=1):
    return MeterPrice.objects.create(
        meter=meter,
        vendor_cost=Decimal(cost),
        unit_size=unit_size,
        margin=None if margin is None else Decimal(margin),
        effective_from=timezone.now() - timedelta(days=days_ago),
    )


def stored_rate(from_code, to_code, day, value, source=ExchangeRate.SOURCE_FEED):
    return ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code=from_code),
        to_currency=Currency.objects.get(code=to_code),
        effective_date=day,
        rate=Decimal(value),
        source=source,
    )


def entry_for(rows, key, field='key'):
    return next(row for row in rows if row[field] == key)


# ── Who may use it ───────────────────────────────────────────────────


def _every_endpoint(client, workspace_id):
    return [
        client.get(VARIABLES),
        client.patch(f'{VARIABLES}grace_days/', {'value': 3, 'reason': 'why not'}, format='json'),
        client.get(METER_PRICES),
        client.post(
            METER_PRICES,
            {'meter': 'vendor.lookup', 'vendor_cost': '1', 'unit_size': 1},
            format='json',
        ),
        client.get(RATES),
        client.post(RATES, {'from': 'USD', 'to': 'NZD', 'rate': '1.7'}, format='json'),
        client.get(usage_cap_url(workspace_id)),
        client.patch(usage_cap_url(workspace_id), {'cap_points': '99'}, format='json'),
        client.post(grants_url(workspace_id), {'key': 'reviews', 'months': 1, 'reason': 'x'}, format='json'),
    ]


def _nothing_was_written():
    return not any(
        (
            PlatformVariable.objects.exists(),
            MeterPrice.objects.exists(),
            ExchangeRate.objects.exists(),
            WorkspaceEntitlement.all_objects.exists(),
            WorkspacePlatformProfile.objects.exclude(monthly_usage_cap_points=None).exists(),
        )
    )


def test_anonymous_callers_are_refused(shop):
    statuses = [response.status_code for response in _every_endpoint(client_for(), shop.id)]

    assert all(code in (401, 403) for code in statuses), statuses
    assert _nothing_was_written()


@pytest.mark.parametrize('who', ['the workspace owner', 'an admin of the workspace'])
def test_everyone_who_does_not_administer_the_platform_is_refused(shop, shop_owner, who):
    caller = {'the workspace owner': shop_owner, 'an admin of the workspace': User.objects.get(
        username='harbour-admin')}[who]

    responses = _every_endpoint(client_for(caller), shop.id)

    assert [response.status_code for response in responses] == [403] * 9
    assert all(response.data == REFUSED_TO_OWNERS for response in responses)
    assert _nothing_was_written()


def test_an_owner_is_told_no_more_about_a_workspace_that_does_not_exist_than_one_that_does(shop, shop_owner):
    """The refusal must not be a way of finding out which ids are workspaces."""
    client = client_for(shop_owner)

    theirs = client.get(usage_cap_url(shop.id))
    nobodys = client.get(usage_cap_url(shop.id + 5000))

    assert theirs.status_code == nobodys.status_code == 403
    assert theirs.data == nobodys.data == REFUSED_TO_OWNERS


def test_a_platform_administrator_naming_no_workspace_is_told_so(operator, shop):
    response = client_for(operator).get(usage_cap_url(shop.id + 5000))

    assert response.status_code == 404
    assert response.data == {'code': 'workspace_not_found', 'detail': 'Workspace not found.'}


# ── Platform variables ───────────────────────────────────────────────


def test_every_variable_is_listed_with_its_default_and_what_it_is_worth_now(operator):
    variables.set_variable('usage_margin', Decimal('0.45'), user=operator, reason='vendor put its prices up')

    response = client_for(operator).get(VARIABLES)

    assert response.status_code == 200
    listed = response.data
    assert [row['key'] for row in listed] == sorted(variables.VARIABLES)
    margin = entry_for(listed, 'usage_margin')
    assert margin['value'] == '0.45'
    assert margin['default'] == '0.30'
    assert margin['overridden'] is True
    assert margin['description']
    assert margin['last_change']['reason'] == 'vendor put its prices up'
    # The trail holds what was in force as it was stored — a JSON number, whose
    # shortest representation is 0.3 — rather than the spec's own scale.
    assert margin['last_change']['old_value'] == '0.3'
    assert margin['last_change']['changed_by']['username'] == 'operator'
    # One nobody has touched still says what it could be set to.
    untouched = entry_for(listed, 'grace_days')
    assert (untouched['value'], untouched['overridden'], untouched['last_change']) == (14, False, None)


def test_the_numbers_money_is_worked_out_from_are_strings_and_whole_numbers_are_not(operator):
    listed = client_for(operator).get(VARIABLES).data

    assert entry_for(listed, 'usage_margin')['kind'] == 'decimal'
    assert isinstance(entry_for(listed, 'usage_margin')['value'], str)
    assert isinstance(entry_for(listed, 'invoice_due_days')['value'], int)


def test_changing_a_variable_records_who_did_it_and_why(operator):
    response = client_for(operator).patch(
        f'{VARIABLES}grace_days/', {'value': 21, 'reason': 'matching the competition'}, format='json'
    )

    assert response.status_code == 200
    assert response.data['value'] == 21
    assert response.data['overridden'] is True
    assert variables.get_variable('grace_days') == 21
    change = PlatformVariableChange.objects.get()
    assert (change.old_value, change.new_value) == (14, 21)
    assert change.reason == 'matching the competition'
    assert change.changed_by == operator


def test_a_change_nobody_gave_a_reason_for_is_refused(operator):
    responses = [
        client_for(operator).patch(f'{VARIABLES}grace_days/', body, format='json')
        for body in ({'value': 21}, {'value': 21, 'reason': '   '})
    ]

    assert [response.status_code for response in responses] == [400, 400]
    assert all(response.data['code'] == 'reason_required' for response in responses)
    assert not PlatformVariable.objects.exists()
    assert not PlatformVariableChange.objects.exists()


def test_a_variable_this_deployment_does_not_declare_is_not_stored(operator):
    response = client_for(operator).patch(
        f'{VARIABLES}free_money/', {'value': 1, 'reason': 'please'}, format='json'
    )

    assert response.status_code == 404
    assert response.data['code'] == 'unknown_platform_variable'
    assert not PlatformVariable.objects.exists()


@pytest.mark.parametrize(
    'body, code',
    [
        ({'value': -1, 'reason': 'x'}, 'invalid_platform_variable'),
        ({'value': 'not a number', 'reason': 'x'}, 'invalid_platform_variable'),
        ({'value': 1.5, 'reason': 'x'}, 'invalid_platform_variable'),
        ({'reason': 'x'}, 'invalid_platform_variable'),
    ],
)
def test_a_value_the_variable_cannot_hold_is_refused(operator, body, code):
    response = client_for(operator).patch(f'{VARIABLES}grace_days/', body, format='json')

    assert response.status_code == 400
    assert response.data['code'] == code
    assert variables.get_variable('grace_days') == 14
    assert not PlatformVariableChange.objects.exists()


# ── What each meter costs ────────────────────────────────────────────


def test_a_meters_whole_history_is_listed_with_the_row_in_force_marked(operator):
    old = priced(cost='17.00', days_ago=40)
    current = priced(cost='19.00', days_ago=1)
    later = MeterPrice.objects.create(
        meter='vendor.lookup', vendor_cost=Decimal('21.00'), unit_size=1000,
        effective_from=timezone.now() + timedelta(days=30),
    )

    response = client_for(operator).get(METER_PRICES)

    assert response.status_code == 200
    meter = entry_for(response.data, 'vendor.lookup', field='meter')
    assert meter['in_force'] == current.pk
    assert [row['id'] for row in meter['prices']] == [later.pk, current.pk, old.pk]
    assert [row['in_force'] for row in meter['prices']] == [False, True, False]
    assert meter['prices'][1]['vendor_cost'] == '19.000000'
    assert meter['prices'][1]['uses_default_margin'] is True
    assert meter['prices'][1]['effective_margin'] == '0.30'
    assert meter['prices'][1]['points_per_unit'] == '0.02470000'


def test_one_meter_can_be_asked_for_on_its_own(operator):
    priced(meter='vendor.lookup')
    priced(meter='ai.tokens')

    response = client_for(operator).get(METER_PRICES, {'meter': 'ai.tokens'})

    assert [row['meter'] for row in response.data] == ['ai.tokens']


def test_pricing_a_meter_adds_a_row_and_leaves_the_old_one_exactly_as_it_was(operator):
    """The rule the whole billing record rests on: a price is added, never edited."""
    old = priced(cost='17.00', unit_size=1000, days_ago=40)
    before = (old.vendor_cost, old.unit_size, old.margin, old.effective_from)

    response = client_for(operator).post(
        METER_PRICES,
        {'meter': 'vendor.lookup', 'vendor_cost': '19.00', 'unit_size': 1000, 'margin': '0.5'},
        format='json',
    )

    assert response.status_code == 201
    old.refresh_from_db()
    assert (old.vendor_cost, old.unit_size, old.margin, old.effective_from) == before
    assert MeterPrice.objects.filter(meter='vendor.lookup').count() == 2
    added = MeterPrice.objects.exclude(pk=old.pk).get()
    assert response.data['in_force'] == added.pk
    assert [row['id'] for row in response.data['prices']] == [added.pk, old.pk]
    assert entry_for(response.data['prices'], added.pk, field='id')['uses_default_margin'] is False


def test_there_is_no_way_to_edit_or_delete_a_price(operator):
    price = priced()
    client = client_for(operator)

    responses = [
        client.patch(f'{METER_PRICES}{price.pk}/', {'vendor_cost': '1'}, format='json'),
        client.put(f'{METER_PRICES}{price.pk}/', {'vendor_cost': '1'}, format='json'),
        client.delete(f'{METER_PRICES}{price.pk}/'),
    ]

    assert all(response.status_code in (404, 405) for response in responses)
    price.refresh_from_db()
    assert price.vendor_cost == Decimal('17.000000')


def test_a_price_dated_ahead_does_not_change_what_is_billed_today(operator):
    current = priced(cost='17.00')
    when = (timezone.now() + timedelta(days=15)).isoformat()

    response = client_for(operator).post(
        METER_PRICES,
        {'meter': 'vendor.lookup', 'vendor_cost': '25.00', 'unit_size': 1000, 'effective_from': when},
        format='json',
    )

    assert response.status_code == 201
    assert response.data['in_force'] == current.pk


@pytest.mark.parametrize(
    'body',
    [
        {'meter': 'vendor.lookup', 'vendor_cost': '1'},
        {'meter': 'vendor.lookup', 'unit_size': 1000},
        {'vendor_cost': '1', 'unit_size': 1000},
        {'meter': 'vendor.lookup', 'vendor_cost': 'free', 'unit_size': 1000},
        {'meter': 'vendor.lookup', 'vendor_cost': '-1', 'unit_size': 1000},
        {'meter': 'vendor.lookup', 'vendor_cost': '1', 'unit_size': 0},
        {'meter': 'vendor.lookup', 'vendor_cost': '1', 'unit_size': 1000, 'effective_from': 'soon'},
    ],
)
def test_a_price_the_columns_cannot_hold_is_refused(operator, body):
    response = client_for(operator).post(METER_PRICES, body, format='json')

    assert response.status_code == 400
    assert response.data['code'] == 'invalid_meter_price'
    assert not MeterPrice.objects.exists()


# ── Exchange rates ───────────────────────────────────────────────────


def test_the_rates_most_recently_stored_are_listed_newest_first(operator, currencies):
    today = timezone.now().date()
    older = stored_rate('USD', 'NZD', today - timedelta(days=2), '1.600000')
    newer = stored_rate('USD', 'NZD', today, '1.700000')
    other = stored_rate('USD', 'CNY', today, '7.100000')

    response = client_for(operator).get(RATES)

    assert response.status_code == 200
    assert [row['id'] for row in response.data] == [other.pk, newer.pk, older.pk]
    assert response.data[1] == {
        'id': newer.pk, 'from': 'USD', 'to': 'NZD', 'rate': '1.700000',
        'effective_date': today.isoformat(), 'source': 'feed', 'entered_by': None,
    }


def test_the_listing_narrows_to_one_currency_and_is_bounded(operator, currencies):
    today = timezone.now().date()
    for day in range(4):
        stored_rate('USD', 'NZD', today - timedelta(days=day), '1.700000')
    stored_rate('USD', 'CNY', today, '7.100000')

    client = client_for(operator)

    assert {row['to'] for row in client.get(RATES, {'currency': 'nzd'}).data} == {'NZD'}
    assert {row['from'] for row in client.get(RATES, {'base': 'USD'}).data} == {'USD'}
    assert len(client.get(RATES, {'limit': 2}).data) == 2
    # Not a number: a listing is still a listing, served the default page.
    assert len(client.get(RATES, {'limit': 'lots'}).data) == 5


def test_a_rate_entered_by_hand_says_so_and_is_what_conversions_then_use(operator, currencies):
    day = timezone.now().date()

    response = client_for(operator).post(
        RATES, {'from': 'USD', 'to': 'NZD', 'rate': '1.655000', 'effective_date': day.isoformat()},
        format='json',
    )

    assert response.status_code == 201
    assert response.data['source'] == 'manual'
    assert response.data['entered_by']['username'] == 'operator'
    assert exchange_rates.convert(Decimal('10'), 'USD', 'NZD', on=day) == Decimal('16.550000')
    row = ExchangeRate.objects.get()
    assert (row.source, row.entered_by) == (ExchangeRate.SOURCE_MANUAL, operator)


def test_entering_a_rate_for_a_day_twice_corrects_it_rather_than_storing_both(operator, currencies):
    day = date(2026, 9, 1)
    client = client_for(operator)
    body = {'from': 'USD', 'to': 'NZD', 'effective_date': day.isoformat()}

    client.post(RATES, {**body, 'rate': '1.600000'}, format='json')
    corrected = client.post(RATES, {**body, 'rate': '1.700000'}, format='json')

    assert corrected.status_code == 201
    assert ExchangeRate.objects.count() == 1
    assert ExchangeRate.objects.get().rate == Decimal('1.700000')


@pytest.mark.parametrize(
    'body',
    [
        {'from': 'USD', 'to': 'NZD', 'rate': '0'},
        {'from': 'USD', 'to': 'NZD', 'rate': '-1.5'},
        {'from': 'USD', 'to': 'NZD', 'rate': 'about two'},
        {'from': 'USD', 'to': 'NZD'},
        {'from': 'USD', 'to': 'DOLLARS', 'rate': '1.7'},
        {'from': 'USD', 'to': 'USD', 'rate': '1'},
        {'from': 'USD', 'to': 'NZD', 'rate': '1.7', 'effective_date': 'yesterday'},
    ],
)
def test_a_rate_that_is_not_one_is_refused(operator, currencies, body):
    response = client_for(operator).post(RATES, body, format='json')

    assert response.status_code == 400
    assert response.data['code'] == 'invalid_exchange_rate'
    assert not ExchangeRate.objects.exists()


# ── One workspace's monthly usage cap ────────────────────────────────


def test_a_workspace_with_no_cap_of_its_own_follows_the_deployments(operator, shop):
    response = client_for(operator).get(usage_cap_url(shop.id))

    assert response.status_code == 200
    assert response.data == {
        'workspace': shop.id,
        'cap_points': None,
        'default_cap_points': '20.00',
        'effective_cap_points': '20.00',
        'source': 'platform',
    }


def test_a_cap_can_be_given_and_taken_away_again(operator, shop):
    client = client_for(operator)

    given = client.patch(usage_cap_url(shop.id), {'cap_points': '250.50'}, format='json')

    assert given.status_code == 200
    assert given.data['cap_points'] == '250.50'
    assert given.data['effective_cap_points'] == '250.50'
    assert given.data['source'] == 'workspace'
    assert usage.monthly_cap(Workspace.objects.get(pk=shop.pk)) == Decimal('250.50')

    taken_back = client.patch(usage_cap_url(shop.id), {'cap_points': None}, format='json')

    assert taken_back.data['cap_points'] is None
    assert taken_back.data['source'] == 'platform'
    assert WorkspacePlatformProfile.objects.get(workspace=shop).monthly_usage_cap_points is None


def test_a_cap_of_zero_is_not_the_same_as_no_cap_at_all(operator, shop):
    response = client_for(operator).patch(usage_cap_url(shop.id), {'cap_points': 0}, format='json')

    assert response.data['cap_points'] == '0.00'
    assert response.data['source'] == 'workspace'
    assert not usage.may_meter(Workspace.objects.get(pk=shop.pk))


@pytest.mark.parametrize(
    'body', [{'cap_points': '-1'}, {'cap_points': 'plenty'}, {'cap_points': '99999999999999'}, {}]
)
def test_a_cap_the_column_cannot_hold_is_refused(operator, shop, body):
    response = client_for(operator).patch(usage_cap_url(shop.id), body, format='json')

    assert response.status_code == 400
    assert response.data['code'] == 'invalid_usage_cap'
    assert not WorkspacePlatformProfile.objects.exclude(monthly_usage_cap_points=None).exists()


# ── Entitlements given rather than sold ──────────────────────────────


def test_granting_an_add_on_writes_a_period_and_says_it_was_given(operator, shop):
    response = client_for(operator).post(
        grants_url(shop.id), {'key': 'reviews', 'months': 3, 'reason': 'agreed with the owner'}, format='json'
    )

    assert response.status_code == 201
    granted = response.data['entitlement']
    assert (granted['key'], granted['status'], granted['source']) == ('reviews', 'active', 'granted')
    assert granted['reason'] == 'agreed with the owner'
    row = WorkspaceEntitlement.all_objects.get()
    assert row.workspace_id == shop.id
    assert row.current_period_end == entitlements.add_months(row.starts_at, 3)
    assert entitlements.is_entitled(shop, 'reviews')


def test_a_grant_can_be_made_never_to_expire_and_can_be_the_base_plan(operator, shop):
    client = client_for(operator)

    forever = client.post(
        grants_url(shop.id), {'key': 'reviews', 'never_expires': True, 'reason': 'bundled'}, format='json'
    )
    base_plan = client.post(
        grants_url(shop.id), {'key': '', 'months': 12, 'reason': 'first year'}, format='json'
    )

    assert forever.status_code == base_plan.status_code == 201
    assert forever.data['entitlement']['current_period_end'] is None
    assert base_plan.data['entitlement']['key'] == ''
    assert entitlements.is_entitled(shop, WorkspaceEntitlement.KEY_BASE_PLAN)


def test_a_workspace_that_already_holds_one_is_refused_rather_than_given_a_second(operator, shop):
    client = client_for(operator)
    first = client.post(grants_url(shop.id), {'key': 'reviews', 'months': 3, 'reason': 'one'}, format='json')

    again = client.post(grants_url(shop.id), {'key': 'reviews', 'months': 3, 'reason': 'two'}, format='json')

    assert again.status_code == 409
    assert again.data['code'] == 'already_entitled'
    assert again.data['entitlement']['id'] == first.data['entitlement']['id']
    assert WorkspaceEntitlement.all_objects.count() == 1


def test_an_entitlement_that_has_run_out_can_be_granted_again(operator, shop):
    """The refusal is about one that is live, not about one that ever existed."""
    WorkspaceEntitlement.all_objects.create(
        workspace=shop, key='reviews', source=WorkspaceEntitlement.SOURCE_GRANTED,
        status=WorkspaceEntitlement.STATUS_ENDED,
        starts_at=timezone.now() - timedelta(days=400),
        current_period_end=timezone.now() - timedelta(days=100),
    )

    response = client_for(operator).post(
        grants_url(shop.id), {'key': 'reviews', 'months': 1, 'reason': 'back again'}, format='json'
    )

    assert response.status_code == 201
    assert WorkspaceEntitlement.all_objects.count() == 2


@pytest.mark.parametrize(
    'body, code',
    [
        ({'key': 'reviews', 'reason': 'x'}, 'invalid_grant'),
        ({'key': 'reviews', 'months': 3, 'never_expires': True, 'reason': 'x'}, 'invalid_grant'),
        ({'key': 'reviews', 'months': 0, 'reason': 'x'}, 'invalid_grant'),
        ({'key': 'reviews', 'months': 1000, 'reason': 'x'}, 'invalid_grant'),
        ({'key': 'reviews', 'months': '3', 'reason': 'x'}, 'invalid_grant'),
        ({'key': 'reviews', 'months': 3}, 'invalid_grant'),
        ({'months': 3, 'reason': 'x'}, 'invalid_grant'),
        ({'key': 'nothing_of_the_sort', 'months': 3, 'reason': 'x'}, 'unknown_extension'),
        # Declared, but not something a workspace switches on.
        ({'key': 'sign_in', 'months': 3, 'reason': 'x'}, 'unknown_extension'),
    ],
)
def test_a_grant_that_does_not_say_what_or_for_how_long_is_refused(operator, shop, body, code):
    response = client_for(operator).post(grants_url(shop.id), body, format='json')

    assert response.status_code == 400
    assert response.data['code'] == code
    assert not WorkspaceEntitlement.all_objects.exists()


def test_granting_does_not_switch_an_extension_on_behind_the_workspaces_back(operator, shop):
    """What a workspace is entitled to and what it has switched on stay separate."""
    record = WorkspaceExtension.all_objects.create(
        workspace=shop, key='reviews', status=WorkspaceExtension.STATUS_INACTIVE, status_reason='deactivated'
    )

    response = client_for(operator).post(
        grants_url(shop.id), {'key': 'reviews', 'months': 3, 'reason': 'x'}, format='json'
    )

    assert response.status_code == 201
    assert response.data['extension'] == {
        'key': 'reviews', 'status': 'inactive', 'resumed': False, 'refusal': None
    }
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE


def test_an_extension_the_platform_paused_comes_back_with_the_entitlement(operator, shop, settings):
    settings.BFG_EXTENSION_ENTITLEMENT_CHECK = 'bfg.platform.services.entitlements.entitlement_check'
    record = WorkspaceExtension.all_objects.create(
        workspace=shop,
        key='reviews',
        status=WorkspaceExtension.STATUS_PAUSED,
        status_reason=entitlements.PAUSED_REASON,
    )

    response = client_for(operator).post(
        grants_url(shop.id), {'key': 'reviews', 'months': 3, 'reason': 'paid up'}, format='json'
    )

    assert response.status_code == 201
    assert response.data['extension'] == {
        'key': 'reviews', 'status': 'active', 'resumed': True, 'refusal': None
    }
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_ACTIVE


def test_a_grant_stands_even_when_what_it_paid_for_cannot_be_switched_back_on(operator, shop):
    WorkspaceExtension.all_objects.create(
        workspace=shop, key='maps', status=WorkspaceExtension.STATUS_PAUSED,
        status_reason=entitlements.PAUSED_REASON,
    )

    response = client_for(operator).post(
        grants_url(shop.id), {'key': 'maps', 'months': 3, 'reason': 'paid up'}, format='json'
    )

    assert response.status_code == 201
    assert response.data['extension']['resumed'] is False
    assert response.data['extension']['refusal']['code'] == 'prerequisite_failed'
    assert entitlements.is_entitled(shop, 'maps')


def test_granting_something_the_workspace_has_never_used_touches_no_extension_record(operator, shop):
    response = client_for(operator).post(
        grants_url(shop.id), {'key': 'reviews', 'months': 3, 'reason': 'x'}, format='json'
    )

    assert response.data['extension'] is None
    assert not WorkspaceExtension.all_objects.exists()
