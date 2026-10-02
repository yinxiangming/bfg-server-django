# -*- coding: utf-8 -*-
"""Address lookup for callers who are not signed in.

Checkout is where addresses are typed, and a shopper at checkout has no account,
so these endpoints answer guests. What stands in for sign-in is pinned here:

* a request has to name a shop, or it is refused rather than charged to a
  default one;
* a guest is throttled harder than a signed-in caller, per shop, so one busy
  storefront cannot use up a quiet one's allowance;
* the shop's monthly cap refuses a guest exactly as it refuses a member.

Google is stubbed throughout, as in the sibling modules. Rates are turned down to
single digits with ``override_settings`` rather than by making hundreds of
requests: what is being tested is that a limit exists and which bucket it belongs
to, not DRF's arithmetic.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIRequestFactory

from bfg.common.extensions import services as extension_services
from bfg.common.models import Customer, Settings, User, Workspace, WorkspaceExtension
from bfg.platform.models import MeterPrice, UsageRecord, WorkspacePlatformProfile

from apps.geo import views
from apps.geo.extension import METER_AUTOCOMPLETE, METER_GEOCODE, METER_PLACE_DETAILS
from apps.geo.models import AutocompleteSession

KEY = 'test-google-key'

CONFIG_URL = '/api/v1/geo/address/config/'
SUGGEST_URL = '/api/v1/geo/address/suggest/'
RESOLVE_URL = '/api/v1/geo/address/resolve/'
REVERSE_URL = '/api/v1/geo/address/reverse/'

# Where the provider is patched. Nothing below this line reaches Google, so every
# test that expects a refusal asserts on this mock rather than on the bill alone.
PROVIDER = 'apps.geo.services.google_maps.requests.request'

SUGGESTIONS = {'suggestions': [
    {'placePrediction': {
        'placeId': 'place-1',
        'text': {'text': '12 Queen Street, Auckland'},
        'structuredFormat': {
            'mainText': {'text': '12 Queen Street'},
            'secondaryText': {'text': 'Auckland, New Zealand'},
        },
    }},
]}

PLACE_DETAILS = {
    'id': 'place-1',
    'formattedAddress': '12 Queen Street, Auckland 1010, New Zealand',
    'displayName': {'text': 'Queen Street Store'},
    'location': {'latitude': -36.8485, 'longitude': 174.7633},
    'addressComponents': [
        {'longText': '12', 'shortText': '12', 'types': ['street_number']},
        {'longText': 'Queen Street', 'shortText': 'Queen St', 'types': ['route']},
        {'longText': 'Auckland', 'shortText': 'Auckland', 'types': ['locality']},
        {'longText': 'New Zealand', 'shortText': 'NZ', 'types': ['country']},
    ],
}

GEOCODE = {'status': 'OK', 'results': [{
    'place_id': 'p1',
    'formatted_address': '12 Queen Street, Auckland 1010, New Zealand',
    'geometry': {'location': {'lat': -36.8485, 'lng': 174.7633}},
    'address_components': [
        {'long_name': '12', 'short_name': '12', 'types': ['street_number']},
        {'long_name': 'Queen Street', 'short_name': 'Queen St', 'types': ['route']},
        {'long_name': 'Auckland', 'short_name': 'Auckland', 'types': ['locality']},
        {'long_name': 'New Zealand', 'short_name': 'NZ', 'types': ['country']},
    ],
}]}


def _ok(payload):
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = payload
    return response


@override_settings(GOOGLE_MAPS_API_KEY=KEY, IS_PROD=False)
class GuestFixture(TestCase):
    """A shop with address lookup on and priced, and nobody signed in."""

    def setUp(self):
        cache.clear()
        self.workspace = self.make_shop('shop-geo-guest')
        for meter in (METER_AUTOCOMPLETE, METER_PLACE_DETAILS, METER_GEOCODE):
            MeterPrice.objects.create(
                meter=meter,
                vendor_cost=Decimal('1'),
                unit_size=1,
                margin=Decimal('0'),
                effective_from=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
            )

    def make_shop(self, slug):
        """A workspace with the plugin on, the extension switched on, and a market."""
        workspace = Workspace.objects.create(name=slug, slug=slug)
        # A signal already gave the new workspace a Settings row.
        settings_row, _ = Settings.objects.get_or_create(workspace=workspace)
        settings_row.default_language = 'en'
        settings_row.country = 'NZ'
        settings_row.custom_settings = {'plugins': {'address_lookup': {'enabled': True}}}
        settings_row.save()

        WorkspaceExtension.all_objects.update_or_create(
            workspace=workspace,
            key='geo',
            defaults={'status': WorkspaceExtension.STATUS_ACTIVE},
        )
        extension_services.invalidate(workspace.pk)
        return workspace

    def switch_geo(self, *, on, workspace=None):
        workspace = workspace or self.workspace
        WorkspaceExtension.all_objects.update_or_create(
            workspace=workspace,
            key='geo',
            defaults={'status': WorkspaceExtension.STATUS_ACTIVE if on else WorkspaceExtension.STATUS_INACTIVE},
        )
        extension_services.invalidate(workspace.pk)

    def get(self, url, workspace=None, **params):
        """A guest request naming its shop the way a storefront's client does."""
        workspace = workspace or self.workspace
        return self.client.get(url, params, HTTP_X_WORKSPACE_ID=str(workspace.pk))

    def sign_in(self):
        """Become a shopper of this workspace with an account."""
        user = User.objects.create_user(username='shopper', email='s@example.com', password='pw')
        Customer.all_objects.create(workspace=self.workspace, user=user)
        self.client.force_login(user)
        return user

    def metered(self, meter, workspace=None):
        rows = UsageRecord.all_objects.filter(workspace=workspace or self.workspace, meter=meter)
        return sum((row.quantity for row in rows), Decimal('0'))


