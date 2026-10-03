# -*- coding: utf-8 -*-
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from bfg.common.extensions.services import ExtensionError
from bfg.common.models import Settings, StaffMember, User, Workspace, WorkspaceExtension
from bfg.platform.models import Cluster, PlatformMembership, WorkspacePlatformProfile
from bfg.platform.services import entitlements

from apps.brand_portal.models import BrandPortalProfile, BrandPortalProvisioning
from apps.brand_portal.services import (
    PortalProvisioningError,
    _apply_theme,
    provision_workspace_from_portal,
)
from apps.brand_portal.tests.manifests import (
    GenericExtensionRegistryMixin,
    SAMPLE_EXTENSION,
    SAMPLE_SKIN,
    SAMPLE_THEME_EXTENSION,
)


@override_settings(PLATFORM_EMBEDDED=True, PLATFORM_WORKSPACE_SLUG='platform')
class BrandPortalProvisioningTests(GenericExtensionRegistryMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.cluster = Cluster.objects.create(
            id='portal-test',
            name='Portal test',
            region='apac',
            api_base_url='https://api.example.test',
            frontend_base_url='https://workspaces.example.test',
            db_host='db',
            redis_url='redis://cache.example.test',
            s3_bucket='test',
        )
        self.user = User.objects.create_user(
            username='new-owner', email='owner@example.test', password='secret-pass'
        )
        self.portal = self.create_portal(
            'Brand One', 'brand-one-portal', [SAMPLE_EXTENSION]
        )

    def create_portal(self, name, slug, extensions, *, default_theme='store'):
        portal = Workspace.objects.create(name=name, slug=slug, is_active=True)
        WorkspacePlatformProfile.objects.create(workspace=portal, cluster=self.cluster)
        WorkspaceExtension.all_objects.create(
            workspace=portal,
            key='brand_portal',
            status=WorkspaceExtension.STATUS_ACTIVE,
        )
        BrandPortalProfile.objects.create(
            workspace=portal,
            registration_enabled=True,
            provisioning_extensions=extensions,
            default_theme=default_theme,
            default_country='NZ',
            default_currency='NZD',
            default_language='en-nz',
        )
        return portal

    def provision(self, portal=None, key='request-1', name='Owner Shop'):
        return provision_workspace_from_portal(
            portal or self.portal,
            self.user,
            idempotency_key=key,
            name=name,
            admin_name='Casey Owner',
        )

    def test_brand_one_creates_owned_admin_workspace_with_only_configured_extension(self):
        attempt, created = self.provision()
        workspace = attempt.target_workspace

        self.assertTrue(created)
        self.assertEqual(attempt.status, BrandPortalProvisioning.STATUS_COMPLETED)
        self.assertEqual(attempt.sso_code.workspace, workspace)
        self.assertEqual(attempt.sso_code.user, self.user)
        self.assertEqual(attempt.sso_code.next_url, '/admin')
        self.assertEqual(
            attempt.sso_code.redirect_domain,
            f'https://{workspace.slug}.workspaces.example.test',
        )
        self.assertTrue(
            PlatformMembership.objects.filter(
                user=self.user,
                profile__workspace=workspace,
                role='owner',
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            StaffMember.all_objects.filter(
                user=self.user,
                workspace=workspace,
                role__code='admin',
                is_active=True,
            ).exists()
        )
        active = set(
            WorkspaceExtension.all_objects.filter(
                workspace=workspace,
                status=WorkspaceExtension.STATUS_ACTIVE,
            ).values_list('key', flat=True)
        )
        self.assertEqual(active, {SAMPLE_EXTENSION})
        workspace_settings = Settings.objects.get(workspace=workspace)
        self.assertEqual(workspace_settings.country, 'NZ')
        self.assertEqual(workspace_settings.default_currency, 'NZD')
        self.assertEqual(
            workspace_settings.custom_settings['storefront_ui']['theme'],
            'store',
        )

    def test_brand_two_uses_its_own_snapshot_and_does_not_grant_portal_staff(self):
        brand_two = self.create_portal(
            'Brand Two', 'brand-two-portal', [SAMPLE_THEME_EXTENSION], default_theme=''
        )
        portal_staff = User.objects.create_user(username='portal-staff')
        portal_role = self.portal.staff_roles.create(code='staff', name='Staff')
        StaffMember.all_objects.create(
            workspace=self.portal, user=portal_staff, role=portal_role, is_active=True
        )

        attempt, _ = self.provision(
            portal=brand_two, key='brand-two-1', name='Second Brand Shop'
        )
        workspace = attempt.target_workspace
        active = set(
            WorkspaceExtension.all_objects.filter(
                workspace=workspace,
                status=WorkspaceExtension.STATUS_ACTIVE,
            ).values_list('key', flat=True)
        )

        self.assertEqual(active, {SAMPLE_THEME_EXTENSION})
        self.assertEqual(
            Settings.objects.get(workspace=workspace).custom_settings['storefront_ui']['theme'],
            SAMPLE_SKIN,
        )
        self.assertFalse(
            StaffMember.all_objects.filter(
                workspace=workspace, user=portal_staff
            ).exists()
        )
        self.assertFalse(
            PlatformMembership.objects.filter(
                profile__workspace=workspace, user=portal_staff
            ).exists()
        )

    def test_explicit_portal_theme_wins_over_extension_default(self):
        brand_two = self.create_portal(
            'Brand Two', 'brand-two-portal', [SAMPLE_THEME_EXTENSION], default_theme='website'
        )

        attempt, _ = self.provision(
            portal=brand_two, key='brand-two-website', name='Second Brand Website'
        )

        self.assertEqual(
            Settings.objects.get(
                workspace=attempt.target_workspace
            ).custom_settings['storefront_ui']['theme'],
            'website',
        )

    def test_explicit_portal_theme_invalidates_a_warmed_storefront_cache(self):
        workspace = Workspace.objects.create(
            name='Cached storefront', slug='cached-storefront', is_active=True
        )
        workspace_settings = Settings.objects.get(workspace=workspace)
        api = APIClient()
        api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
        self.assertEqual(
            api.get('/api/v1/settings/storefront/').json()['theme'],
            'store',
        )

        with self.captureOnCommitCallbacks(execute=True):
            _apply_theme(workspace_settings, 'website', extension_keys=[])

        self.assertEqual(
            api.get('/api/v1/settings/storefront/').json()['theme'],
            'website',
        )

    @override_settings(
        BFG_EXTENSION_ENTITLEMENT_CHECK=(
            'bfg.platform.services.entitlements.entitlement_check'
        )
    )
    def test_brand_two_grants_extension_entitlement_before_activation(self):
        brand_two = self.create_portal(
            'Brand Two', 'brand-two-portal', [SAMPLE_THEME_EXTENSION]
        )

        attempt, _ = self.provision(portal=brand_two, key='brand-two-entitled')
        workspace = attempt.target_workspace

        self.assertTrue(entitlements.is_entitled(workspace, SAMPLE_THEME_EXTENSION))
        self.assertTrue(
            WorkspaceExtension.all_objects.filter(
                workspace=workspace,
                key=SAMPLE_THEME_EXTENSION,
                status=WorkspaceExtension.STATUS_ACTIVE,
            ).exists()
        )

    def test_completed_idempotency_key_returns_the_original_result(self):
        first, first_created = self.provision()
        second, second_created = self.provision(name='Ignored New Name')

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(second.target_workspace_id, first.target_workspace_id)
        self.assertEqual(second.sso_code_id, first.sso_code_id)
        self.assertEqual(
            BrandPortalProvisioning.objects.filter(portal_workspace=self.portal).count(),
            1,
        )

    def test_extension_failure_rolls_back_workspace_and_same_key_retries_snapshot(self):
        baseline_ids = set(Workspace.objects.values_list('id', flat=True))
        original_activate = __import__(
            'bfg.common.extensions.services', fromlist=['activate']
        ).activate
        with patch(
            'apps.brand_portal.services.extension_services.activate',
            side_effect=ExtensionError('test_failure', 'sensitive internal reason'),
        ):
            with self.assertRaises(PortalProvisioningError) as refused:
                self.provision()

        attempt = BrandPortalProvisioning.objects.get(
            portal_workspace=self.portal, idempotency_key='request-1'
        )
        self.assertEqual(attempt.status, BrandPortalProvisioning.STATUS_FAILED)
        self.assertEqual(attempt.error_code, 'extension_activation_failed')
        self.assertNotIn('sensitive', attempt.error_detail)
        self.assertEqual(set(Workspace.objects.values_list('id', flat=True)), baseline_ids)

        profile = self.portal.brand_portal_profile
        profile.provisioning_extensions = [SAMPLE_THEME_EXTENSION]
        profile.save(update_fields=['provisioning_extensions', 'updated_at'])
        with patch(
            'apps.brand_portal.services.extension_services.activate',
            side_effect=original_activate,
        ):
            retried, created = self.provision(name='Changed Retry Name')

        self.assertTrue(created)
        self.assertEqual(retried.target_workspace.name, 'Owner Shop')
        self.assertEqual(
            retried.profile_snapshot['provisioning_extensions'],
            [SAMPLE_EXTENSION],
        )
        self.assertTrue(
            WorkspaceExtension.all_objects.filter(
                workspace=retried.target_workspace,
                key=SAMPLE_EXTENSION,
                status=WorkspaceExtension.STATUS_ACTIVE,
            ).exists()
        )

    def test_missing_cluster_domain_rolls_back_and_records_stable_failure(self):
        WorkspacePlatformProfile.objects.filter(workspace=self.portal).update(cluster=None)

        with self.assertRaises(PortalProvisioningError) as refused:
            self.provision()

        self.assertEqual(refused.exception.code, 'workspace_domain_unavailable')
        attempt = BrandPortalProvisioning.objects.get(portal_workspace=self.portal)
        self.assertEqual(attempt.status, BrandPortalProvisioning.STATUS_FAILED)
        self.assertIsNone(attempt.target_workspace)

    @override_settings(BFG_MAX_OWNED_WORKSPACES_PER_USER=1)
    def test_owner_limit_is_checked_under_the_user_lock(self):
        first, _ = self.provision()

        with self.assertRaises(PortalProvisioningError) as refused:
            self.provision(key='request-2', name='Second Shop')

        self.assertEqual(refused.exception.code, 'workspace_limit_reached')
        self.assertEqual(
            PlatformMembership.objects.filter(user=self.user, role='owner').count(), 1
        )
        self.assertIsNotNone(first.target_workspace)
