# -*- coding: utf-8 -*-
"""Address lookup: workspace gating, country restriction, and field mapping.

Every Google call is stubbed. These tests pin our side of the contract — what the
workspace's settings mean, which results we are willing to hand back, and how a
Google address becomes the fields of an address form — not Google's behaviour.
"""

from __future__ import annotations

from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from bfg.common.extensions import services as extension_services
from bfg.common.models import Customer, Settings, User, Workspace, WorkspaceExtension

from apps.geo.services.config import get_address_lookup_config, normalise_country_code
from apps.geo.services.google_maps import (
    GeoProviderError,
    _Component,
    _parse_components,
    resolve,
    reverse,
    suggest,
)

KEY = 'test-google-key'

CONFIG_URL = '/api/v1/geo/address/config/'
SUGGEST_URL = '/api/v1/geo/address/suggest/'
RESOLVE_URL = '/api/v1/geo/address/resolve/'
REVERSE_URL = '/api/v1/geo/address/reverse/'


def places_component(long_text, short_text, *types):
    return {'longText': long_text, 'shortText': short_text, 'types': list(types)}


def geocoding_component(long_name, short_name, *types):
    return {'long_name': long_name, 'short_name': short_name, 'types': list(types)}


class WorkspaceFixture(TestCase):
    """A workspace with the plugin block wired however the test needs it."""

    def setUp(self):
        cache.clear()
        self.workspace = Workspace.objects.create(name='Shop', slug='shop-geo-test')
        # A signal already gave the new workspace a Settings row, so update it rather
        # than creating a second one against the same OneToOne.
        self.settings_row, _ = Settings.objects.get_or_create(workspace=self.workspace)
        self.settings_row.default_language = 'en'
        self.settings_row.country = 'NZ'
        self.settings_row.custom_settings = {}
        self.settings_row.save()
        self.switch_geo(on=True)

    def set_plugin(self, **values):
        self.settings_row.custom_settings = {'plugins': {'address_lookup': values}}
        self.settings_row.save(update_fields=['custom_settings'])
        self.workspace.refresh_from_db()
        return self.workspace

    def switch_geo(self, *, on):
        """The geo extension, switched per workspace on top of the plugin block."""
        WorkspaceExtension.all_objects.update_or_create(
            workspace=self.workspace,
            key='geo',
            defaults={'status': WorkspaceExtension.STATUS_ACTIVE if on else WorkspaceExtension.STATUS_INACTIVE},
        )
        extension_services.invalidate(self.workspace.pk)


@override_settings(GOOGLE_MAPS_API_KEY=KEY, IS_PROD=False)
class ExtensionSwitchTests(WorkspaceFixture):
    def test_the_feature_is_off_while_the_workspace_has_the_extension_off(self):
        workspace = self.set_plugin(enabled=True)
        self.assertTrue(get_address_lookup_config(workspace).usable)

        self.switch_geo(on=False)
        self.assertFalse(get_address_lookup_config(workspace).usable)

        shopper = User.objects.create_user(username='shopper', email='s@example.com', password='pw')
        Customer.all_objects.create(workspace=self.workspace, user=shopper)
        self.client.force_login(shopper)
        on_workspace = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}
        self.assertFalse(self.client.get(CONFIG_URL, **on_workspace).json()['enabled'])
        self.assertEqual(self.client.get(SUGGEST_URL, {'q': 'queen'}, **on_workspace).status_code, 404)

        # Switching it back on restores the settings the workspace already had.
        self.switch_geo(on=True)
        self.assertTrue(get_address_lookup_config(workspace).usable)


@override_settings(GOOGLE_MAPS_API_KEY=KEY)
class ConfigResolutionTests(WorkspaceFixture):
    def test_off_until_an_operator_turns_it_on(self):
        config = get_address_lookup_config(self.workspace)
        self.assertFalse(config.enabled)
        self.assertFalse(config.usable)

    def test_country_falls_back_to_the_workspace_market(self):
        config = get_address_lookup_config(self.set_plugin(enabled=True))
        self.assertEqual(config.country_code, 'NZ')
        self.assertTrue(config.usable)

    def test_plugin_country_overrides_the_workspace_market(self):
        config = get_address_lookup_config(self.set_plugin(enabled=True, country_code='cn'))
        self.assertEqual(config.country_code, 'CN')

    def test_a_country_code_that_is_not_alpha2_is_ignored(self):
        config = get_address_lookup_config(self.set_plugin(enabled=True, country_code='NZL'))
        self.assertEqual(config.country_code, 'NZ', 'falls back rather than passing NZL to Google')

    def test_language_falls_back_to_the_workspace_default(self):
        self.settings_row.default_language = 'zh-hans'
        self.settings_row.save(update_fields=['default_language'])
        config = get_address_lookup_config(self.set_plugin(enabled=True))
        self.assertEqual(config.language, 'zh-hans')

    def test_enabled_without_a_server_key_is_configured_but_not_usable(self):
        with override_settings(GOOGLE_MAPS_API_KEY=''):
            config = get_address_lookup_config(self.set_plugin(enabled=True))
        self.assertTrue(config.enabled)
        self.assertFalse(config.usable)

    def test_no_workspace_resolves_without_raising(self):
        config = get_address_lookup_config(None)
        self.assertFalse(config.usable)

    def test_normalise_country_code(self):
        self.assertEqual(normalise_country_code(' nz '), 'NZ')
        for bad in (None, '', 'N', 'NZL', '12', 'N1'):
            self.assertEqual(normalise_country_code(bad), '', bad)


