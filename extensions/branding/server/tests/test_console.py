# -*- coding: utf-8 -*-
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from bfg.common.models import (
    StaffMember,
    StaffRole,
    User,
    Workspace,
    WorkspaceDomain,
    WorkspaceExtension,
)
from bfg.platform.models import WorkspacePlatformProfile
from bfg.platform.services.ownership import assign_workspace_owner

from apps.brand_portal.models import BrandPortalProfile, BrandPortalProvisioning
from apps.brand_portal.tests.manifests import (
    GenericExtensionRegistryMixin,
    SAMPLE_EXTENSION,
    SAMPLE_THEME_EXTENSION,
)


@override_settings(PLATFORM_EMBEDDED=True, PLATFORM_WORKSPACE_SLUG='platform')
class BrandPortalConsoleTests(GenericExtensionRegistryMixin, APITestCase):
    def setUp(self):
        cache.clear()
        self.platform = Workspace.objects.create(
            name='Platform', slug='platform', is_active=True
        )
        platform_admin_role = StaffRole.objects.create(
            workspace=self.platform, code='admin', name='Admin'
        )
        self.admin = User.objects.create_user(username='platform-admin')
        StaffMember.all_objects.create(
            workspace=self.platform,
            user=self.admin,
            role=platform_admin_role,
            is_active=True,
        )
        self.portal = Workspace.objects.create(
            name='Brand One', slug='brand-one-portal', is_active=True
        )
        WorkspacePlatformProfile.objects.create(workspace=self.portal)
        self.owner = User.objects.create_user(username='portal-owner')
        assign_workspace_owner(self.portal, self.owner)
        WorkspaceExtension.all_objects.create(
            workspace=self.portal,
            key='brand_portal',
            status=WorkspaceExtension.STATUS_ACTIVE,
            status_changed_by=self.admin,
        )
        self.url = f'/api/v1/brand_portal/v1/console/workspaces/{self.portal.pk}/'

    def test_platform_admin_can_read_schema_domains_and_recent_audit(self):
        WorkspaceDomain.objects.create(
            workspace=self.portal,
            hostname='brand-one.example.test',
            kind=WorkspaceDomain.KIND_CUSTOM,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
            ssl_status=WorkspaceDomain.SSL_ACTIVE,
            is_primary=True,
        )
        user = User.objects.create_user(username='provisioned')
        BrandPortalProvisioning.objects.create(
            portal_workspace=self.portal,
            user=user,
            idempotency_key='failed-1',
            profile_snapshot={'provisioning_extensions': [SAMPLE_EXTENSION]},
            status=BrandPortalProvisioning.STATUS_FAILED,
            error_code='extension_activation_failed',
            error_detail='internal detail must stay private',
        )
        self.client.force_authenticate(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['extension_active'])
        option_keys = {item['key'] for item in response.data['extension_options']}
        self.assertIn(SAMPLE_EXTENSION, option_keys)
        self.assertIn(SAMPLE_THEME_EXTENSION, option_keys)
        self.assertNotIn('brand_portal', option_keys)
        self.assertEqual(
            response.data['verified_domains'][0]['hostname'], 'brand-one.example.test'
        )
        audit = response.data['recent_provisionings'][0]
        self.assertEqual(audit['error_code'], 'extension_activation_failed')
        self.assertNotIn('error_detail', audit)

    def test_platform_admin_can_save_validated_profile_and_cache_changes_immediately(self):
        BrandPortalProfile.objects.create(
            workspace=self.portal,
            registration_enabled=False,
            provisioning_extensions=[SAMPLE_THEME_EXTENSION],
        )
        self.client.force_authenticate(self.admin)
        from apps.brand_portal.services import profile_snapshot

        self.assertFalse(profile_snapshot(self.portal)['registration_enabled'])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                self.url,
                {
                    'registration_enabled': True,
                    'provisioning_extensions': [SAMPLE_EXTENSION],
                    'default_country': 'nz',
                    'default_currency': 'nzd',
                    'default_language': 'en-nz',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['profile']['provisioning_extensions'],
            [SAMPLE_EXTENSION],
        )
        self.assertEqual(response.data['profile']['default_country'], 'NZ')
        self.assertTrue(profile_snapshot(self.portal)['registration_enabled'])

    def test_owner_cannot_discover_profile_console_or_private_extension(self):
        self.client.force_authenticate(self.owner)

        profile = self.client.get(self.url)
        workspace = self.client.get(
            f'/api/v1/platform/console/workspaces/{self.portal.pk}/'
        )

        self.assertEqual(profile.status_code, 403)
        self.assertEqual(workspace.status_code, 200)
        self.assertNotIn(
            'brand_portal', {item['key'] for item in workspace.data['extensions']}
        )

    def test_invalid_extension_and_unknown_fields_return_stable_validation_error(self):
        self.client.force_authenticate(self.admin)

        for payload in (
            {'provisioning_extensions': ['brand_portal']},
            {'unknown': 'value'},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(self.url, payload, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_portal_profile')

    def test_inactive_or_suspended_workspace_cannot_change_profile(self):
        self.client.force_authenticate(self.admin)
        self.portal.is_active = False
        self.portal.save(update_fields=['is_active'])

        inactive = self.client.patch(
            self.url, {'registration_enabled': False}, format='json'
        )
        self.assertEqual(inactive.status_code, 409)
        self.assertEqual(inactive.data['code'], 'workspace_inactive')

        self.portal.is_active = True
        self.portal.save(update_fields=['is_active'])
        WorkspacePlatformProfile.objects.filter(workspace=self.portal).update(
            suspended_at=timezone.now()
        )
        suspended = self.client.patch(
            self.url, {'registration_enabled': False}, format='json'
        )
        self.assertEqual(suspended.status_code, 409)
        self.assertEqual(suspended.data['code'], 'workspace_suspended')

    def test_profile_cannot_be_saved_until_private_extension_is_active(self):
        WorkspaceExtension.all_objects.filter(
            workspace=self.portal, key='brand_portal'
        ).update(status=WorkspaceExtension.STATUS_INACTIVE)
        cache.clear()
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            self.url, {'registration_enabled': False}, format='json'
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'portal_extension_inactive')
