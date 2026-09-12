# -*- coding: utf-8 -*-
"""
Custom views for API
"""

import os
import hmac
import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.conf import settings
from django.http import HttpResponse
from .authentication import OptionalBearerTokenAuthentication
from .onboarding_token import make_onboarding_token, user_for_onboarding_token
from .serializers import (
    RegisterSerializer,
    FinalizeOnboardingSerializer,
    ForgotPasswordSerializer,
    ResetPasswordConfirmSerializer,
    VerifyEmailSerializer,
    CustomTokenObtainPairSerializer,
)
from .version_info import get_server_version_payload

User = get_user_model()
logger = logging.getLogger(__name__)

# finalize-onboarding gives this one answer to every caller who fails to prove
# who they are, so it says nothing about which email addresses have accounts.
ONBOARDING_PROOF_REQUIRED = (
    'Unable to finalize onboarding. Open the latest confirmation email, '
    'or sign in, and try again.'
)


def _platform_api_key_rejection(request, view_name):
    """Return a 403 response unless the request presents PLATFORM_API_KEY, else None.

    An unset key refuses every call instead of skipping the check: these
    endpoints mint JWTs and staff memberships for whatever email they are given.
    """
    expected = getattr(settings, 'PLATFORM_API_KEY', '') or ''
    presented = request.headers.get('Authorization') or ''
    if expected and hmac.compare_digest(presented.encode(), f'Bearer {expected}'.encode()):
        return None
    if expected:
        logger.warning('%s: invalid or missing Platform API Key', view_name)
    else:
        logger.error('%s: PLATFORM_API_KEY is not configured, refusing the call', view_name)
    return Response({'detail': 'Invalid Platform API Key'}, status=status.HTTP_403_FORBIDDEN)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def server_version(request):
    """
    GET /api/v1/system/version/
    Public metadata: API line, OpenAPI schema version, BFG library version, workspace server app
    version, Django local extension apps (id + optional __version__), optional build id.
    """
    return Response(get_server_version_payload())