class ParseComponentsTests(TestCase):
    def test_suburb_is_a_district_not_a_city(self):
        parts = _parse_components([
            _Component('12', '12', ('street_number',)),
            _Component('Queen Street', 'Queen St', ('route',)),
            _Component('Grey Lynn', 'Grey Lynn', ('sublocality', 'sublocality_level_1')),
            _Component('Auckland', 'Auckland', ('locality',)),
            _Component('Auckland', 'AUK', ('administrative_area_level_1',)),
            _Component('1021', '1021', ('postal_code',)),
            _Component('New Zealand', 'NZ', ('country',)),
        ])
        self.assertEqual(parts['address_line1'], '12 Queen Street')
        self.assertEqual(parts['district'], 'Grey Lynn')
        self.assertEqual(parts['city'], 'Auckland')
        self.assertEqual(parts['state'], 'AUK')
        self.assertEqual(parts['postal_code'], '1021')
        self.assertEqual(parts['country'], 'NZ')

    def test_unit_number_leads_the_street_line(self):
        parts = _parse_components([
            _Component('3', '3', ('subpremise',)),
            _Component('12', '12', ('street_number',)),
            _Component('Queen Street', 'Queen St', ('route',)),
        ])
        self.assertEqual(parts['address_line1'], '3/12 Queen Street')

    def test_district_is_promoted_when_there_is_no_locality(self):
        parts = _parse_components([
            _Component('Piha', 'Piha', ('neighborhood',)),
            _Component('New Zealand', 'NZ', ('country',)),
        ])
        self.assertEqual(parts['city'], 'Piha')
        self.assertEqual(parts['district'], '')

    def test_empty_components_give_empty_fields_not_an_error(self):
        parts = _parse_components([])
        self.assertEqual(parts['address_line1'], '')
        self.assertEqual(parts['country'], '')


@override_settings(GOOGLE_MAPS_API_KEY=KEY)
class SuggestTests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        self.config = get_address_lookup_config(self.set_plugin(enabled=True))

    def test_restricts_to_the_workspace_country_and_maps_predictions(self):
        payload = {'suggestions': [
            {'placePrediction': {
                'placeId': 'place-1',
                'text': {'text': '12 Queen Street, Auckland'},
                'structuredFormat': {
                    'mainText': {'text': '12 Queen Street'},
                    'secondaryText': {'text': 'Auckland, New Zealand'},
                },
            }},
            {'placePrediction': {'placeId': '', 'text': {'text': 'no id'}}},
        ]}
        with mock.patch(
            'apps.geo.services.google_maps.requests.request', return_value=_ok(payload)
        ) as request:
            results = suggest('12 queen', self.config, session_token='tok')

        sent = request.call_args.kwargs['json']
        self.assertEqual(sent['includedRegionCodes'], ['nz'], 'Google wants CLDR lower-case')
        self.assertEqual(sent['sessionToken'], 'tok')
        self.assertEqual(request.call_args.kwargs['headers']['X-Goog-Api-Key'], KEY)

        self.assertEqual(len(results), 1, 'a prediction with no place id is unusable')
        self.assertEqual(results[0].place_id, 'place-1')
        self.assertEqual(results[0].main_text, '12 Queen Street')

    def test_caps_the_list(self):
        payload = {'suggestions': [
            {'placePrediction': {'placeId': f'p{i}', 'text': {'text': str(i)}}} for i in range(50)
        ]}
        with mock.patch('apps.geo.services.google_maps.requests.request', return_value=_ok(payload)):
            self.assertEqual(len(suggest('queen', self.config)), 8)

    def test_a_timeout_surfaces_as_a_retryable_provider_error(self):
        import requests as requests_lib

        with mock.patch(
            'apps.geo.services.google_maps.requests.request', side_effect=requests_lib.Timeout('slow')
        ):
            with self.assertRaises(GeoProviderError) as caught:
                suggest('queen', self.config)
        self.assertEqual(caught.exception.code, 'provider_timeout')

    def test_googles_error_body_never_escapes(self):
        with mock.patch(
            'apps.geo.services.google_maps.requests.request',
            return_value=_response(403, {'error': {'message': f'key {KEY} is not authorized'}}),
        ):
            with self.assertRaises(GeoProviderError) as caught:
                suggest('queen', self.config)
        self.assertNotIn(KEY, str(caught.exception))


