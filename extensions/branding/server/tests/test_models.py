# -*- coding: utf-8 -*-
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from bfg.common.extensions import (
    ACTIVATION_PLATFORM_ADMIN,
    VISIBILITY_PRIVATE,
    services as extension_services,
)
from bfg.common.models import StaffMember, StaffRole, User, Workspace, WorkspaceExtension
from bfg.platform.models import PlatformSSOCode

from apps.brand_portal.extension import EXTENSION
from apps.brand_portal.models import BrandPortalProfile, BrandPortalProvisioning
from apps.brand_portal.services import profile_snapshot, save_profile
from apps.brand_portal.tests.manifests import (
    GenericExtensionRegistryMixin,
    SAMPLE_EXTENSION,
    SAMPLE_SKIN,
    SAMPLE_THEME_EXTENSION,
)


@override_settings(PLATFORM_EMBEDDED=True, PLATFORM_WORKSPACE_SLUG='platform')
class BrandPortalModelTests(GenericExtensionRegistryMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.platform = Workspace.objects.create(name='Platform', slug='platform', is_active=True)
        self.portal = Workspace.objects.create(name='Brand One', slug='brand-one-portal', is_active=True)
        role = StaffRole.objects.create(workspace=self.platform, code='admin', name='Admin')
        self.operator = User.objects.create_user(
            username='operator', email='operator@example.com', password='x'
        )
        StaffMember.all_objects.create(
            workspace=self.platform,
            user=self.operator,
            role=role,
            is_active=True,
        )
        self.owner = User.objects.create_user(
            username='owner', email='owner@example.com', password='x'
        )

    def activate_portal(self):
        return WorkspaceExtension.all_objects.create(
            workspace=self.portal,
            key='brand_portal',
            status=WorkspaceExtension.STATUS_ACTIVE,
            status_changed_by=self.operator,
        )

    def test_manifest_is_private_server_only_and_platform_managed(self):
        self.assertEqual(EXTENSION.visibility, VISIBILITY_PRIVATE)
        self.assertEqual(EXTENSION.activation_policy, ACTIVATION_PLATFORM_ADMIN)
        self.assertEqual(EXTENSION.surfaces, ())

    def test_registration_cannot_be_enabled_before_the_extension_is_active(self):
        profile = BrandPortalProfile(
            workspace=self.portal,
            registration_enabled=True,
            provisioning_extensions=[SAMPLE_EXTENSION],
        )

        with self.assertRaises(ValidationError) as refused:
            profile.full_clean()

        self.assertIn('registration_enabled', refused.exception.message_dict)

    def test_profile_accepts_only_public_owner_manageable_workspace_extensions(self):
        self.activate_portal()

        for key in ('not_deployed', 'brand_portal', 'sign_in'):
            profile = BrandPortalProfile(
                workspace=self.portal,
                provisioning_extensions=[key],
            )
            with self.subTest(key=key), self.assertRaises(ValidationError) as refused:
                profile.full_clean()
            self.assertIn('provisioning_extensions', refused.exception.message_dict)

        profile = BrandPortalProfile(
            workspace=self.portal,
            provisioning_extensions=[SAMPLE_EXTENSION],
            default_country=' nz ',
            default_currency=' nzd ',
            default_language=' EN-NZ ',
        )
        profile.full_clean()
        self.assertEqual(profile.provisioning_extensions, [SAMPLE_EXTENSION])
        self.assertEqual(
            (profile.default_country, profile.default_currency, profile.default_language),
            ('NZ', 'NZD', 'en-nz'),
        )

        profile.provisioning_extensions = [SAMPLE_EXTENSION] * 33
        with self.assertRaises(ValidationError) as refused:
            profile.full_clean()
        self.assertIn('provisioning_extensions', refused.exception.message_dict)

    def test_profile_theme_must_be_available_from_its_extensions(self):
        self.activate_portal()

        profile = BrandPortalProfile(
            workspace=self.portal,
            provisioning_extensions=[SAMPLE_THEME_EXTENSION],
            default_theme=f' {SAMPLE_SKIN.upper()} ',
        )
        profile.full_clean()
        self.assertEqual(profile.default_theme, SAMPLE_SKIN)

        profile.provisioning_extensions = [SAMPLE_EXTENSION]
        with self.assertRaises(ValidationError) as refused:
            profile.full_clean()
        self.assertEqual(
            refused.exception.message_dict['default_theme'],
            ['Unsupported storefront theme.'],
        )

        profile.default_theme = 'not-installed'
        with self.assertRaises(ValidationError) as refused:
            profile.full_clean()
        self.assertEqual(
            refused.exception.message_dict['default_theme'],
            ['Unsupported storefront theme.'],
        )

    def test_only_a_platform_administrator_can_save_and_audit_a_profile(self):
        self.activate_portal()
        values = {
            'registration_enabled': True,
            'provisioning_extensions': [SAMPLE_EXTENSION],
            'default_country': 'nz',
        }

        with self.assertRaises(PermissionDenied):
            save_profile(self.portal, values, actor=self.owner)

        profile = save_profile(self.portal, values, actor=self.operator)
        public_id = profile.public_id
        profile = save_profile(
            self.portal,
            {'default_country': 'au'},
            actor=self.operator,
        )

        self.assertEqual(profile.public_id, public_id)
        self.assertEqual(profile.default_country, 'AU')
        self.assertEqual(profile.created_by, self.operator)
        self.assertEqual(profile.updated_by, self.operator)

    def test_profile_cache_changes_after_commit_without_a_restart(self):
        self.activate_portal()
        self.assertEqual(
            profile_snapshot(self.portal),
            {'configured': False, 'registration_enabled': False},
        )

        with self.captureOnCommitCallbacks(execute=True):
            save_profile(
                self.portal,
                {
                    'registration_enabled': True,
                    'provisioning_extensions': [SAMPLE_EXTENSION],
                    'default_language': 'en-nz',
                },
                actor=self.operator,
            )

        snapshot = profile_snapshot(self.portal)
        self.assertTrue(snapshot['configured'])
        self.assertTrue(snapshot['registration_enabled'])
        self.assertEqual(snapshot['provisioning_extensions'], [SAMPLE_EXTENSION])

    def test_deactivation_disables_registration_and_invalidates_the_cache(self):
        self.activate_portal()
        profile = BrandPortalProfile.objects.create(
            workspace=self.portal,
            registration_enabled=True,
            provisioning_extensions=[SAMPLE_EXTENSION],
            created_by=self.operator,
            updated_by=self.operator,
        )
        profile_snapshot(self.portal)

        with self.captureOnCommitCallbacks(execute=True):
            extension_services.deactivate(
                self.portal,
                'brand_portal',
                user=self.operator,
                actor=ACTIVATION_PLATFORM_ADMIN,
            )

        profile.refresh_from_db()
        self.assertFalse(profile.registration_enabled)
        self.assertEqual(profile.updated_by, self.operator)
        self.assertFalse(profile_snapshot(self.portal)['registration_enabled'])

    def test_provisioning_idempotency_is_scoped_to_the_portal_workspace(self):
        other = Workspace.objects.create(name='Brand Two', slug='brand-two-portal', is_active=True)
        fields = {
            'user': self.owner,
            'idempotency_key': 'request-1',
            'profile_snapshot': {'provisioning_extensions': [SAMPLE_EXTENSION]},
        }
        BrandPortalProvisioning.objects.create(portal_workspace=self.portal, **fields)
        BrandPortalProvisioning.objects.create(portal_workspace=other, **fields)

        with self.assertRaises(IntegrityError), transaction.atomic():
            BrandPortalProvisioning.objects.create(portal_workspace=self.portal, **fields)

    def test_completed_and_failed_provisioning_states_are_validated(self):
        completed = BrandPortalProvisioning(
            portal_workspace=self.portal,
            user=self.owner,
            idempotency_key='completed',
            status=BrandPortalProvisioning.STATUS_COMPLETED,
        )
        with self.assertRaises(ValidationError) as refused:
            completed.full_clean()
        self.assertEqual(
            set(refused.exception.message_dict),
            {'target_workspace', 'completed_at', 'sso_code'},
        )

        completed.target_workspace = Workspace.objects.create(
            name='Target', slug='target', is_active=True
        )
        completed.completed_at = timezone.now()
        completed.sso_code = PlatformSSOCode.objects.create(
            workspace=completed.target_workspace,
            user=self.owner,
            redirect_domain='https://target.example.test',
        )
        completed.full_clean()

        failed = BrandPortalProvisioning(
            portal_workspace=self.portal,
            user=self.owner,
            idempotency_key='failed',
            status=BrandPortalProvisioning.STATUS_FAILED,
        )
        with self.assertRaises(ValidationError) as refused:
            failed.full_clean()
        self.assertIn('error_code', refused.exception.message_dict)