class GuestAccessTests(GuestFixture):
    """The four endpoints answer a caller with no account."""

    def test_config_is_answered_without_signing_in(self):
        response = self.get(CONFIG_URL)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['enabled'])
        self.assertEqual(response.json()['country_code'], 'NZ')
        self.assertNotIn(KEY, response.content.decode(), 'the key never crosses this line')

    def test_a_guest_can_type_an_address_and_pick_it(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            suggested = self.get(SUGGEST_URL, q='12 queen', session='tok')
        with mock.patch(PROVIDER, return_value=_ok(PLACE_DETAILS)):
            resolved = self.get(RESOLVE_URL, place_id='place-1', session='tok')

        self.assertEqual(suggested.status_code, 200)
        self.assertEqual(suggested.json()['results'][0]['place_id'], 'place-1')
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()['address_line1'], '12 Queen Street')
        # Billed exactly as the same lookup by a signed-in shopper would be.
        self.assertEqual(self.metered(METER_PLACE_DETAILS), 1)
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0, 'the session ended in an address')

    def test_a_guest_can_reverse_a_gps_fix(self):
        with mock.patch(PROVIDER, return_value=_ok(GEOCODE)):
            response = self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['country'], 'NZ')
        self.assertEqual(self.metered(METER_GEOCODE), 1)

    def test_the_extension_being_off_still_shuts_a_guest_out(self):
        """Opening this to guests did not open it to guests of shops that said no."""
        self.switch_geo(on=False)

        with mock.patch(PROVIDER) as request:
            self.assertFalse(self.get(CONFIG_URL).json()['enabled'])
            for url in (SUGGEST_URL, RESOLVE_URL, REVERSE_URL):
                response = self.get(url, q='queen', place_id='place-1', lat='-36.8', lng='174.7')
                self.assertEqual(response.status_code, 404, url)

        request.assert_not_called()


class WorkspaceRequiredTests(GuestFixture):
    """A lookup that names no shop is refused, never charged to a default one."""

    def test_a_request_that_names_no_shop_is_refused(self):
        with mock.patch(PROVIDER) as request:
            # No X-Workspace-ID, and 'testserver' maps to no WorkspaceDomain.
            response = self.client.get(SUGGEST_URL, {'q': '12 queen', 'session': 'tok'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'workspace_required')
        request.assert_not_called()
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0)
        self.assertFalse(AutocompleteSession.all_objects.exists(), 'nothing was opened against anyone')

    def test_the_view_refuses_on_its_own_when_nothing_bound_a_workspace(self):
        """The backstop behind the middleware, which does not run on every path.

        A request carrying an ``X-API-Key`` header is let past the middleware with
        no workspace resolved, on the understanding that the view layer will work
        one out. These views have nothing to work one out from, and with anonymous
        callers allowed in, falling back to a default tenant would let anybody at
        all spend that tenant's allowance.
        """
        factory = APIRequestFactory()
        calls = (
            (views.address_config, factory.get(CONFIG_URL)),
            (views.address_suggest, factory.get(SUGGEST_URL, {'q': '12 queen'})),
            (views.address_resolve, factory.get(RESOLVE_URL, {'place_id': 'place-1'})),
            (views.address_reverse, factory.get(REVERSE_URL, {'lat': '-36.8', 'lng': '174.7'})),
        )

        with mock.patch(PROVIDER) as request:
            for view, bare_request in calls:
                response = view(bare_request)
                self.assertEqual(response.status_code, 400, view.__name__)
                self.assertEqual(response.data['code'], 'workspace_required', view.__name__)

        request.assert_not_called()


