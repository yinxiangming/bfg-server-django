# -*- coding: utf-8 -*-
import re
import uuid
from ipaddress import ip_address

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from bfg.common.extensions import services as extension_services
from bfg.common.models import APIKey, StaffMember, resolve_workspace_public_frontend_base_url
from bfg.common.services import UserService
from bfg.platform.models import PlatformSSOCode
from bfg.web.exceptions import PageNotFound, PostNotFound
from bfg.web.models import Menu
from bfg.web.services.page_service import PageService
from bfg.web.services.post_service import PostService

from .authentication import PortalAPIKeyAuthentication
from .serializers import (
    PortalConfigSerializer,
    PortalErrorSerializer,
    PortalFinalizeSerializer,
    PortalLoginResultSerializer,
    PortalLoginSerializer,
    PortalMenuSerializer,
    PortalPageSerializer,
    PortalPostSerializer,
    PortalProvisioningResultSerializer,
    PortalRegisterResultSerializer,
    PortalRegisterSerializer,
    PortalSSOStartResultSerializer,
    PortalSSOStartSerializer,
    PortalVerifyEmailResultSerializer,
    PortalVerifyEmailSerializer,
)
from .services import (
    PortalProvisioningError,
    make_portal_session_token,
    normalize_callback_origin,
    portal_session_max_age,
    portal_workspaces,
    profile_snapshot,
    provision_workspace_from_portal,
    provisioning_response,
    user_for_portal_session_token,
)
from .models import BrandPortalProvisioning, BrandPortalRegistration


FORBIDDEN_PORTAL_SELECTORS = frozenset(
    {
        'domain',
        'callback',
        'callback_origin',
        'callback_url',
        'extensions',
        'next',
        'portal_workspace_id',
        'provisioning_extensions',
        'redirect',
        'redirect_url',
        'store_name',
        'workspace',
        'workspace_id',
    }
)
REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
LANGUAGE_PARAMETER = OpenApiParameter(
    name='language',
    type=str,
    location=OpenApiParameter.QUERY,
    required=False,
    description='Preferred content language. Defaults to the portal profile language or en.',
)
CALLBACK_ORIGIN_PARAMETER = OpenApiParameter(
    name='X-Portal-Callback-Origin',
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description='Trusted BFF origin used for the email verification link.',
)
ERROR_RESPONSES = {
    400: OpenApiResponse(PortalErrorSerializer, description='Invalid portal request.'),
    401: OpenApiResponse(PortalErrorSerializer, description='Invalid or missing API credentials.'),
    403: OpenApiResponse(PortalErrorSerializer, description='Portal workspace is unavailable.'),
    404: OpenApiResponse(PortalErrorSerializer, description='Published content was not found.'),
    409: OpenApiResponse(PortalErrorSerializer, description='Portal request conflicts with state.'),
    429: OpenApiResponse(PortalErrorSerializer, description='Portal write rate limit exceeded.'),
    503: OpenApiResponse(PortalErrorSerializer, description='A required service is unavailable.'),
}


class PortalRateThrottle(SimpleRateThrottle):
    """Rate portal writes per API key and caller address without global settings."""

    rate = '30/hour'

    def get_cache_key(self, request, view):
        auth = getattr(request, 'auth', None)
        workspace_id = getattr(auth, 'workspace_id', None)
        if workspace_id is None:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': f'{workspace_id}:{self.get_ident(request)}',
        }


class PortalRegisterThrottle(PortalRateThrottle):
    scope = 'brand_portal_register'
    rate = '10/hour'


class PortalFinalizeThrottle(PortalRateThrottle):
    scope = 'brand_portal_finalize'
    rate = '30/hour'


class PortalVerifyEmailThrottle(PortalRateThrottle):
    scope = 'brand_portal_verify_email'
    rate = '30/hour'


class PortalLoginThrottle(PortalRateThrottle):
    scope = 'brand_portal_login'
    rate = '20/hour'


class PortalSSOStartThrottle(PortalRateThrottle):
    scope = 'brand_portal_sso_start'
    rate = '60/hour'