@api_view(['POST'])
@authentication_classes([])  # Skip JWT auth — we verify PLATFORM_API_KEY manually
@permission_classes([AllowAny])
def provision_user(request):
    """
    POST /internal/auth/provision-user/
    Called by Platform Server (via Token Exchange) to sync a user and get a Workspace JWT.
    Headers: { "Authorization": "Bearer <PLATFORM_API_KEY>" }
    Body: { "platform_user_id", "email", "name", "role" }
    """
    rejection = _platform_api_key_rejection(request, 'provision_user')
    if rejection is not None:
        return rejection

    data = request.data
    platform_user_id = data.get("platform_user_id")
    email = data.get("email")
    
    if not email and not platform_user_id:
        return Response({"detail": "Email or Platform User ID is required"}, status=status.HTTP_400_BAD_REQUEST)

    name = data.get("name", "")
    role_code = data.get("role", "staff")
    workspace_uuid = data.get("workspace_uuid")
    workspace_slug = data.get("workspace_slug")

    try:
        from bfg.common.services import UserService
        user, _ = UserService.provision_sso_user(
            platform_user_id=platform_user_id,
            email=email,
            name=name,
            role_code=role_code,
            workspace_uuid=workspace_uuid,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to provision user: {e}")
        return Response({"detail": f"User provisioning failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Ensure StaffMember for the specific workspace (by slug) and return its local id
    workspace_id = None
    if workspace_slug:
        try:
            from bfg.common.models import Workspace, StaffMember, StaffRole
            ws = Workspace.objects.filter(slug=workspace_slug).first()
            if ws:
                workspace_id = ws.id
                role, _ = StaffRole.objects.get_or_create(
                    workspace=ws, code=role_code,
                    defaults={'name': role_code.title(), 'permissions': {}}
                )
                StaffMember.objects.get_or_create(
                    user=user, workspace=ws,
                    defaults={"role": role}
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"workspace StaffMember ensure failed slug={workspace_slug}: {e}"
            )

    # Generate Workspace JWT
    refresh = RefreshToken.for_user(user)

    return Response({
        "token": str(refresh.access_token),
        "refresh": str(refresh),
        "workspace_id": workspace_id,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([])  # Skip JWT auth — we verify PLATFORM_API_KEY manually
@permission_classes([AllowAny])
def provision_workspace(request):
    """
    POST /api/v1/internal/auth/provision-workspace/
    Called by Platform Server during registration to create a real business workspace.
    Headers: { "Authorization": "Bearer <PLATFORM_API_KEY>" }
    Body: { "platform_user_id", "email", "name", "workspace_name", "workspace_slug" }
    """
    rejection = _platform_api_key_rejection(request, 'provision_workspace')
    if rejection is not None:
        return rejection

    data = request.data
    platform_user_id = data.get("platform_user_id")
    email = data.get("email")

    if not email and not platform_user_id:
        return Response(
            {"detail": "Email or Platform User ID is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Step 1: Provision user locally
        from bfg.common.services import UserService
        user, _ = UserService.provision_sso_user(
            platform_user_id=platform_user_id,
            email=email,
            name=data.get("name", ""),
            role_code="admin",  # Owner of new workspace gets admin
        )

        # Step 2: Create the business workspace locally
        from bfg.common.services.workspace_service import WorkspaceService
        ws_service = WorkspaceService()
        workspace = ws_service.create_workspace(
            name=data.get("workspace_name", "My Workspace"),
            slug=data.get("workspace_slug"),
            owner_user=user,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to provision workspace: {e}")
        return Response(
            {"detail": f"Workspace provisioning failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response({
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "workspace_uuid": str(workspace.uuid),
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    User registration endpoint
    POST /api/v1/auth/register/
    
    Body:
    {
        "email": "user@example.com",
        "password": "password123",
        "password_confirm": "password123",
        "first_name": "John",
        "last_name": "Doe"
    }
    """
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        # If the registration is part of accepting an invitation, validate
        # the token *before* creating the user so we don't leave orphans.
        invite_token = request.data.get('invite_token') or ''
        invite_uuid = request.data.get('invite_uuid') or ''
        pending_invitation = None
        if invite_token:
            from bfg.common.services import find_invitation_by_token
            try:
                pending_invitation = find_invitation_by_token(invite_token, invite_uuid)
            except Exception as exc:  # noqa: BLE001
                detail = getattr(exc, 'detail', None) or str(exc)
                return Response({'invite_token': detail}, status=status.HTTP_400_BAD_REQUEST)
            if pending_invitation.email.lower() != serializer.validated_data['email'].lower():
                return Response({
                    'email': (
                        'Please register with the email address the invitation '
                        f'was sent to ({pending_invitation.email}).'
                    ),
                }, status=status.HTTP_400_BAD_REQUEST)

        from django.db import transaction
        from bfg.common.exceptions import VerificationEmailNotSent
        from bfg.common.services import UserService

        try:
            # One transaction, so a sign-up whose confirmation mail fails keeps nothing: the
            # account could never be activated, and its address could not sign up again.
            with transaction.atomic():
                user = serializer.save()

                store_name = getattr(user, '_temporary_store_name', None)
                # Don't auto-provision a fresh workspace if the user is joining one via invite.
                if pending_invitation:
                    workspace, workspace_error = None, None
                else:
                    workspace, workspace_error = UserService.process_registration(
                        user, store_name, request=request._request,
                    )
        except VerificationEmailNotSent:
            logger.exception("Sign-up rolled back: the confirmation email could not be sent")
            return Response({
                'detail': 'We could not send your confirmation email. Please try again in a few minutes.',
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        accepted_invitation = None
        if pending_invitation:
            from bfg.common.services import accept_invitation
            try:
                accept_invitation(pending_invitation, user)
                accepted_invitation = pending_invitation
                workspace = pending_invitation.workspace
            except Exception:  # noqa: BLE001
                logger.exception("Failed to auto-accept invitation during register")

        response_data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'email_verification_required': not user.is_active,
        }

        # Generate JWT token for the new user, unless the account waits on its
        # confirmation mail. Anyone can register any address, and tokens issued
        # now would come alive when the address's owner confirms it, in the
        # hands of whoever registered. Once confirmed, verify-email's onboarding
        # token or a password sign-in gets the owner their tokens.
        # Use CustomTokenObtainPairSerializer.get_token so the access token
        # carries the workspace_id claim required by WorkspaceMiddleware —
        # without it, /me/ and other workspace-scoped endpoints can't resolve
        # the user's workspace and the frontend gets bounced back to login.
        if user.is_active:
            from .serializers import CustomTokenObtainPairSerializer
            refresh = CustomTokenObtainPairSerializer.get_token(user)
            response_data['access'] = str(refresh.access_token)
            response_data['refresh'] = str(refresh)

        if workspace:
            response_data['workspace'] = {
                'id': workspace.id,
                'name': workspace.name,
                'slug': workspace.slug,
            }
        elif workspace_error:
            response_data['workspace_warning'] = workspace_error

        if accepted_invitation:
            response_data['invitation_accepted'] = True

        return Response(response_data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([OptionalBearerTokenAuthentication])  # a JWT is the only sign-in that counts here
@permission_classes([AllowAny])
def finalize_onboarding(request):
    """
    Finalize deferred onboarding after email verification.
    POST /api/v1/auth/finalize-onboarding/

    An email address is not proof, so the caller must show who they are: the
    ``onboarding_token`` verify-email returned, or a Bearer token for that
    user. A Bearer token that fails to authenticate counts as no sign-in, so a
    stale one a client still holds does not void the onboarding token sent
    with it. Every caller who cannot prove who they are gets the same 403,
    whether or not the address has an account; ``email`` is optional and must
    match. An account that already has a workspace gets tokens only when
    signed in.

    Body:
    {
        "onboarding_token": "<from verify-email, unless signed in>",
        "email": "user@example.com",
        "store_name": "Acme Store",
        "admin_name": "Jane Doe"
    }
    """
    serializer = FinalizeOnboardingSerializer(data=request.data)
    if serializer.is_valid():
        signed_in = request.user.is_authenticated
        if signed_in:
            user = request.user
        else:
            user = user_for_onboarding_token(serializer.validated_data.get('onboarding_token'))
        if not serializer.may_finalize(user, signed_in):
            return Response({'detail': ONBOARDING_PROOF_REQUIRED}, status=status.HTTP_403_FORBIDDEN)

        from bfg.common.models import StaffMember
        # all_objects: no workspace is bound on this public path, so the scoped manager is always empty.
        # A removed membership, or one in a deactivated workspace, is not a workspace of the user's own.
        if not signed_in and StaffMember.all_objects.filter(
            user=user, is_active=True, workspace__is_active=True,
        ).exists():
            return Response({
                'detail': 'This account already has a workspace. Sign in to continue.',
                'code': 'already_onboarded',
            }, status=status.HTTP_409_CONFLICT)

        try:
            user, workspace, created = serializer.save(user)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception("Failed to finalize onboarding")
            return Response({
                'detail': 'Unable to finalize onboarding at this time.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # get_token embeds the workspace_id claim WorkspaceMiddleware reads, as register does.
        refresh = CustomTokenObtainPairSerializer.get_token(user)
        response_data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'workspace': {
                'id': workspace.id,
                'name': workspace.name,
                'slug': workspace.slug,
            },
            'created': created,
        }

        # Public frontend URL of the (possibly just-provisioned) workspace, so the
        # onboarding client can hand the user off to their own tenant subdomain.
        try:
            from bfg.common.models.workspace_domain import resolve_workspace_public_frontend_base_url
            frontend_url = resolve_workspace_public_frontend_base_url(workspace)
        except Exception:
            frontend_url = ''
        response_data['workspace']['frontend_url'] = frontend_url

        return Response(response_data, status=status.HTTP_200_OK)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    Forgot password endpoint - sends password reset email
    POST /api/v1/auth/forgot-password/
    
    Body:
    {
        "email": "user@example.com"
    }
    """
    serializer = ForgotPasswordSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        
        try:
            from django.conf import settings
            from bfg.common.services import UserService
            frontend_url = getattr(settings, 'FRONTEND_URL', '')
            UserService.request_password_reset(email, frontend_url)
        except Exception:
            pass
        
        # Return success without revealing if email exists
        return Response({
            'detail': 'If the email exists, a password reset link has been sent to your email address.'
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_confirm(request):
    """
    Password reset confirmation endpoint
    POST /api/v1/auth/reset-password-confirm/
    
    Body:
    {
        "uid": "base64_encoded_user_id",
        "token": "password_reset_token",
        "new_password": "newpassword123",
        "new_password_confirm": "newpassword123"
    }
    """
    serializer = ResetPasswordConfirmSerializer(data=request.data)
    if serializer.is_valid():
        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']
        
        try:
            from bfg.common.services import UserService
            UserService.reset_password(uid, token, new_password)
        except ValueError as e:
            return Response({
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({
            'detail': 'Password has been reset successfully.'
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    """
    Email verification endpoint
    POST /api/v1/auth/verify-email/
    
    Body:
    {
        "key": "verification_key"
    }
    
    Note: This is a simplified version. In production, you might want to use
    django-allauth's email verification system.
    """
    serializer = VerifyEmailSerializer(data=request.data)
    if serializer.is_valid():
        key = serializer.validated_data['key']
        
        try:
            from bfg.common.services import UserService
            email_address = UserService.verify_email(key)
        except ValueError as e:
            return Response({
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({
            'detail': 'Email verified successfully.',
            # finalize-onboarding takes this in place of an email address it cannot trust.
            'onboarding_token': make_onboarding_token(email_address),
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def acme_challenge(request, path):
    """
    Serve ACME challenge responses for Let's Encrypt.
    Looks for files in settings.BASE_DIR/.well-known/acme-challenge/
    Also supports setting token/response via environment variables.
    """
    challenge_dir = os.path.join(settings.BASE_DIR, '.well-known', 'acme-challenge')
    file_path = os.path.join(challenge_dir, path)

    # Security: check that the file is indeed within the challenge_dir
    if not os.path.abspath(file_path).startswith(os.path.abspath(challenge_dir)):
        return HttpResponse("Forbidden", status=403)

    if os.path.exists(file_path) and os.path.isfile(file_path):
        with open(file_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='text/plain')

    # Fallback: support via environment variables
    acme_token = os.environ.get('ACME_CHALLENGE_TOKEN')
    acme_response = os.environ.get('ACME_CHALLENGE_RESPONSE')

    if acme_token and acme_response and path == acme_token:
        return HttpResponse(acme_response, content_type='text/plain')

    return HttpResponse("Not Found", status=404)