class GuestThrottleTests(GuestFixture):
    """How fast a guest may spend, and whose allowance they spend it out of."""

    def test_the_guest_rates_are_the_tighter_pair(self):
        """The whole point of a separate bucket, pinned as a number.

        A change that loosened the guest limits past the signed-in ones would
        leave the endpoints open with nothing left holding the rate down.
        """
        rates = {
            'guest typeahead': views.DEFAULT_GUEST_TYPEAHEAD_RATE,
            'signed-in typeahead': views.DEFAULT_TYPEAHEAD_RATE,
            'guest lookup': views.DEFAULT_GUEST_LOOKUP_RATE,
            'signed-in lookup': views.DEFAULT_LOOKUP_RATE,
        }
        for label, rate in rates.items():
            self.assertTrue(rate.endswith('/min'), f'{label} is {rate}')
        per_minute = {label: int(rate.split('/')[0]) for label, rate in rates.items()}

        self.assertLess(per_minute['guest typeahead'], per_minute['signed-in typeahead'])
        self.assertLess(per_minute['guest lookup'], per_minute['signed-in lookup'])
        self.assertLess(
            per_minute['guest lookup'], per_minute['guest typeahead'],
            'a lookup is a whole address; typing one takes several suggests',
        )

    @override_settings(GEO_GUEST_TYPEAHEAD_RATE='3/min')
    def test_a_guest_who_keeps_typing_is_cut_off(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)) as request:
            allowed = [self.get(SUGGEST_URL, q='12 queen', session='tok').status_code for _ in range(3)]
            refused = self.get(SUGGEST_URL, q='12 queen', session='tok')

        self.assertEqual(allowed, [200, 200, 200])
        self.assertEqual(refused.status_code, 429)
        self.assertEqual(request.call_count, 3, 'the refused request never reached Google')
        self.assertEqual(self.session_count('tok'), 3, 'and was never counted against the bill')

    @override_settings(GEO_GUEST_LOOKUP_RATE='2/min')
    def test_a_guest_picking_address_after_address_is_cut_off(self):
        with mock.patch(PROVIDER, return_value=_ok(GEOCODE)) as request:
            allowed = [self.get(REVERSE_URL, lat='-36.8485', lng='174.7633').status_code for _ in range(2)]
            refused = self.get(REVERSE_URL, lat='-41.2865', lng='174.7762')

        self.assertEqual(allowed, [200, 200])
        self.assertEqual(refused.status_code, 429)
        self.assertEqual(request.call_count, 1, 'the second answer came from the cache')
        self.assertEqual(self.metered(METER_GEOCODE), 2, 'the throttled one was never billed')

    @override_settings(GEO_GUEST_LOOKUP_RATE='1/min')
    def test_running_out_of_lookups_does_not_stop_the_typing(self):
        """Two limits, two buckets: an exhausted one must not take the other down."""
        with mock.patch(PROVIDER, return_value=_ok(GEOCODE)):
            self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')
            self.assertEqual(self.get(REVERSE_URL, lat='-41.2865', lng='174.7762').status_code, 429)

        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            self.assertEqual(self.get(SUGGEST_URL, q='12 queen', session='tok').status_code, 200)

    @override_settings(GEO_GUEST_TYPEAHEAD_RATE='1/min')
    def test_a_signed_in_shopper_is_not_held_to_the_guest_rate(self):
        """The two buckets are separate, and an account is counted in the other one."""
        self.sign_in()

        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            statuses = [self.get(SUGGEST_URL, q='12 queen', session='tok').status_code for _ in range(4)]

        self.assertEqual(statuses, [200, 200, 200, 200])

    @override_settings(GEO_TYPEAHEAD_RATE='2/min')
    def test_a_signed_in_shopper_still_has_a_limit_of_their_own(self):
        self.sign_in()

        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            allowed = [self.get(SUGGEST_URL, q='12 queen', session='tok').status_code for _ in range(2)]
            refused = self.get(SUGGEST_URL, q='12 queen', session='tok')

        self.assertEqual(allowed, [200, 200])
        self.assertEqual(refused.status_code, 429)

    @override_settings(GEO_GUEST_TYPEAHEAD_RATE='1/min')
    def test_one_shops_shoppers_do_not_use_up_anothers_limit(self):
        """One IP address is a carrier NAT or an office; it is not one person.

        Keyed on the address alone, the shoppers of a busy storefront would be
        what a quiet storefront's shopper is refused for — and the two shops pay
        separate bills.
        """
        neighbour = self.make_shop('shop-geo-neighbour')

        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            self.assertEqual(self.get(SUGGEST_URL, q='12 queen', session='a').status_code, 200)
            self.assertEqual(self.get(SUGGEST_URL, q='12 queen', session='a').status_code, 429)
            from_next_door = self.get(SUGGEST_URL, workspace=neighbour, q='12 queen', session='b')

        self.assertEqual(from_next_door.status_code, 200, 'the same address, a different shop')

    def session_count(self, token):
        session = AutocompleteSession.all_objects.filter(workspace=self.workspace, token=token).first()
        return session.request_count if session else 0


