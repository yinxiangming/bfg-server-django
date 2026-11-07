"""Staff market overrides keep public scope, activation and billing controls."""

from dataclasses import replace
from unittest import mock

from django.test import override_settings
from rest_framework.response import Response

from bfg.common.models import StaffMember, StaffRole, User, Workspace
from apps.geo.services.config import get_address_lookup_config
from apps.geo.services.google_maps import ResolvedAddress, resolve, reverse
from . import test_address_lookup as fixtures
from .test_address_lookup import (
    KEY, CONFIG_URL, SUGGEST_URL, RESOLVE_URL, REVERSE_URL, WorkspaceFixture,
    _ok,
)


@override_settings(GOOGLE_MAPS_API_KEY=KEY, IS_PROD=False)
class CountryOverrideTests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        self.set_plugin(enabled=True)
        self.user = User.objects.create_user(username='lookup-staff', password='test-password')
        self.role = StaffRole.objects.create(workspace=self.workspace, name='Operator', code='lookup-operator')
        self.membership = StaffMember.all_objects.create(workspace=self.workspace, user=self.user, role=self.role)
        self.client.force_login(self.user)

    def get(self, url=SUGGEST_URL, **values):
        return self.client.get(url, {'q': '12 street', 'country_code': 'AU', **values},
                               HTTP_X_WORKSPACE_ID=str(self.workspace.pk))

    def test_staff_country_reaches_provider_without_changing_settings(self):
        with mock.patch('apps.geo.views.suggest', return_value=[]) as provider:
            response = self.get(country_code='au')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.call_args.args[1].country_code, 'AU')
        self.assertEqual(get_address_lookup_config(self.workspace).country_code, 'NZ')
        self.assertEqual(self.get(CONFIG_URL).json()['country_code'], 'NZ')

    def test_matching_country_and_omitted_country_retain_public_behavior(self):
        self.client.logout()
        with mock.patch('apps.geo.views.suggest', return_value=[]) as provider:
            self.assertEqual(self.get(country_code='NZ').status_code, 200)
            self.assertEqual(self.client.get(SUGGEST_URL, {'q': '12 street'},
                HTTP_X_WORKSPACE_ID=str(self.workspace.pk)).status_code, 200)
        self.assertEqual(provider.call_count, 2)
        self.assertTrue(all(call.args[1].country_code == 'NZ' for call in provider.call_args_list))

    def test_anonymous_and_non_staff_cannot_expand_the_market(self):
        self.client.logout()
        with mock.patch('apps.geo.views.suggest') as provider:
            self.assertEqual(self.get().status_code, 403)
        provider.assert_not_called()
        user = User.objects.create_user(username='lookup-customer', password='test-password')
        self.client.force_login(user)
        with mock.patch('apps.geo.views.suggest') as provider:
            self.assertEqual(self.get().status_code, 403)
        provider.assert_not_called()

    def test_membership_in_another_workspace_is_insufficient(self):
        self.membership.is_active = False
        self.membership.save()
        other = Workspace.objects.create(name='Other workspace', slug='lookup-other')
        role = StaffRole.objects.create(workspace=other, name='Other operator', code='lookup-other')
        StaffMember.all_objects.create(workspace=other, user=self.user, role=role)
        with mock.patch('apps.geo.views.suggest') as provider:
            self.assertEqual(self.get().status_code, 403)
        provider.assert_not_called()

    def test_inactive_or_mismatched_roles_do_not_authorize_overrides(self):
        self.role.is_active = False
        self.role.save()
        self.assertEqual(self.get().status_code, 403)
        other = Workspace.objects.create(name='Other role owner', slug='lookup-other-role')
        role = StaffRole.objects.create(workspace=other, name='Wrong role', code='lookup-wrong-role')
        self.membership.role = role
        self.membership.save()
        self.assertEqual(self.get().status_code, 403)

    def test_invalid_country_is_rejected_before_provider_calls(self):
        with mock.patch('apps.geo.views.suggest') as provider:
            for value in ['', 'N', 'NZZ', '12', 'N<script>']:
                with self.subTest(value=value):
                    self.assertEqual(self.get(country_code=value).status_code, 400)
        provider.assert_not_called()

    def test_disabled_lookup_cannot_be_reenabled_by_a_country_parameter(self):
        self.switch_geo(on=False)
        with mock.patch('apps.geo.views.suggest') as provider:
            self.assertEqual(self.get().status_code, 404)
        provider.assert_not_called()

    def test_override_still_obeys_usage_caps(self):
        refusal = Response({'code': 'usage_cap_reached'}, status=402)
        with mock.patch('apps.geo.views._budget_refusal', return_value=refusal) as budget:
            with mock.patch('apps.geo.views.suggest') as provider:
                self.assertEqual(self.get().status_code, 402)
        budget.assert_called_once()
        provider.assert_not_called()

    def test_resolve_and_reverse_receive_the_same_authorized_context(self):
        address = ResolvedAddress(
            place_id='synthetic', display_name='Street', formatted_address='Street, Sydney',
            address_line1='12 Street', address_line2='', district='', city='Sydney', state='NSW',
            postal_code='2000', country='AU', latitude=-33.8, longitude=151.2,
        )
        with mock.patch('apps.geo.views.resolve', return_value=address) as provider:
            response = self.get(RESOLVE_URL, place_id='synthetic', session='synthetic-session')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['country'], 'AU')
        self.assertEqual(provider.call_args.args[1].country_code, 'AU')
        with mock.patch('apps.geo.views.reverse', return_value=address) as provider:
            response = self.get(REVERSE_URL, lat='-33.8', lng='151.2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.call_args.args[2].country_code, 'AU')

    def test_provider_caches_are_partitioned_by_country(self):
        config = get_address_lookup_config(self.workspace)
        fixture = fixtures.ResolveTests()
        with mock.patch('apps.geo.services.google_maps.requests.request', return_value=_ok(fixture._payload())) as provider:
            self.assertIsNotNone(resolve('place-1', config))
            self.assertIsNone(resolve('place-1', replace(config, country_code='AU')))
        self.assertEqual(provider.call_count, 2)
        fixture = fixtures.ReverseTests()
        payload = {'status': 'OK', 'results': [fixture._result('12 Street', 'NZ')]}
        with mock.patch('apps.geo.services.google_maps.requests.request', return_value=_ok(payload)) as provider:
            self.assertIsNotNone(reverse(-36.8, 174.7, config))
            self.assertIsNone(reverse(-36.8, 174.7, replace(config, country_code='AU')))
        self.assertEqual(provider.call_count, 2)
