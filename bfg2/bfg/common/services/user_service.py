# -*- coding: utf-8 -*-
from django.contrib.auth import get_user_model
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


class UserService:
    """
    Handle user identity, provisioning, and synchronization.
    """

    @classmethod
    def provision_sso_user(
        cls,
        platform_user_id: str,
        email: str,
        name: str,
        role_code: str = 'staff',
        workspace_uuid: str = None,
    ) -> Tuple[object, bool]:
        """
        Provision or synchronize an SSO user locally from Platform details.
        Assigns the user to the active workspace with the provided role.
        
        Returns:
            Tuple[User, bool]: The user instance and a boolean indicating if created.
        """
        User = get_user_model()
        first_name = name.split(" ")[0] if name else ""
        last_name = " ".join(name.split(" ")[1:]) if name and " " in name else ""

        user = None
        created = False
        
        # 1. Try to find by platform_user_id
        if platform_user_id:
            user = User.objects.filter(platform_user_id=platform_user_id).first()
            
        # 2. Try to find by email if not found, and link them
        if not user and email:
            user = User.objects.filter(email=email).first()
            if user and platform_user_id and not user.platform_user_id:
                user.platform_user_id = platform_user_id
                user.save(update_fields=['platform_user_id'])
                
        # 3. Create a new user if still not found
        if not user:
            base_username = email.split("@")[0] if email else f"user_{platform_user_id}"
            user = User.objects.create(
                platform_user_id=platform_user_id,
                email=email or "",
                username=base_username,
                first_name=first_name,
                last_name=last_name,
                is_active=True
            )
            created = True

        if created:
            user.set_unusable_password()
            # Handle duplicate username fallback
            counter = 1
            base_username = user.username
            while User.objects.exclude(id=user.id).filter(username=user.username).exists():
                user.username = f"{base_username}{counter}"
                counter += 1
            user.save()

        # Synchronize StaffMember for target Workspace
        from bfg.common.models import Workspace, StaffRole, StaffMember
        if workspace_uuid:
            workspace = Workspace.objects.filter(uuid=workspace_uuid, is_active=True).first()
        else:
            workspace = Workspace.objects.filter(is_active=True).first()

        if workspace:
            try:
                role = StaffRole.objects.get(workspace=workspace, code=role_code)
            except StaffRole.DoesNotExist:
                role, _ = StaffRole.objects.get_or_create(
                    workspace=workspace, 
                    code='staff', 
                    defaults={'name': 'Staff', 'permissions': {}}
                )

            StaffMember.objects.get_or_create(
                user=user,
                workspace=workspace,
                defaults={"role": role}
            )
            
        return user, created

    @classmethod
    def process_registration(cls, user, store_name: str = None) -> Tuple[object, str]:
        """
        Post-registration logic to auto-provision workspace if needed
        and trigger email verification.

        Branching:
          - BFG_INSTANCE_TYPE=platform: dual-write (Platform DB + Workspace Server API)
          - BFG_INSTANCE_TYPE=workspace: local create only
        Returns (workspace, error_message)
        """
        workspace = None
        workspace_error = None
        
        # Trigger allauth email verification
        try:
            from allauth.account.utils import send_email_confirmation
            from django.http import HttpRequest
            dummy_request = HttpRequest()
            dummy_request.META['SERVER_NAME'] = 'localhost'
            dummy_request.META['SERVER_PORT'] = '80'
            send_email_confirmation(request=dummy_request, user=user, signup=True)
        except Exception as e:
            logger.error(f"Failed to send verification email for {user.email}: {e}")
        
        if store_name:
            from django.conf import settings
            instance_type = getattr(settings, 'BFG_INSTANCE_TYPE', 'workspace')

            if instance_type == 'platform':
                workspace, workspace_error = cls._provision_workspace_remote(user, store_name)
            else:
                workspace, workspace_error = cls._provision_workspace_local(user, store_name)
                
        return workspace, workspace_error

    @classmethod
    def _provision_workspace_remote(cls, user, store_name: str) -> Tuple[object, str]:
        """
        Platform dual-write: create metadata in Platform DB, then call Workspace
        Server API to create the real business workspace.

        Atomicity: if the remote API call fails, the local metadata is rolled back.

        Step 1 (Platform DB):
          - common.Workspace (metadata entry)
          - common.StaffMember (access control)
          - platform.WorkspacePlatformProfile (routing / API keys)

        Step 2 (Workspace Server):
          - POST /api/v1/internal/auth/provision-workspace/
          - Creates local Workspace + User + StaffMember on the Workspace instance
        """
        import requests as http_requests
        from django.conf import settings
        from django.db import transaction
        from django.utils.text import slugify
        from bfg.common.models import Workspace, StaffMember, StaffRole

        slug = slugify(store_name)
        workspace_api_url = getattr(settings, 'WORKSPACE_API_URL', 'http://localhost:8000')
        platform_api_key = getattr(settings, 'PLATFORM_API_KEY', 'local-dev-key')

        try:
            with transaction.atomic():
                # -- Step 1: Platform DB metadata --
                workspace, _ = Workspace.objects.get_or_create(
                    slug=slug,
                    defaults={'name': store_name},
                )
                admin_role, _ = StaffRole.objects.get_or_create(
                    workspace=workspace, code='admin',
                    defaults={'name': 'Administrator', 'permissions': {}},
                )
                StaffMember.objects.get_or_create(
                    user=user, workspace=workspace,
                    defaults={'role': admin_role, 'is_active': True},
                )

                # WorkspacePlatformProfile + PlatformMembership (only when platform extension is installed)
                profile = None
                try:
                    from apps.platform.models import WorkspacePlatformProfile, PlatformMembership
                    profile, _ = WorkspacePlatformProfile.objects.get_or_create(
                        workspace=workspace,
                    )
                    if not profile.platform_api_key:
                        profile.generate_api_keys()
                        profile.save()
                    PlatformMembership.objects.get_or_create(
                        user=user,
                        profile=profile,
                        defaults={'role': 'owner', 'is_active': True},
                    )
                except ImportError:
                    pass

                # -- Step 2: Workspace Server API --
                resp = http_requests.post(
                    f'{workspace_api_url}/api/v1/internal/auth/provision-workspace/',
                    json={
                        'platform_user_id': str(user.id),
                        'email': user.email,
                        'name': user.get_full_name(),
                        'workspace_name': store_name,
                        'workspace_slug': slug,
                    },
                    headers={'Authorization': f'Bearer {platform_api_key}'},
                    timeout=15,
                )
                resp.raise_for_status()

                try:
                    remote_uuid = resp.json().get("workspace_uuid")
                    if remote_uuid and profile:
                        profile.remote_workspace_uuid = remote_uuid
                        profile.save(update_fields=["remote_workspace_uuid"])
                except Exception:
                    pass

            # Both steps succeeded — return the Platform metadata workspace
            return workspace, None

        except Exception as e:
            # transaction.atomic() ensures Step 1 is rolled back if Step 2 fails
            logger.warning(f'Remote workspace provision failed (rolled back): {e}')
            return None, str(e)

    @classmethod
    def _provision_workspace_local(cls, user, store_name: str) -> Tuple[object, str]:
        """Standalone Workspace — create tenant directly in local DB."""
        try:
            from bfg.common.services.workspace_service import WorkspaceService
            ws_service = WorkspaceService()
            workspace = ws_service.create_workspace(name=store_name, owner_user=user)
            return workspace, None
        except Exception as e:
            logger.warning(f'Local workspace provision failed: {e}')
            return None, str(e)

    @classmethod
    def request_password_reset(cls, email: str, frontend_url: str) -> None:
        """
        Process password reset request for a given email.
        """
        from django.contrib.auth import get_user_model
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.conf import settings
        from django.core.mail import send_mail
        
        User = get_user_model()
        try:
            user = User.objects.get(email=email, is_active=True)
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            reset_link = f"{frontend_url}/reset-password?uid={uid}&token={token}"
            
            subject = f"Password reset for {settings.SITE_NAME}"
            message = (
                f"You're receiving this email because you requested a password reset for your account.\n\n"
                f"Please go to the following page and choose a new password:\n{reset_link}\n\n"
                f"If you didn't request this, please ignore this email.\n\n"
                f"Your password won't change until you access the link above and create a new one."
            )
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as e:
            logger.error(f"Failed to process password reset for {email}: {e}")
            pass

    @classmethod
    def reset_password(cls, uid: str, token: str, new_password: str) -> bool:
        """
        Verify the reset token and update the user's password.
        Raises ValueError on invalid token or UID.
        """
        from django.contrib.auth import get_user_model
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str
        
        User = get_user_model()
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise ValueError("Invalid password reset link.")
            
        if not default_token_generator.check_token(user, token):
            raise ValueError("Invalid or expired password reset link.")
            
        user.set_password(new_password)
        user.save()
        return True

    @classmethod
    def verify_email(cls, key: str) -> bool:
        """
        Verify a user's email address by key using django-allauth mechanisms.
        Raises ValueError if key is invalid.
        """
        if not key:
            raise ValueError("Invalid verification key.")
            
        try:
            from allauth.account.models import EmailConfirmationHMAC, EmailConfirmation
            from django.http import HttpRequest
            
            # 1. First try to verify as an HMAC key (stateless)
            confirmation = EmailConfirmationHMAC.from_key(key)
            
            # 2. If not HMAC, try to find a DB-backed key (stateful)
            if not confirmation:
                try:
                    confirmation = EmailConfirmation.objects.get(key=key.lower())
                except EmailConfirmation.DoesNotExist:
                    raise ValueError("Invalid or expired verification key.")
                    
            # Confirm it (marks EmailAddress as verified)
            dummy_request = HttpRequest()
            dummy_request.META['SERVER_NAME'] = 'localhost'
            dummy_request.META['SERVER_PORT'] = '80'
            confirmation.confirm(request=dummy_request)
            return True
            
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            logger.error(f"Error during email verification: {e}")
            raise ValueError("An error occurred during verification.")