class PortalAPIError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'invalid_request'

    def __init__(self, code, detail, *, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        self.portal_code = code
        super().__init__(detail=detail, code=code)


class PortalAPIView(APIView):
    """Server-to-server portal API bound exclusively by an API key."""

    authentication_classes = [PortalAPIKeyAuthentication]
    permission_classes = []

    def initialize_request(self, request, *args, **kwargs):
        request = super().initialize_request(request, *args, **kwargs)
        supplied = request.headers.get('X-Request-ID', '')
        request.portal_request_id = (
            supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid.uuid4())
        )
        return request

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not isinstance(request.auth, APIKey):
            raise PortalAPIError(
                'api_credentials_required',
                'Valid portal API credentials are required.',
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        workspace = request.auth.workspace
        if not workspace.is_active or not extension_services.is_available(
            workspace, 'brand_portal'
        ):
            raise PortalAPIError(
                'portal_unavailable',
                'The portal is unavailable.',
                status_code=status.HTTP_403_FORBIDDEN,
            )

        supplied_selectors = set(
            FORBIDDEN_PORTAL_SELECTORS.intersection(request.query_params)
        )
        if hasattr(request.data, 'keys'):
            supplied_selectors.update(
                FORBIDDEN_PORTAL_SELECTORS.intersection(request.data.keys())
            )
        if supplied_selectors:
            raise PortalAPIError(
                'portal_selector_forbidden',
                'Portal routing and provisioning are controlled by the server.',
            )
        request.portal_workspace = workspace

    def handle_exception(self, exc):
        if isinstance(exc, PortalAPIError):
            code = exc.portal_code
            detail = str(exc.detail)
            status_code = exc.status_code
        elif isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
            code = 'invalid_api_credentials'
            detail = 'Valid portal API credentials are required.'
            status_code = status.HTTP_401_UNAUTHORIZED
        elif isinstance(exc, exceptions.Throttled):
            code = 'rate_limited'
            detail = 'Too many portal requests. Try again later.'
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        else:
            return super().handle_exception(exc)

        return Response(
            {
                'code': code,
                'detail': detail,
                'request_id': self.request.portal_request_id,
            },
            status=status_code,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['X-Request-ID'] = request.portal_request_id
        return response

    def get_language(self, request):
        language = request.query_params.get('language', '').strip().lower()
        if language and (len(language) > 16 or not re.fullmatch(r'[a-z0-9-]+', language)):
            raise PortalAPIError('invalid_language', 'The requested language is invalid.')
        if language:
            return language
        return profile_snapshot(request.portal_workspace).get('default_language') or 'en'

    def content_not_found(self):
        raise PortalAPIError(
            'content_not_found',
            'Published content was not found.',
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PortalConfigView(PortalAPIView):
    @extend_schema(
        operation_id='brand_portal_v1_config',
        responses={200: PortalConfigSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def get(self, request):
        snapshot = profile_snapshot(request.portal_workspace)
        if not snapshot.get('configured'):
            raise PortalAPIError(
                'portal_not_configured',
                'The portal is not configured.',
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            {
                'portal_id': snapshot['public_id'],
                'name': request.portal_workspace.name,
                'registration_enabled': snapshot['registration_enabled'],
                'defaults': {
                    key.removeprefix('default_'): snapshot.get(key, '')
                    for key in (
                        'default_theme',
                        'default_plan',
                        'default_country',
                        'default_currency',
                        'default_language',
                    )
                },
            }
        )


class PortalRegisterView(PortalAPIView):
    throttle_classes = [PortalRegisterThrottle]

    @extend_schema(
        operation_id='brand_portal_v1_register',
        request=PortalRegisterSerializer,
        parameters=[CALLBACK_ORIGIN_PARAMETER],
        responses={201: PortalRegisterResultSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def post(self, request):
        snapshot = profile_snapshot(request.portal_workspace)
        if not snapshot.get('configured') or not snapshot.get('registration_enabled'):
            raise PortalAPIError(
                'registration_disabled',
                'Registration is not available.',
                status_code=status.HTTP_403_FORBIDDEN,
            )

        try:
            callback_origin = normalize_callback_origin(
                request.headers.get('X-Portal-Callback-Origin', '')
            )
        except PortalProvisioningError as exc:
            raise PortalAPIError(exc.code, exc.detail, status_code=exc.status_code) from exc

        email = str(request.data.get('email', '')).strip().lower()
        if email and get_user_model().objects.filter(email__iexact=email).exists():
            raise PortalAPIError(
                'email_already_registered',
                'This email already has an account. Sign in to continue.',
                status_code=status.HTTP_409_CONFLICT,
            )
        serializer = PortalRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalAPIError('invalid_registration', 'Registration data is invalid.')
        try:
            with transaction.atomic():
                user = serializer.save()
                BrandPortalRegistration.objects.create(
                    portal_workspace=request.portal_workspace,
                    user=user,
                    callback_origin=callback_origin,
                )
                request._request._trusted_frontend_origin = callback_origin
                if settings.EMAIL_VERIFICATION_REQUIRED:
                    UserService.process_registration(user, None, request=request._request)
                else:
                    # Portal provisioning always requires verified ownership of the email,
                    # even on deployments that let generic accounts skip confirmation.
                    user.is_active = False
                    user.save(update_fields=['is_active'])
                    UserService.send_verification_email(user, request._request)
        except IntegrityError as exc:
            raise PortalAPIError(
                'email_already_registered',
                'This email already has an account. Sign in to continue.',
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        except Exception as exc:
            raise PortalAPIError(
                'verification_email_failed',
                'The verification email could not be sent. Try again later.',
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        return Response(
            {'verification_required': True},
            status=status.HTTP_201_CREATED,
        )


class PortalVerifyEmailView(PortalAPIView):
    throttle_classes = [PortalVerifyEmailThrottle]

    @extend_schema(
        operation_id='brand_portal_v1_verify_email',
        request=PortalVerifyEmailSerializer,
        responses={200: PortalVerifyEmailResultSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def post(self, request):
        serializer = PortalVerifyEmailSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalAPIError('invalid_verification_key', 'The verification key is invalid.')

        key = serializer.validated_data['key']
        try:
            from allauth.account.models import EmailConfirmation, EmailConfirmationHMAC

            confirmation = EmailConfirmationHMAC.from_key(key)
            if confirmation is None:
                confirmation = EmailConfirmation.from_key(key)
        except Exception:
            confirmation = None
        if confirmation is None:
            raise PortalAPIError('invalid_verification_key', 'The verification key is invalid.')

        with transaction.atomic():
            registration = BrandPortalRegistration.objects.select_for_update().filter(
                portal_workspace=request.portal_workspace,
                user=confirmation.email_address.user,
            ).first()
            if registration is None or registration.verified_at is not None:
                raise PortalAPIError(
                    'invalid_verification_key', 'The verification key is invalid.'
                )
            try:
                email_address = UserService.verify_email(key)
            except ValueError as exc:
                raise PortalAPIError(
                    'invalid_verification_key', 'The verification key is invalid.'
                ) from exc
            if email_address.user_id != registration.user_id:
                raise PortalAPIError(
                    'invalid_verification_key', 'The verification key is invalid.'
                )
            registration.verified_at = timezone.now()
            registration.save(update_fields=['verified_at', 'updated_at'])

        from config.onboarding_token import make_onboarding_token

        return Response({'onboarding_token': make_onboarding_token(email_address)})


_DUMMY_PASSWORD_HASH = make_password('brand-portal-invalid-password')


class PortalLoginView(PortalAPIView):
    throttle_classes = [PortalLoginThrottle]

    @extend_schema(
        operation_id='brand_portal_v1_login',
        request=PortalLoginSerializer,
        responses={200: PortalLoginResultSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def post(self, request):
        serializer = PortalLoginSerializer(data=request.data)
        if not serializer.is_valid():
            raise self.invalid_credentials()
        email = serializer.validated_data['email'].strip().lower()
        password = serializer.validated_data['password']
        user = get_user_model().objects.filter(email__iexact=email).first()
        password_valid = (
            user.check_password(password)
            if user is not None
            else check_password(password, _DUMMY_PASSWORD_HASH)
        )
        if not password_valid or user is None or not user.is_active:
            raise self.invalid_credentials()

        from allauth.account.models import EmailAddress

        registration = BrandPortalRegistration.objects.filter(
            portal_workspace=request.portal_workspace,
            user=user,
            verified_at__isnull=False,
        ).first()
        email_verified = EmailAddress.objects.filter(
            user=user, email__iexact=user.email, verified=True
        ).exists()
        if registration is None or not email_verified:
            raise self.invalid_credentials()

        workspaces = portal_workspaces(request.portal_workspace, user)
        result = {
            'session_token': make_portal_session_token(request.portal_workspace, user),
            'expires_in': portal_session_max_age(),
            'workspaces': workspaces,
        }
        # A verified account may lose its setup cookie before creating a tenant.
        # Reissue proof only after password verification and only before the
        # first completed provisioning for this exact portal.
        completed = BrandPortalProvisioning.objects.filter(
            portal_workspace=request.portal_workspace, user=user,
            status=BrandPortalProvisioning.STATUS_COMPLETED,
        ).exists()
        snapshot = profile_snapshot(request.portal_workspace)
        if not workspaces and not completed and snapshot.get('registration_enabled'):
            from config.onboarding_token import make_onboarding_token

            address = EmailAddress.objects.get(user=user, email__iexact=user.email, verified=True)
            result['onboarding_token'] = make_onboarding_token(address)
        return Response(result)

    @staticmethod
    def invalid_credentials():
        return PortalAPIError(
            'invalid_credentials',
            'The email or password is invalid.',
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class PortalSSOStartView(PortalAPIView):
    throttle_classes = [PortalSSOStartThrottle]

    @extend_schema(
        operation_id='brand_portal_v1_sso_start',
        request=PortalSSOStartSerializer,
        responses={200: PortalSSOStartResultSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def post(self, request):
        serializer = PortalSSOStartSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalAPIError('invalid_sso_request', 'The SSO request is invalid.')
        user = user_for_portal_session_token(
            serializer.validated_data['session_token'], request.portal_workspace
        )
        if user is None:
            raise PortalAPIError(
                'invalid_session_token',
                'The portal session is invalid or expired.',
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        attempt = BrandPortalProvisioning.objects.filter(
            portal_workspace=request.portal_workspace,
            user=user,
            status=BrandPortalProvisioning.STATUS_COMPLETED,
            target_workspace__uuid=serializer.validated_data['workspace_uuid'],
            target_workspace__is_active=True,
        ).select_related('target_workspace').first()
        if attempt is None or not StaffMember.all_objects.filter(
            workspace=attempt.target_workspace, user=user, is_active=True
        ).exists():
            raise PortalAPIError(
                'workspace_access_denied',
                'The requested workspace is unavailable.',
                status_code=status.HTTP_403_FORBIDDEN,
            )

        from urllib.parse import urlencode

        try:
            frontend_url = resolve_workspace_public_frontend_base_url(
                attempt.target_workspace
            ).rstrip('/')
        except ValueError as exc:
            raise PortalAPIError(
                'workspace_domain_unavailable',
                'The requested workspace is unavailable.',
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        client_ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        client_ip = client_ip or request.META.get('REMOTE_ADDR') or None
        try:
            client_ip = str(ip_address(client_ip)) if client_ip else None
        except ValueError:
            client_ip = None
        sso_code = PlatformSSOCode.objects.create(
            workspace=attempt.target_workspace,
            user=user,
            next_url='/admin',
            redirect_domain=frontend_url,
            created_by_ip=client_ip,
        )
        redirect_url = f'{frontend_url}/auth/sso?{urlencode({"code": sso_code.code})}'
        return Response({'redirect_url': redirect_url, 'expires_at': sso_code.expires_at})


class PortalFinalizeView(PortalAPIView):
    throttle_classes = [PortalFinalizeThrottle]

    @extend_schema(
        operation_id='brand_portal_v1_finalize',
        request=PortalFinalizeSerializer,
        parameters=[
            OpenApiParameter(
                name='Idempotency-Key',
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Retry identity, unique within this portal workspace.',
            )
        ],
        responses={200: PortalProvisioningResultSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def post(self, request):
        serializer = PortalFinalizeSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalAPIError('invalid_finalize_request', 'Finalize data is invalid.')

        from config.onboarding_token import user_for_onboarding_token
        from config.serializers import FinalizeOnboardingSerializer

        user = user_for_onboarding_token(serializer.validated_data['onboarding_token'])
        proof = FinalizeOnboardingSerializer(
            data={
                'onboarding_token': serializer.validated_data['onboarding_token'],
                'store_name': serializer.validated_data['workspace_name'],
            }
        )
        proof.is_valid(raise_exception=True)
        if not proof.may_finalize(user, signed_in=False):
            raise PortalAPIError(
                'onboarding_proof_required',
                'A verified email proof is required.',
                status_code=status.HTTP_403_FORBIDDEN,
            )
        if not BrandPortalRegistration.objects.filter(
            portal_workspace=request.portal_workspace,
            user=user,
            verified_at__isnull=False,
        ).exists():
            raise PortalAPIError(
                'onboarding_proof_required',
                'A verified email proof is required.',
                status_code=status.HTTP_403_FORBIDDEN,
            )
        try:
            attempt, created = provision_workspace_from_portal(
                request.portal_workspace,
                user,
                idempotency_key=request.headers.get('Idempotency-Key', ''),
                name=serializer.validated_data['workspace_name'],
                admin_name=serializer.validated_data.get('admin_name', ''),
            )
        except PortalProvisioningError as exc:
            raise PortalAPIError(
                exc.code, exc.detail, status_code=exc.status_code
            ) from exc
        return Response(provisioning_response(attempt, created=created))


class PortalPageView(PortalAPIView):
    @extend_schema(
        operation_id='brand_portal_v1_page',
        parameters=[LANGUAGE_PARAMETER],
        responses={200: PortalPageSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def get(self, request, slug):
        try:
            page = PageService(
                workspace=request.portal_workspace, user=request.user
            ).get_rendered_page(slug, self.get_language(request), request=request)
        except PageNotFound:
            self.content_not_found()
        page.pop('id', None)
        return Response(page)


class PortalPostView(PortalAPIView):
    @extend_schema(
        operation_id='brand_portal_v1_post',
        parameters=[LANGUAGE_PARAMETER],
        responses={200: PortalPostSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def get(self, request, slug):
        try:
            post = PostService(
                workspace=request.portal_workspace, user=request.user
            ).get_rendered_post(slug, self.get_language(request))
        except PostNotFound:
            self.content_not_found()
        post.pop('id', None)
        return Response(post)


class PortalMenuView(PortalAPIView):
    @extend_schema(
        operation_id='brand_portal_v1_menu',
        parameters=[LANGUAGE_PARAMETER],
        responses={200: PortalMenuSerializer, **ERROR_RESPONSES},
        tags=['Brand portal BFF'],
    )
    def get(self, request, slug):
        language = self.get_language(request)
        menu = self._find_menu(request.portal_workspace, slug, language)
        if menu is None:
            self.content_not_found()
        return Response(
            {
                'name': menu.name,
                'slug': menu.slug,
                'location': menu.location,
                'language': menu.language,
                'items': self._public_items(menu),
            }
        )

    @staticmethod
    def _find_menu(workspace, slug, language):
        languages = []
        for candidate in (language, 'en', 'zh-hans', 'zh'):
            if candidate not in languages:
                languages.append(candidate)
        menus = Menu.objects.filter(workspace=workspace, slug=slug, is_active=True)
        for candidate in languages:
            menu = menus.filter(language=candidate).first()
            if menu is not None:
                return menu
        return menus.order_by('language', 'id').first()

    @staticmethod
    def _public_items(menu):
        items = list(
            menu.items.filter(is_active=True)
            .select_related('page', 'post')
            .order_by('order', 'title', 'id')
        )
        now = timezone.now()

        def is_public(item):
            if item.page_id and item.page.status != 'published':
                return False
            if item.post_id and (
                item.post.status != 'published'
                or not item.post.published_at
                or item.post.published_at > now
            ):
                return False
            return True

        public_items = [item for item in items if is_public(item)]
        children = {}
        for item in public_items:
            children.setdefault(item.parent_id, []).append(item)

        def serialize(item):
            return {
                'title': item.title,
                'url': item.url,
                'icon': item.icon,
                'css_class': item.css_class,
                'open_in_new_tab': item.open_in_new_tab,
                'children': [serialize(child) for child in children.get(item.id, [])],
            }

        return [serialize(item) for item in children.get(None, [])]
