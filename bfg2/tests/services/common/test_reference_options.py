"""Reference catalogs preserve configured data and use the shared option API."""
from zoneinfo import ZoneInfo

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from bfg.common.models import User, Workspace
from bfg.common.reference_data import currency_catalog, currency_options, currency_profile, timezone_options
from bfg.common.views import OptionsView
from bfg.finance.models import Currency


def test_timezones_are_real_unique_iana_identifiers():
    items = timezone_options()
    codes = [item['value'] for item in items]
    assert len(codes) > 400
    assert codes == sorted(set(codes))
    assert {'UTC', 'Pacific/Auckland', 'America/New_York', 'Europe/London'} <= set(codes)
    assert 'localtime' not in codes
    for code in codes:
        assert ZoneInfo(code).key == code


def test_currency_reference_has_current_codes_and_exact_minor_units():
    catalog = currency_catalog()
    assert catalog['published'] == '2026-09-17'
    assert len(catalog['currencies']) == 178
    assert currency_profile('kwd')['decimal_places'] == 3
    assert currency_profile('JPY')['decimal_places'] == 0
    assert currency_profile('CLF')['decimal_places'] == 4
    assert currency_profile('NZD')['decimal_places'] == 2
    assert currency_profile('XXX')['decimal_places'] is None
    assert currency_profile('not-a-currency') is None
    profile = currency_profile('NZD')
    profile['name'] = 'Changed'
    assert currency_profile('NZD')['name'] != 'Changed'


@pytest.mark.django_db
def test_reference_options_retain_custom_names_flags_and_historical_codes():
    Currency.objects.update_or_create(code='NZD', defaults={
        'name': 'Configured NZ dollars', 'symbol': 'NZ$', 'decimal_places': 2, 'is_active': False,
    })
    Currency.objects.update_or_create(code='BGN', defaults={
        'name': 'Saved lev', 'symbol': 'BGN', 'decimal_places': 2, 'is_active': True,
    })
    before = list(Currency.objects.order_by('pk').values())
    items = {item['code']: item for item in currency_options()}
    assert items['NZD']['name'] == 'Configured NZ dollars'
    assert items['NZD']['disabled'] is True
    assert items['BGN']['name'] == 'Saved lev'
    assert items['BGN']['disabled'] is False
    assert items['KWD']['decimal_places'] == 3
    assert items['XXX']['disabled'] is True
    assert list(Currency.objects.order_by('pk').values()) == before


@pytest.mark.django_db
def test_authenticated_options_discover_the_shared_provider():
    workspace = Workspace.objects.create(name='Reference options', slug='reference-options')
    user = User.objects.create_user(username='reference-user')
    request = APIRequestFactory().get('/api/v1/options/')
    request.workspace = workspace
    force_authenticate(request, user=user)
    response = OptionsView.as_view()(request)
    assert response.status_code == 200
    assert 'Pacific/Auckland' in {item['value'] for item in response.data['timezones']}
    assert 'KWD' in {item['value'] for item in response.data['currency_codes']}
    anonymous = APIRequestFactory().get('/api/v1/options/')
    anonymous.workspace = workspace
    assert OptionsView.as_view()(anonymous).status_code in (401, 403)
