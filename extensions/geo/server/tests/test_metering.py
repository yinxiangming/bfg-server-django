# -*- coding: utf-8 -*-
"""What a workspace is charged for address lookup, and when it is refused.

Google is stubbed throughout, as in ``test_address_lookup``. What is pinned here
is the accounting either side of that stub: an autocomplete request is not billed
while its session might still end in a chosen address, a finished session costs
one place details call and nothing more, an abandoned one costs its requests, and
a workspace that has spent its month is refused before any of it is spent.

Prices are created per test class because the platform refuses to record usage for
a meter nobody has priced. One point per call, with no margin, so the arithmetic
in the assertions is the arithmetic of the bill.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from bfg.common.extensions import services as extension_services
from bfg.common.models import Customer, Settings, User, Workspace, WorkspaceExtension
from bfg.platform import metering
from bfg.platform.models import MeterPrice, UsageRecord, WorkspacePlatformProfile
from bfg.platform.services import usage

from apps.geo.extension import METER_AUTOCOMPLETE, METER_GEOCODE, METER_PLACE_DETAILS
from apps.geo.models import AutocompleteSession
from apps.geo.services import billing

KEY = 'test-google-key'

SUGGEST_URL = '/api/v1/geo/address/suggest/'
RESOLVE_URL = '/api/v1/geo/address/resolve/'
REVERSE_URL = '/api/v1/geo/address/reverse/'

# Where the provider is patched. Nothing below this line is allowed to reach
# Google, so every test that expects no spend asserts on this mock.
PROVIDER = 'apps.geo.services.google_maps.requests.request'


def _response(status_code, payload):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _ok(payload):
    return _response(200, payload)


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
        {'longText': '1010', 'shortText': '1010', 'types': ['postal_code']},
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


@override_settings(GOOGLE_MAPS_API_KEY=KEY, IS_PROD=False)
class MeteredLookupFixture(TestCase):
    """A signed-in shopper of a workspace with address lookup on and priced."""

    def setUp(self):
        cache.clear()
        self.workspace = Workspace.objects.create(name='Shop', slug='shop-geo-metering')
        settings_row, _ = Settings.objects.get_or_create(workspace=self.workspace)
        settings_row.default_language = 'en'
        settings_row.country = 'NZ'
        settings_row.custom_settings = {'plugins': {'address_lookup': {'enabled': True}}}
        settings_row.save()

        WorkspaceExtension.all_objects.update_or_create(
            workspace=self.workspace,
            key='geo',
            defaults={'status': WorkspaceExtension.STATUS_ACTIVE},
        )
        extension_services.invalidate(self.workspace.pk)

        for meter in (METER_AUTOCOMPLETE, METER_PLACE_DETAILS, METER_GEOCODE):
            MeterPrice.objects.create(
                meter=meter,
                vendor_cost=Decimal('1'),
                unit_size=1,
                margin=Decimal('0'),
                effective_from=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
            )

        self.user = User.objects.create_user(username='shopper', email='s@example.com', password='pw')
        Customer.all_objects.create(workspace=self.workspace, user=self.user)
        self.client.force_login(self.user)

    def get(self, url, **params):
        return self.client.get(url, params, HTTP_X_WORKSPACE_ID=str(self.workspace.pk))

    def metered(self, meter):
        """Quantity of ``meter`` recorded against this workspace so far."""
        rows = UsageRecord.all_objects.filter(workspace=self.workspace, meter=meter)
        return sum((row.quantity for row in rows), Decimal('0'))

    def session(self, token):
        return AutocompleteSession.all_objects.filter(workspace=self.workspace, token=token).first()

    def age_session(self, token, *, minutes):
        """Backdate a session so it looks like nobody has touched it for ``minutes``."""
        AutocompleteSession.all_objects.filter(workspace=self.workspace, token=token).update(
            last_request_at=timezone.now() - timedelta(minutes=minutes)
        )


class SessionPricingTests(MeteredLookupFixture):
    """Google bills a session, so the requests inside one are counted, not metered."""

    def test_typing_is_counted_rather_than_billed(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            for _ in range(3):
                self.assertEqual(self.get(SUGGEST_URL, q='12 queen', session='tok').status_code, 200)

        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0, 'the session might still end in an address')
        self.assertEqual(self.session('tok').request_count, 3)

    def test_choosing_an_address_costs_one_place_details_and_frees_the_typing(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            for _ in range(3):
                self.get(SUGGEST_URL, q='12 queen', session='tok')

        with mock.patch(PROVIDER, return_value=_ok(PLACE_DETAILS)):
            response = self.get(RESOLVE_URL, place_id='place-1', session='tok')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.metered(METER_PLACE_DETAILS), 1)
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0, 'the session ended in an address')
        self.assertIsNone(self.session('tok'), 'nothing is owed, so there is nothing left to remember')

    def test_a_settled_session_is_never_billed_afterwards(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            self.get(SUGGEST_URL, q='12 queen', session='tok')
        with mock.patch(PROVIDER, return_value=_ok(PLACE_DETAILS)):
            self.get(RESOLVE_URL, place_id='place-1', session='tok')

        # A whole day later, with the sweep running on every request since.
        billing.settle_abandoned(self.workspace, now=timezone.now() + timedelta(days=1))

        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0)

    def test_an_abandoned_session_is_billed_per_request_on_the_next_one(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            for _ in range(4):
                self.get(SUGGEST_URL, q='12 queen', session='walked-away')
        self.age_session('walked-away', minutes=31)

        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            self.get(SUGGEST_URL, q='19 vulcan', session='next-shopper')

        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 4, 'one charge per request of the lost session')
        self.assertIsNone(self.session('walked-away'))
        self.assertEqual(self.session('next-shopper').request_count, 1, 'the new session is untouched')

    def test_a_session_still_being_typed_into_is_left_alone(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            self.get(SUGGEST_URL, q='12 queen', session='thinking')
        self.age_session('thinking', minutes=29)

        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            self.get(SUGGEST_URL, q='19 vulcan', session='someone-else')

        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0)
        self.assertIsNotNone(self.session('thinking'), 'a pause is not an abandonment')

    def test_typing_without_a_session_token_is_billed_as_it_happens(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            self.assertEqual(self.get(SUGGEST_URL, q='12 queen').status_code, 200)

        # No token means no session pricing at Google either, so there is nothing
        # this request could later turn out to be free of.
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 1)
        self.assertFalse(AutocompleteSession.all_objects.filter(workspace=self.workspace).exists())

    def test_a_query_too_short_to_search_costs_nothing(self):
        with mock.patch(PROVIDER) as request:
            self.assertEqual(self.get(SUGGEST_URL, q='q', session='tok').status_code, 200)

        request.assert_not_called()
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0)
        self.assertIsNone(self.session('tok'))

    def test_a_provider_failure_is_not_billed_or_counted(self):
        import requests as requests_lib

        with mock.patch(PROVIDER, side_effect=requests_lib.Timeout('slow')):
            self.assertEqual(self.get(SUGGEST_URL, q='12 queen', session='tok').status_code, 503)

        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0)
        self.assertIsNone(self.session('tok'), 'nothing happened at Google, so nothing is owed')

    def test_settling_the_same_session_twice_bills_it_once(self):
        with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
            for _ in range(2):
                self.get(SUGGEST_URL, q='12 queen', session='walked-away')
        self.age_session('walked-away', minutes=31)

        self.assertEqual(billing.settle_abandoned(self.workspace), 2)
        self.assertEqual(billing.settle_abandoned(self.workspace), 0)
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 2)

    def test_a_session_typed_into_mid_sweep_is_not_billed_as_abandoned(self):
        """The shopper who comes back between the sweep's select and its delete.

        Without the cutoff repeated on the delete, that session is billed per
        request here *and* charged as place details when the shopper finishes
        picking an address — one Google session paid for twice — and the keystroke
        that revived it is lost along with the row.
        """
        stale = timezone.now() - timedelta(minutes=31)
        AutocompleteSession.all_objects.create(
            workspace=self.workspace, token='came-back', request_count=2,
            started_at=stale, last_request_at=stale,
        )
        real_stale_sessions = billing._stale_sessions

        def types_one_more(workspace, cutoff):
            rows = real_stale_sessions(workspace, cutoff)
            # The sweep has chosen its rows; the shopper picks the form back up
            # before it gets round to deleting them.
            billing.note_autocomplete(workspace, 'came-back')
            return rows

        with mock.patch.object(billing, '_stale_sessions', types_one_more):
            self.assertEqual(billing.settle_abandoned(self.workspace), 0)

        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0, 'the session is alive, not abandoned')
        session = self.session('came-back')
        self.assertIsNotNone(session, 'and it is still there to be finished')
        self.assertEqual(session.request_count, 3, 'with the keystroke that revived it counted')

    def test_a_session_revived_mid_sweep_still_ends_in_one_place_details(self):
        """The other half of that race, carried through to the bill.

        The session the sweep let go is an ordinary open session again, so
        finishing it costs the one details call and forgives all of its typing —
        including the keystroke that saved it.
        """
        stale = timezone.now() - timedelta(minutes=31)
        AutocompleteSession.all_objects.create(
            workspace=self.workspace, token='came-back', request_count=2,
            started_at=stale, last_request_at=stale,
        )
        real_stale_sessions = billing._stale_sessions

        def types_one_more(workspace, cutoff):
            rows = real_stale_sessions(workspace, cutoff)
            billing.note_autocomplete(workspace, 'came-back')
            return rows

        with mock.patch.object(billing, '_stale_sessions', types_one_more):
            billing.settle_abandoned(self.workspace)

        with mock.patch(PROVIDER, return_value=_ok(PLACE_DETAILS)):
            self.get(RESOLVE_URL, place_id='place-1', session='came-back')

        self.assertEqual(self.metered(METER_PLACE_DETAILS), 1)
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0)
        self.assertIsNone(self.session('came-back'))

    def test_a_settlement_failure_does_not_fail_the_lookup(self):
        with mock.patch.object(billing, '_stale_sessions', side_effect=RuntimeError('lock wait timeout')):
            with mock.patch(PROVIDER, return_value=_ok(SUGGESTIONS)):
                response = self.get(SUGGEST_URL, q='12 queen', session='tok')

        self.assertEqual(response.status_code, 200, "bookkeeping is not the shopper's problem")
        self.assertEqual(self.session('tok').request_count, 1)

    def test_a_session_lookup_never_comes_from_the_cache(self):
        """A cached details call would leave the session unfinished at Google.

        Google would then price that session as abandoned — every autocomplete
        request charged for — while we billed one place details and forgave the
        typing. So a lookup carrying a session token always goes to Google, even
        where a token-less one for the same place would be served from the cache.
        """
        with mock.patch(PROVIDER, return_value=_ok(PLACE_DETAILS)) as request:
            self.get(RESOLVE_URL, place_id='place-1', session='first')
            self.get(RESOLVE_URL, place_id='place-1', session='second')

        self.assertEqual(request.call_count, 2, 'each session has to be ended at Google itself')
        self.assertEqual(
            [call.kwargs['params']['sessionToken'] for call in request.call_args_list],
            ['first', 'second'],
        )
        self.assertEqual(self.metered(METER_PLACE_DETAILS), 2)

    def test_settling_works_through_a_backlog_a_batch_at_a_time(self):
        stale = timezone.now() - timedelta(minutes=31)
        AutocompleteSession.all_objects.bulk_create([
            AutocompleteSession(
                workspace=self.workspace, token=f'tok-{i}', request_count=1,
                started_at=stale, last_request_at=stale,
            )
            for i in range(billing.SETTLE_BATCH + 5)
        ])

        self.assertEqual(billing.settle_abandoned(self.workspace), billing.SETTLE_BATCH)
        self.assertEqual(
            AutocompleteSession.all_objects.filter(workspace=self.workspace).count(), 5,
            'one request settles a batch rather than the whole backlog',
        )
        self.assertEqual(billing.settle_abandoned(self.workspace), 5)

    def test_one_workspace_never_settles_another_ones_sessions(self):
        neighbour = Workspace.objects.create(name='Next door', slug='shop-geo-neighbour')
        stale = timezone.now() - timedelta(minutes=31)
        AutocompleteSession.all_objects.create(
            workspace=neighbour, token='tok', request_count=7, started_at=stale, last_request_at=stale,
        )

        self.assertEqual(billing.settle_abandoned(self.workspace), 0)
        self.assertEqual(usage.points_used(neighbour), 0)
        self.assertIsNotNone(AutocompleteSession.all_objects.filter(workspace=neighbour, token='tok').first())


class GeocodeTests(MeteredLookupFixture):
    def test_a_reverse_lookup_is_billed_once(self):
        with mock.patch(PROVIDER, return_value=_ok(GEOCODE)):
            response = self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.metered(METER_GEOCODE), 1)
        self.assertEqual(usage.points_used(self.workspace), Decimal('1'))

    def test_a_cached_lookup_costs_the_workspace_the_same(self):
        """The cache saves the operator money at Google, not the workspace points.

        Billing only the lookups that miss the cache would make a workspace's bill
        depend on what *other* workspaces happened to look up recently — the cache
        is keyed on place and language, not on tenant — so it could neither be
        predicted nor explained. What a workspace buys is the answer.
        """
        with mock.patch(PROVIDER, return_value=_ok(GEOCODE)) as request:
            self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')
            self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')

        self.assertEqual(request.call_count, 1, 'the second answer came from the cache')
        self.assertEqual(self.metered(METER_GEOCODE), 2)

    def test_a_failed_reverse_lookup_is_not_billed(self):
        import requests as requests_lib

        with mock.patch(PROVIDER, side_effect=requests_lib.ConnectionError('down')):
            self.assertEqual(self.get(REVERSE_URL, lat='-36.8485', lng='174.7633').status_code, 503)

        self.assertEqual(self.metered(METER_GEOCODE), 0)


class UsageCapTests(MeteredLookupFixture):
    """A workspace that has spent its month is refused before anything is spent."""

    def setUp(self):
        super().setUp()
        WorkspacePlatformProfile.objects.create(
            workspace=self.workspace, monthly_usage_cap_points=Decimal('2')
        )
        metering.meter(self.workspace, METER_GEOCODE, 2)
        self.assertEqual(usage.points_used(self.workspace), Decimal('2'), 'the month is spent')

    def test_every_lookup_is_refused_without_reaching_the_provider(self):
        calls = {
            SUGGEST_URL: {'q': '12 queen', 'session': 'tok'},
            RESOLVE_URL: {'place_id': 'place-1', 'session': 'tok'},
            REVERSE_URL: {'lat': '-36.8485', 'lng': '174.7633'},
        }
        with mock.patch(PROVIDER) as request:
            for url, params in calls.items():
                response = self.get(url, **params)
                self.assertEqual(response.status_code, 402, url)
                self.assertEqual(response.json()['code'], 'usage_cap_reached', url)

        request.assert_not_called()
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 0)
        self.assertEqual(self.metered(METER_PLACE_DETAILS), 0)
        self.assertEqual(self.metered(METER_GEOCODE), 2, 'nothing beyond the usage that used the month up')

    def test_a_refused_lookup_opens_no_session(self):
        with mock.patch(PROVIDER):
            self.get(SUGGEST_URL, q='12 queen', session='tok')

        self.assertIsNone(self.session('tok'))

    def test_what_is_owed_is_settled_before_the_cap_is_read(self):
        """An abandoned session counts against the cap, not after it."""
        stale = timezone.now() - timedelta(minutes=31)
        AutocompleteSession.all_objects.create(
            workspace=self.workspace, token='walked-away', request_count=3,
            started_at=stale, last_request_at=stale,
        )
        # Room for one call, and three unbilled requests waiting to be settled.
        WorkspacePlatformProfile.objects.filter(workspace=self.workspace).update(
            monthly_usage_cap_points=Decimal('3')
        )

        with mock.patch(PROVIDER) as request:
            response = self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')

        request.assert_not_called()
        self.assertEqual(response.status_code, 402)
        self.assertEqual(self.metered(METER_AUTOCOMPLETE), 3, 'settled on the way past')

    def test_the_lookup_resumes_once_the_cap_is_raised(self):
        WorkspacePlatformProfile.objects.filter(workspace=self.workspace).update(
            monthly_usage_cap_points=Decimal('50')
        )

        with mock.patch(PROVIDER, return_value=_ok(GEOCODE)):
            response = self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')

        self.assertEqual(response.status_code, 200)


class ManifestTests(TestCase):
    def test_the_meters_belong_to_this_extension(self):
        """The gate is by name: a meter the manifest does not declare is not gated.

        ``metering.allowed`` finds the owning extension by matching the meter name
        against every manifest's ``meters``. A name that appears in one place and
        not the other stops being refused when the workspace switches address
        lookup off, which is the failure this pins down.
        """
        for meter in (METER_AUTOCOMPLETE, METER_PLACE_DETAILS, METER_GEOCODE):
            self.assertEqual(metering.extension_for_meter(meter), 'geo', meter)