@override_settings(GOOGLE_MAPS_API_KEY=KEY)
class ResolveTests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        self.config = get_address_lookup_config(self.set_plugin(enabled=True))

    def _payload(self, country_short='NZ'):
        return {
            'id': 'place-1',
            'formattedAddress': '12 Queen Street, Auckland 1010, New Zealand',
            'displayName': {'text': 'Queen Street Store'},
            'location': {'latitude': -36.8485, 'longitude': 174.7633},
            'addressComponents': [
                places_component('12', '12', 'street_number'),
                places_component('Queen Street', 'Queen St', 'route'),
                places_component('Auckland', 'Auckland', 'locality'),
                places_component('1010', '1010', 'postal_code'),
                places_component('New Zealand', country_short, 'country'),
            ],
        }

    def test_fills_the_form_fields(self):
        with mock.patch(
            'apps.geo.services.google_maps.requests.request', return_value=_ok(self._payload())
        ) as request:
            resolved = resolve('place-1', self.config, session_token='tok')

        self.assertEqual(resolved.address_line1, '12 Queen Street')
        self.assertEqual(resolved.city, 'Auckland')
        self.assertEqual(resolved.country, 'NZ')
        self.assertEqual(resolved.display_name, 'Queen Street Store')
        self.assertAlmostEqual(resolved.latitude, -36.8485)
        self.assertIn('addressComponents', request.call_args.kwargs['headers']['X-Goog-FieldMask'])

    def test_a_place_outside_the_country_is_refused(self):
        with mock.patch(
            'apps.geo.services.google_maps.requests.request', return_value=_ok(self._payload('AU'))
        ):
            self.assertIsNone(resolve('place-1', self.config))

    def test_a_second_lookup_is_served_from_cache(self):
        with mock.patch(
            'apps.geo.services.google_maps.requests.request', return_value=_ok(self._payload())
        ) as request:
            resolve('place-1', self.config)
            resolve('place-1', self.config)
        self.assertEqual(request.call_count, 1)


@override_settings(GOOGLE_MAPS_API_KEY=KEY)
class ReverseTests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        self.config = get_address_lookup_config(self.set_plugin(enabled=True))

    def _result(self, street, country_short, place_id='p'):
        return {
            'place_id': place_id,
            'formatted_address': f'{street}, Auckland, New Zealand',
            'geometry': {'location': {'lat': -36.8485, 'lng': 174.7633}},
            'address_components': [
                geocoding_component(street.split(' ')[0], street.split(' ')[0], 'street_number'),
                geocoding_component(' '.join(street.split(' ')[1:]), 'St', 'route'),
                geocoding_component('Auckland', 'Auckland', 'locality'),
                geocoding_component('New Zealand', country_short, 'country'),
            ],
        }

    def test_takes_the_most_specific_in_country_result(self):
        payload = {'status': 'OK', 'results': [
            self._result('12 Queen Street', 'NZ', 'exact'),
            self._result('Queen Street', 'NZ', 'street'),
        ]}
        with mock.patch('apps.geo.services.google_maps.requests.request', return_value=_ok(payload)):
            resolved = reverse(-36.8485, 174.7633, self.config)

        self.assertEqual(resolved.place_id, 'exact')
        self.assertEqual(resolved.display_name, '12 Queen Street')
        self.assertEqual(resolved.country, 'NZ')

    def test_skips_out_of_country_results_to_reach_an_in_country_one(self):
        payload = {'status': 'OK', 'results': [
            self._result('1 Bondi Road', 'AU', 'aussie'),
            self._result('12 Queen Street', 'NZ', 'kiwi'),
        ]}
        with mock.patch('apps.geo.services.google_maps.requests.request', return_value=_ok(payload)):
            resolved = reverse(-36.8485, 174.7633, self.config)
        self.assertEqual(resolved.place_id, 'kiwi')

    def test_a_fix_entirely_outside_the_country_yields_nothing(self):
        payload = {'status': 'OK', 'results': [self._result('1 Bondi Road', 'AU')]}
        with mock.patch('apps.geo.services.google_maps.requests.request', return_value=_ok(payload)):
            self.assertIsNone(reverse(-33.89, 151.27, self.config))

    def test_zero_results_is_not_an_error(self):
        with mock.patch(
            'apps.geo.services.google_maps.requests.request',
            return_value=_ok({'status': 'ZERO_RESULTS', 'results': []}),
        ):
            self.assertIsNone(reverse(-36.8485, 174.7633, self.config))

    def test_nearby_fixes_share_one_cached_lookup(self):
        payload = {'status': 'OK', 'results': [self._result('12 Queen Street', 'NZ')]}
        with mock.patch(
            'apps.geo.services.google_maps.requests.request', return_value=_ok(payload)
        ) as request:
            reverse(-36.84850001, 174.76330001, self.config)
            reverse(-36.84850002, 174.76330002, self.config)
        self.assertEqual(request.call_count, 1, 'GPS jitter must not become a second bill')