class GuestUsageCapTests(GuestFixture):
    """The month's cap is what bounds the bill, and it does not care who is asking."""

    def setUp(self):
        super().setUp()
        WorkspacePlatformProfile.objects.create(
            workspace=self.workspace, monthly_usage_cap_points=Decimal('1')
        )
        with mock.patch(PROVIDER, return_value=_ok(GEOCODE)):
            self.assertEqual(self.get(REVERSE_URL, lat='-36.8485', lng='174.7633').status_code, 200)

    def test_a_guest_is_refused_once_the_month_is_spent(self):
        calls = {
            SUGGEST_URL: {'q': '12 queen', 'session': 'tok'},
            RESOLVE_URL: {'place_id': 'place-1', 'session': 'tok'},
            REVERSE_URL: {'lat': '-41.2865', 'lng': '174.7762'},
        }
        with mock.patch(PROVIDER) as request:
            for url, params in calls.items():
                response = self.get(url, **params)
                self.assertEqual(response.status_code, 402, url)
                self.assertEqual(response.json()['code'], 'usage_cap_reached', url)

        request.assert_not_called()
        self.assertEqual(self.metered(METER_GEOCODE), 1, 'nothing beyond what used the month up')

    def test_signing_in_is_not_a_way_around_the_cap(self):
        self.sign_in()

        with mock.patch(PROVIDER) as request:
            response = self.get(REVERSE_URL, lat='-41.2865', lng='174.7762')

        self.assertEqual(response.status_code, 402)
        request.assert_not_called()


class RateConfigurationTests(SimpleTestCase):
    """Where a deployment says how fast these endpoints may be asked."""

    def test_a_rate_in_the_settings_wins(self):
        with override_settings(GEO_GUEST_TYPEAHEAD_RATE='7/min'):
            self.assertEqual(views._rate('GEO_GUEST_TYPEAHEAD_RATE', '30/min'), '7/min')

    def test_the_environment_answers_when_the_settings_do_not(self):
        with mock.patch.dict(os.environ, {'GEO_GUEST_LOOKUP_RATE': '5/hour'}):
            self.assertEqual(views._rate('GEO_GUEST_LOOKUP_RATE', '10/min'), '5/hour')

    def test_nothing_configured_leaves_the_default(self):
        self.assertEqual(views._rate('GEO_NOBODY_SET_THIS', '30/min'), '30/min')

    def test_a_rate_nobody_can_parse_falls_back_rather_than_failing_every_lookup(self):
        """The rate is parsed inside the request, so a typo would be a 500 a call.

        And it must fall back to the default rather than to no limit: a limit that
        disappears when somebody fat-fingers an environment variable is worse than
        no limit at all, because nothing says it went.
        """
        for bad in ('lots', '30', '30/fortnight', '', '  '):
            with override_settings(GEO_GUEST_TYPEAHEAD_RATE=bad):
                self.assertEqual(views._rate('GEO_GUEST_TYPEAHEAD_RATE', '30/min'), '30/min', bad)
