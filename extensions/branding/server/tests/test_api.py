# -*- coding: utf-8 -*-
from django.core.cache import cache
from unittest.mock import ANY, patch

from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.test import override_settings
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.test import APITestCase

from bfg.common.extensions.services import invalidate as invalidate_extension_cache
from bfg.common.middleware import set_current_workspace
from bfg.common.models import (
    APIKey,
    StaffMember,
    StaffRole,
    User,
    Workspace,
    WorkspaceDomain,
    WorkspaceExtension,
)
from bfg.platform.models import Cluster, PlatformSSOCode, WorkspacePlatformProfile
from bfg.web.models import Menu, MenuItem, Page, Post

from apps.brand_portal.models import (
    BrandPortalProfile,
    BrandPortalProvisioning,
    BrandPortalRegistration,
)
from apps.brand_portal.serializers import (
    PortalFinalizeSerializer,
    PortalLoginSerializer,
    PortalRegisterSerializer,
    PortalSSOStartSerializer,
)
from apps.brand_portal.services import make_portal_session_token
from apps.brand_portal.tests.manifests import (
    GenericExtensionRegistryMixin,
    SAMPLE_EXTENSION,
    SAMPLE_THEME_EXTENSION,
)
from config.onboarding_token import make_onboarding_token


@override_settings(PLATFORM_EMBEDDED=True, PLATFORM_WORKSPACE_SLUG='platform')
class BrandPortalAPITests(GenericExtensionRegistryMixin, APITestCase):
    def setUp(self):
        cache.clear()
        self.portal = Workspace.objects.create(
            name='Brand One', slug='brand-one-portal', is_active=True
        )
        self.author = User.objects.create_user(
            username='author', email='author@example.com', password='x'
        )
        WorkspaceExtension.all_objects.create(
            workspace=self.portal,
            key='brand_portal',
            status=WorkspaceExtension.STATUS_ACTIVE,
        )
        BrandPortalProfile.objects.create(
            workspace=self.portal,
            registration_enabled=False,
            provisioning_extensions=[SAMPLE_EXTENSION],
            default_country='NZ',
            default_currency='NZD',
            default_language='en-nz',
        )
        set_current_workspace(self.portal)
        self.api_key, self.api_secret = APIKey.create_key(self.portal, 'Portal BFF')
        self.credentials = {
            'HTTP_X_API_KEY': self.api_key.prefix,
            'HTTP_X_API_SECRET': self.api_secret,
        }

    def tearDown(self):
        set_current_workspace(None)

    def create_page(self, slug, *, status='published', workspace=None):
        workspace = workspace or self.portal
        return Page.objects.create(
            workspace=workspace,
            title=slug.title(),
            slug=slug,
            content=f'{slug} content',
            status=status,
            language='en-nz',
            published_at=timezone.now() if status == 'published' else None,
            created_by=self.author,
        )

    def create_post(self, slug, *, status='published'):
        return Post.objects.create(
            workspace=self.portal,
            title=slug.title(),
            slug=slug,
            content=f'{slug} content',
            status=status,
            language='en-nz',
            published_at=timezone.now() if status == 'published' else None,
            author=self.author,
        )

    def create_portal(self, name='Brand Two'):
        portal = Workspace.objects.create(
            name=name, slug=f'{slugify(name)}-portal', is_active=True
        )
        WorkspaceExtension.all_objects.create(
            workspace=portal,
            key='brand_portal',
            status=WorkspaceExtension.STATUS_ACTIVE,
        )
        BrandPortalProfile.objects.create(
            workspace=portal,
            registration_enabled=True,
            provisioning_extensions=[SAMPLE_THEME_EXTENSION],
        )
        set_current_workspace(portal)
        api_key, api_secret = APIKey.create_key(portal, f'{name} Portal BFF')
        set_current_workspace(self.portal)
        return portal, {
            'HTTP_X_API_KEY': api_key.prefix,
            'HTTP_X_API_SECRET': api_secret,
        }

    def create_portal_user(self, email='owner@example.test'):
        user = User.objects.create_user(
            username=email.split('@')[0], email=email, password='strong-password'
        )
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=True
        )
        BrandPortalRegistration.objects.create(
            portal_workspace=self.portal,
            user=user,
            callback_origin='https://brand-one.example.test',
            verified_at=timezone.now(),
        )
        return user

    def create_target(self, portal, user, slug='owner-shop'):
        target = Workspace.objects.create(
            name=slug.replace('-', ' ').title(), slug=slug, is_active=True
        )
        WorkspaceDomain.objects.create(
            workspace=target,
            hostname=f'{slug}.workspaces.example.test',
            kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        )
        role = StaffRole.objects.create(
            workspace=target,
            name='Admin',
            code='admin',
            is_active=True,
        )
        StaffMember.all_objects.create(
            workspace=target, user=user, role=role, is_active=True
        )
        BrandPortalProvisioning.objects.create(
            portal_workspace=portal,
            target_workspace=target,
            user=user,
            idempotency_key=f'completed-{portal.pk}-{target.pk}',
            status=BrandPortalProvisioning.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        return target

    def test_config_is_bound_to_api_key_and_hides_provisioning_extensions(self):
        response = self.client.get(
            '/api/v1/brand_portal/v1/config/',
            HTTP_X_REQUEST_ID='portal-request-1',
            **self.credentials,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Request-ID'], 'portal-request-1')
        self.assertEqual(response.data['name'], 'Brand One')
        self.assertEqual(response.data['defaults']['currency'], 'NZD')
        self.assertNotIn('workspace_id', response.data)
        self.assertNotIn('provisioning_extensions', response.data)

    def test_missing_or_invalid_credentials_return_stable_errors(self):
        missing = self.client.get(
            '/api/v1/brand_portal/v1/config/',
            HTTP_X_API_KEY=self.api_key.prefix,
        )
        invalid = self.client.get(
            '/api/v1/brand_portal/v1/config/',
            HTTP_X_API_KEY=self.api_key.prefix,
            HTTP_X_API_SECRET='wrong',
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.data['code'], 'api_credentials_required')
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(invalid.data['code'], 'invalid_api_credentials')
        self.assertEqual(invalid.data['request_id'], invalid['X-Request-ID'])

    def test_request_cannot_select_another_workspace(self):
        other = Workspace.objects.create(
            name='Brand Two', slug='brand-two-portal', is_active=True
        )
        self.create_page('about', workspace=other)

        response = self.client.get(
            f'/api/v1/brand_portal/v1/cms/pages/about/?workspace_id={other.pk}',
            **self.credentials,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'portal_selector_forbidden')

    def test_request_cannot_select_extensions_or_redirect_target(self):
        BrandPortalProfile.objects.filter(workspace=self.portal).update(
            registration_enabled=True
        )
        cache.clear()

        for field, value in (
            ('provisioning_extensions', [SAMPLE_THEME_EXTENSION]),
            ('domain', 'attacker.example'),
            ('next', 'https://attacker.example'),
        ):
            with self.subTest(field=field):
                response = self.client.post(
                    '/api/v1/brand_portal/v1/auth/finalize/',
                    {
                        'onboarding_token': 'not-reached',
                        'workspace_name': 'Blocked',
                        field: value,
                    },
                    format='json',
                    HTTP_IDEMPOTENCY_KEY=f'blocked-{field}',
                    **self.credentials,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'portal_selector_forbidden')

    def test_each_api_key_reads_only_its_own_portal_content(self):
        self.create_page('about')
        other = Workspace.objects.create(
            name='Brand Two', slug='brand-two-portal', is_active=True
        )
        WorkspaceExtension.all_objects.create(
            workspace=other,
            key='brand_portal',
            status=WorkspaceExtension.STATUS_ACTIVE,
        )
        BrandPortalProfile.objects.create(
            workspace=other,
            provisioning_extensions=[SAMPLE_THEME_EXTENSION],
            default_language='en-nz',
        )
        other_page = self.create_page('about', workspace=other)
        other_page.title = 'Brand Two About'
        other_page.save(update_fields=['title'])
        set_current_workspace(other)
        other_key, other_secret = APIKey.create_key(other, 'Portal BFF')

        response = self.client.get(
            '/api/v1/brand_portal/v1/cms/pages/about/',
            HTTP_X_API_KEY=other_key.prefix,
            HTTP_X_API_SECRET=other_secret,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'Brand Two About')
        self.assertNotEqual(response.data['title'], 'About')

    def test_page_and_post_reads_return_only_published_content(self):
        self.create_page('about')
        self.create_page('draft-page', status='draft')
        self.create_post('news')
        self.create_post('draft-post', status='draft')

        page = self.client.get(
            '/api/v1/brand_portal/v1/cms/pages/about/', **self.credentials
        )
        draft_page = self.client.get(
            '/api/v1/brand_portal/v1/cms/pages/draft-page/', **self.credentials
        )
        post = self.client.get(
            '/api/v1/brand_portal/v1/cms/posts/news/', **self.credentials
        )
        draft_post = self.client.get(
            '/api/v1/brand_portal/v1/cms/posts/draft-post/', **self.credentials
        )

        self.assertEqual(page.status_code, 200)
        self.assertNotIn('id', page.data)
        self.assertEqual(post.status_code, 200)
        self.assertNotIn('id', post.data)
        for response in (draft_page, draft_post):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data['code'], 'content_not_found')

    def test_menu_omits_inactive_and_unpublished_items(self):
        published = self.create_page('published')
        draft = self.create_page('draft', status='draft')
        menu = Menu.objects.create(
            workspace=self.portal,
            name='Header',
            slug='header',
            location='header',
            language='en-nz',
            is_active=True,
        )
        visible = MenuItem.objects.create(
            menu=menu, title='Visible', url='/published', page=published, order=1
        )
        MenuItem.objects.create(
            menu=menu, title='Draft', url='/draft', page=draft, order=2
        )
        MenuItem.objects.create(
            menu=menu, title='Inactive', url='/hidden', is_active=False, order=3
        )
        MenuItem.objects.create(
            menu=menu, title='Child', url='/child', parent=visible, order=1
        )

        response = self.client.get(
            '/api/v1/brand_portal/v1/cms/menus/header/', **self.credentials
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['title'] for item in response.data['items']], ['Visible'])
        self.assertEqual(response.data['items'][0]['children'][0]['title'], 'Child')

    def test_inactive_workspace_or_disabled_extension_is_rejected(self):
        self.portal.is_active = False
        self.portal.save(update_fields=['is_active'])
        inactive = self.client.get(
            '/api/v1/brand_portal/v1/config/', **self.credentials
        )
        self.assertEqual(inactive.status_code, 403)
        self.assertEqual(inactive.data['code'], 'portal_unavailable')

        self.portal.is_active = True
        self.portal.save(update_fields=['is_active'])
        WorkspaceExtension.all_objects.filter(
            workspace=self.portal, key='brand_portal'
        ).update(status=WorkspaceExtension.STATUS_INACTIVE)
        invalidate_extension_cache(self.portal.pk)
        disabled = self.client.get(
            '/api/v1/brand_portal/v1/config/', **self.credentials
        )
        self.assertEqual(disabled.status_code, 403)
        self.assertEqual(disabled.data['code'], 'portal_unavailable')

    def test_openapi_contains_versioned_portal_read_contract(self):
        response = self.client.get('/api/schema/?format=json')

        self.assertEqual(response.status_code, 200)
        paths = response.json()['paths']
        self.assertIn('/api/v1/brand_portal/v1/config/', paths)
        self.assertIn('/api/v1/brand_portal/v1/cms/pages/{slug}/', paths)
        self.assertIn('/api/v1/brand_portal/v1/cms/posts/{slug}/', paths)
        self.assertIn('/api/v1/brand_portal/v1/cms/menus/{slug}/', paths)
        self.assertIn('/api/v1/brand_portal/v1/auth/register/', paths)
        self.assertIn('/api/v1/brand_portal/v1/auth/verify-email/', paths)
        self.assertIn('/api/v1/brand_portal/v1/auth/login/', paths)
        self.assertIn('/api/v1/brand_portal/v1/auth/sso/start/', paths)
        self.assertIn('/api/v1/brand_portal/v1/auth/finalize/', paths)
        security = paths['/api/v1/brand_portal/v1/config/']['get']['security']
        self.assertIn({'portalApiKey': [], 'portalApiSecret': []}, security)
        register_parameters = paths['/api/v1/brand_portal/v1/auth/register/']['post'][
            'parameters'
        ]
        self.assertIn(
            ('X-Portal-Callback-Origin', True),
            [(item['name'], item.get('required')) for item in register_parameters],
        )

    def test_registration_uses_core_user_flow_without_creating_a_workspace(self):
        BrandPortalProfile.objects.filter(workspace=self.portal).update(
            registration_enabled=True
        )
        cache.clear()

        with patch(
            'apps.brand_portal.views.UserService.process_registration'
        ) as process_registration:
            response = self.client.post(
                '/api/v1/brand_portal/v1/auth/register/',
                {
                    'email': 'new-user@example.test',
                    'password': 'strong-password',
                    'password_confirm': 'strong-password',
                    'first_name': 'New',
                },
                format='json',
                HTTP_X_PORTAL_CALLBACK_ORIGIN='https://brand-one.example.test',
                **self.credentials,
            )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='new-user@example.test')
        process_registration.assert_called_once_with(user, None, request=ANY)
        raw_request = process_registration.call_args.kwargs['request']
        self.assertEqual(
            raw_request._trusted_frontend_origin, 'https://brand-one.example.test'
        )
        registration = BrandPortalRegistration.objects.get(user=user)
        self.assertEqual(registration.portal_workspace, self.portal)
        self.assertEqual(registration.callback_origin, 'https://brand-one.example.test')
        self.assertFalse(user.staff_memberships.exists())

    def test_existing_email_is_told_to_sign_in(self):
        BrandPortalProfile.objects.filter(workspace=self.portal).update(
            registration_enabled=True
        )
        cache.clear()
        User.objects.create_user(username='existing', email='existing@example.test')

        response = self.client.post(
            '/api/v1/brand_portal/v1/auth/register/',
            {
                'email': 'EXISTING@example.test',
                'password': 'strong-password',
                'password_confirm': 'strong-password',
            },
            format='json',
            HTTP_X_PORTAL_CALLBACK_ORIGIN='https://brand-one.example.test',
            **self.credentials,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'email_already_registered')

    def test_finalize_requires_verified_proof_and_is_idempotent(self):
        BrandPortalProfile.objects.filter(workspace=self.portal).update(
            registration_enabled=True
        )
        cluster = Cluster.objects.create(
            id='api-test',
            name='API test',
            region='apac',
            api_base_url='https://api.example.test',
            frontend_base_url='https://workspaces.example.test',
            db_host='db',
            redis_url='redis://cache.example.test',
            s3_bucket='test',
        )
        WorkspacePlatformProfile.objects.create(workspace=self.portal, cluster=cluster)
        user = User.objects.create_user(
            username='verified', email='verified@example.test', password='secret-pass'
        )
        email = EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=True
        )
        BrandPortalRegistration.objects.create(
            portal_workspace=self.portal,
            user=user,
            callback_origin='https://brand-one.example.test',
            verified_at=timezone.now(),
        )
        token = make_onboarding_token(email)
        cache.clear()
        payload = {
            'onboarding_token': token,
            'workspace_name': 'Portal Shop',
            'admin_name': 'Portal Owner',
        }

        first = self.client.post(
            '/api/v1/brand_portal/v1/auth/finalize/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='finalize-1',
            **self.credentials,
        )
        second = self.client.post(
            '/api/v1/brand_portal/v1/auth/finalize/',
            {**payload, 'workspace_name': 'Ignored Name'},
            format='json',
            HTTP_IDEMPOTENCY_KEY='finalize-1',
            **self.credentials,
        )

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.data['created'])
        self.assertEqual(first.data['extensions'], [SAMPLE_EXTENSION])
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.data['created'])
        self.assertEqual(second.data['workspace'], first.data['workspace'])
        self.assertEqual(second.data['redirect_url'], first.data['redirect_url'])

    def test_finalize_rejects_unverified_or_missing_idempotency_proof(self):
        BrandPortalProfile.objects.filter(workspace=self.portal).update(
            registration_enabled=True
        )
        user = User.objects.create_user(
            username='unverified', email='unverified@example.test', password='secret-pass'
        )
        email = EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=False
        )
        cache.clear()

        response = self.client.post(
            '/api/v1/brand_portal/v1/auth/finalize/',
            {
                'onboarding_token': make_onboarding_token(email),
                'workspace_name': 'Blocked Shop',
            },
            format='json',
            **self.credentials,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'onboarding_proof_required')

    def test_registration_requires_a_pure_trusted_callback_origin(self):
        BrandPortalProfile.objects.filter(workspace=self.portal).update(
            registration_enabled=True
        )
        cache.clear()
        payload = {
            'email': 'callback@example.test',
            'password': 'strong-password',
            'password_confirm': 'strong-password',
        }
        for origin in (
            '',
            'http://brand-one.example.test',
            'https://brand-one.example.test/path',
        ):
            with self.subTest(origin=origin):
                response = self.client.post(
                    '/api/v1/brand_portal/v1/auth/register/',
                    payload,
                    format='json',
                    HTTP_X_PORTAL_CALLBACK_ORIGIN=origin,
                    **self.credentials,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_callback_origin')

        body_callback = self.client.post(
            '/api/v1/brand_portal/v1/auth/register/',
            {**payload, 'callback_origin': 'https://attacker.example.test'},
            format='json',
            HTTP_X_PORTAL_CALLBACK_ORIGIN='https://brand-one.example.test',
            **self.credentials,
        )
        self.assertEqual(body_callback.status_code, 400)
        self.assertEqual(body_callback.data['code'], 'portal_selector_forbidden')

        with patch('apps.brand_portal.views.UserService.process_registration'):
            local = self.client.post(
                '/api/v1/brand_portal/v1/auth/register/',
                {**payload, 'email': 'local@example.test'},
                format='json',
                HTTP_X_PORTAL_CALLBACK_ORIGIN='http://localhost:3000',
                **self.credentials,
            )
        self.assertEqual(local.status_code, 201)
        self.assertEqual(
            BrandPortalRegistration.objects.get(user__email='local@example.test').callback_origin,
            'http://localhost:3000',
        )

    def test_verify_email_key_is_bound_to_its_registration_portal(self):
        other_portal, other_credentials = self.create_portal()
        user = User.objects.create_user(
            username='waiting',
            email='waiting@example.test',
            password='strong-password',
            is_active=False,
        )
        address = EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=False
        )
        BrandPortalRegistration.objects.create(
            portal_workspace=self.portal,
            user=user,
            callback_origin='https://brand-one.example.test',
        )
        key = EmailConfirmationHMAC(address).key

        denied = self.client.post(
            '/api/v1/brand_portal/v1/auth/verify-email/',
            {'key': key},
            format='json',
            **other_credentials,
        )
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(denied.data['code'], 'invalid_verification_key')
        address.refresh_from_db()
        self.assertFalse(address.verified)

        verified = self.client.post(
            '/api/v1/brand_portal/v1/auth/verify-email/',
            {'key': key},
            format='json',
            **self.credentials,
        )
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.data['onboarding_token'])
        registration = BrandPortalRegistration.objects.get(user=user)
        self.assertIsNotNone(registration.verified_at)

        replayed = self.client.post(
            '/api/v1/brand_portal/v1/auth/verify-email/',
            {'key': key},
            format='json',
            **self.credentials,
        )
        self.assertEqual(replayed.status_code, 400)
        self.assertEqual(replayed.data['code'], 'invalid_verification_key')

    def test_login_does_not_enumerate_accounts_or_cross_portals(self):
        user = self.create_portal_user()
        _, other_credentials = self.create_portal()
        valid = self.client.post(
            '/api/v1/brand_portal/v1/auth/login/',
            {'email': user.email, 'password': 'strong-password'},
            format='json',
            **self.credentials,
        )
        wrong_password = self.client.post(
            '/api/v1/brand_portal/v1/auth/login/',
            {'email': user.email, 'password': 'wrong-password'},
            format='json',
            **self.credentials,
        )
        missing_user = self.client.post(
            '/api/v1/brand_portal/v1/auth/login/',
            {'email': 'missing@example.test', 'password': 'wrong-password'},
            format='json',
            **self.credentials,
        )
        other_portal = self.client.post(
            '/api/v1/brand_portal/v1/auth/login/',
            {'email': user.email, 'password': 'strong-password'},
            format='json',
            **other_credentials,
        )

        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.data['expires_in'], 900)
        self.assertEqual(valid.data['workspaces'], [])
        for response in (wrong_password, missing_user, other_portal):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data['code'], 'invalid_credentials')
            self.assertEqual(response.data['detail'], 'The email or password is invalid.')

    def test_authentication_secrets_have_bounded_input_lengths(self):
        password = 'x' * 257
        self.assertFalse(
            PortalRegisterSerializer(
                data={
                    'email': 'bounded@example.test',
                    'password': password,
                    'password_confirm': password,
                }
            ).is_valid()
        )
        self.assertFalse(
            PortalLoginSerializer(
                data={'email': 'bounded@example.test', 'password': password}
            ).is_valid()
        )
        self.assertFalse(
            PortalFinalizeSerializer(
                data={'onboarding_token': 'x' * 4097, 'workspace_name': 'Bounded'}
            ).is_valid()
        )
        self.assertFalse(
            PortalSSOStartSerializer(
                data={
                    'session_token': 'x' * 4097,
                    'workspace_uuid': '00000000-0000-0000-0000-000000000001',
                }
            ).is_valid()
        )

    def test_login_lists_only_active_workspaces_from_the_same_portal(self):
        user = self.create_portal_user()
        own_target = self.create_target(self.portal, user, 'brand-one-shop')
        other_portal, _ = self.create_portal()
        self.create_target(other_portal, user, 'brand-two-shop')
        inactive_target = self.create_target(self.portal, user, 'inactive-shop')
        inactive_target.is_active = False
        inactive_target.save(update_fields=['is_active'])

        response = self.client.post(
            '/api/v1/brand_portal/v1/auth/login/',
            {'email': user.email, 'password': 'strong-password'},
            format='json',
            **self.credentials,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [workspace['uuid'] for workspace in response.data['workspaces']],
            [str(own_target.uuid)],
        )

    def test_sso_rejects_bad_expired_and_cross_portal_sessions(self):
        user = self.create_portal_user()
        target = self.create_target(self.portal, user)
        other_portal, other_credentials = self.create_portal()
        other_target = self.create_target(other_portal, user, 'brand-two-shop')
        token = make_portal_session_token(self.portal, user)

        bad = self.client.post(
            '/api/v1/brand_portal/v1/auth/sso/start/',
            {'session_token': 'bad', 'workspace_uuid': str(target.uuid)},
            format='json',
            **self.credentials,
        )
        wrong_portal = self.client.post(
            '/api/v1/brand_portal/v1/auth/sso/start/',
            {'session_token': token, 'workspace_uuid': str(target.uuid)},
            format='json',
            **other_credentials,
        )
        cross_workspace = self.client.post(
            '/api/v1/brand_portal/v1/auth/sso/start/',
            {'session_token': token, 'workspace_uuid': str(other_target.uuid)},
            format='json',
            **self.credentials,
        )
        with override_settings(BRAND_PORTAL_SESSION_TOKEN_MAX_AGE=-1):
            expired = self.client.post(
                '/api/v1/brand_portal/v1/auth/sso/start/',
                {'session_token': token, 'workspace_uuid': str(target.uuid)},
                format='json',
                **self.credentials,
            )

        for response in (bad, wrong_portal, expired):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data['code'], 'invalid_session_token')
        self.assertEqual(cross_workspace.status_code, 403)
        self.assertEqual(cross_workspace.data['code'], 'workspace_access_denied')

    def test_sso_rejects_session_after_registration_is_revoked(self):
        user = self.create_portal_user()
        target = self.create_target(self.portal, user)
        token = make_portal_session_token(self.portal, user)
        BrandPortalRegistration.objects.filter(
            portal_workspace=self.portal,
            user=user,
        ).delete()

        response = self.client.post(
            '/api/v1/brand_portal/v1/auth/sso/start/',
            {'session_token': token, 'workspace_uuid': str(target.uuid)},
            format='json',
            **self.credentials,
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['code'], 'invalid_session_token')

    def test_sso_uses_platform_domain_and_fixed_admin_next(self):
        user = self.create_portal_user()
        target = self.create_target(self.portal, user)
        token = make_portal_session_token(self.portal, user)

        response = self.client.post(
            '/api/v1/brand_portal/v1/auth/sso/start/',
            {'session_token': token, 'workspace_uuid': str(target.uuid)},
            format='json',
            **self.credentials,
        )

        self.assertEqual(response.status_code, 200)
        code = PlatformSSOCode.objects.get(code=response.data['redirect_url'].split('code=')[1])
        self.assertEqual(code.workspace, target)
        self.assertEqual(code.user, user)
        self.assertEqual(code.next_url, '/admin')
        self.assertEqual(code.redirect_domain, 'https://owner-shop.workspaces.example.test')
        self.assertNotIn('next=', response.data['redirect_url'])


    def test_verified_login_resumes_setup_only_before_first_provisioning(self):
        from config.onboarding_token import user_for_onboarding_token

        BrandPortalProfile.objects.filter(workspace=self.portal).update(registration_enabled=True)
        cache.clear()
        user = User.objects.create_user(username='resume-owner', email='resume@example.test', password='strong-password')
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        BrandPortalRegistration.objects.create(portal_workspace=self.portal, user=user,
                                              callback_origin='https://brand-one.example.test', verified_at=timezone.now())
        credentials = {'email': user.email, 'password': 'strong-password'}
        response = self.client.post('/api/v1/brand_portal/v1/auth/login/', credentials, format='json', **self.credentials)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['workspaces'], [])
        self.assertEqual(user_for_onboarding_token(response.data['onboarding_token']), user)
        other, other_keys = self.create_portal()
        denied = self.client.post('/api/v1/brand_portal/v1/auth/login/', credentials, format='json', **other_keys)
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn('onboarding_token', denied.data)
        BrandPortalProvisioning.objects.create(portal_workspace=self.portal, user=user, idempotency_key='completed-resume',
                                              status=BrandPortalProvisioning.STATUS_COMPLETED)
        completed = self.client.post('/api/v1/brand_portal/v1/auth/login/', credentials, format='json', **self.credentials)
        self.assertEqual(completed.status_code, 200)
        self.assertNotIn('onboarding_token', completed.data)

    def test_verified_login_does_not_resume_setup_when_registration_disabled(self):
        user = User.objects.create_user(username='disabled-resume', email='disabled-resume@example.test', password='strong-password')
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        BrandPortalRegistration.objects.create(portal_workspace=self.portal, user=user,
                                              callback_origin='https://brand-one.example.test', verified_at=timezone.now())
        response = self.client.post('/api/v1/brand_portal/v1/auth/login/',
                                    {'email': user.email, 'password': 'strong-password'}, format='json', **self.credentials)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('onboarding_token', response.data)