@override_settings(GOOGLE_MAPS_API_KEY=KEY, IS_PROD=False)
class EndpointTests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='shopper', email='s@example.com', password='pw')
        Customer.all_objects.create(workspace=self.workspace, user=self.user)
        self.client.force_login(self.user)

    def get(self, url, **params):
        return self.client.get(url, params, HTTP_X_WORKSPACE_ID=str(self.workspace.pk))

    def test_a_caller_who_is_not_signed_in_is_served_too(self):
        """Checkout is where addresses get typed, and it happens before sign-up.

        What a guest may do, how hard they are throttled for it and what happens
        once the shop's month is spent are pinned in ``test_guest_access``.
        """
        self.client.logout()
        self.assertEqual(self.get(CONFIG_URL).status_code, 200)

    def test_config_reports_off_and_never_carries_the_key(self):
        response = self.get(CONFIG_URL)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['enabled'])
        self.assertNotIn(KEY, response.content.decode())

    def test_lookups_404_while_the_workspace_has_it_switched_off(self):
        for url in (SUGGEST_URL, RESOLVE_URL, REVERSE_URL):
            self.assertEqual(self.get(url, q='queen', place_id='p', lat='-36.8', lng='174.7').status_code, 404, url)

    def test_config_reports_on_once_enabled(self):
        self.set_plugin(enabled=True)
        body = self.get(CONFIG_URL).json()
        self.assertTrue(body['enabled'])
        self.assertEqual(body['country_code'], 'NZ')

    def test_a_query_too_short_to_search_returns_an_empty_list(self):
        self.set_plugin(enabled=True)
        with mock.patch('apps.geo.services.google_maps.requests.request') as request:
            response = self.get(SUGGEST_URL, q='q')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])
        request.assert_not_called()

    def test_reverse_rejects_coordinates_that_are_not_coordinates(self):
        self.set_plugin(enabled=True)
        for lat, lng in (('', ''), ('abc', '174.7'), ('-36.8', '999'), ('nan', '174.7'), ('inf', '174.7')):
            response = self.get(REVERSE_URL, lat=lat, lng=lng)
            self.assertEqual(response.status_code, 400, f'{lat},{lng}')

    def test_reverse_returns_the_address(self):
        self.set_plugin(enabled=True)
        payload = {'status': 'OK', 'results': [{
            'place_id': 'p1',
            'formatted_address': '12 Queen Street, Auckland 1010, New Zealand',
            'geometry': {'location': {'lat': -36.8485, 'lng': 174.7633}},
            'address_components': [
                geocoding_component('12', '12', 'street_number'),
                geocoding_component('Queen Street', 'Queen St', 'route'),
                geocoding_component('Auckland', 'Auckland', 'locality'),
                geocoding_component('New Zealand', 'NZ', 'country'),
            ],
        }]}
        with mock.patch('apps.geo.services.google_maps.requests.request', return_value=_ok(payload)):
            response = self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['address_line1'], '12 Queen Street')
        self.assertEqual(body['display_name'], '12 Queen Street')
        self.assertEqual(body['country'], 'NZ')

    def test_resolve_requires_a_place_id(self):
        self.set_plugin(enabled=True)
        self.assertEqual(self.get(RESOLVE_URL).status_code, 400)

    def test_an_unreachable_provider_is_a_503(self):
        import requests as requests_lib

        self.set_plugin(enabled=True)
        with mock.patch(
            'apps.geo.services.google_maps.requests.request',
            side_effect=requests_lib.ConnectionError('down'),
        ):
            response = self.get(REVERSE_URL, lat='-36.8485', lng='174.7633')
        self.assertEqual(response.status_code, 503)


def _ok(payload):
    return _response(200, payload)


def _response(status_code, payload):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response
