# -*- coding: utf-8 -*-
from urllib.parse import urlencode, urlsplit

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone

from bfg.common.extensions import ACTIVATION_SYSTEM
from bfg.common.extensions import services as extension_services
from bfg.common.extensions.storefront_skins import validate_storefront_skin
from bfg.common.middleware import get_current_workspace, set_current_workspace
from bfg.common.models import resolve_workspace_public_frontend_base_url
from bfg.common.onboarding import provisioning
from bfg.common.services.workspace_service import WorkspaceService
from bfg.common.storefront_cache import invalidate_storefront_config_cache
from bfg.inbox.notification_templates import ensure_notification_templates
from bfg.platform.services import entitlements
from bfg.platform.services.ownership import owned_workspace_ids
from bfg.platform.services.workspace_creation import max_owned_workspaces, unique_workspace_slug
from bfg.platform.services.workspace_service import is_platform_admin

from .models import BrandPortalProfile, BrandPortalProvisioning, BrandPortalRegistration

PORTAL_SESSION_SALT = 'apps.brand_portal.session'
DEFAULT_PORTAL_SESSION_MAX_AGE = 15 * 60

PROFILE_FIELDS = (
    'registration_enabled',
    'provisioning_extensions',
    'default_theme',
    'default_plan',
    'default_country',
    'default_currency',
    'default_language',
)


def normalize_callback_origin(value):
    """Validate and normalize a server-supplied frontend origin."""
    value = (value or '').strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PortalProvisioningError(
            'invalid_callback_origin', 'A valid portal callback origin is required.'
        ) from exc
    hostname = (parsed.hostname or '').lower()
    if (
        parsed.scheme not in {'http', 'https'}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise PortalProvisioningError(
            'invalid_callback_origin', 'A valid portal callback origin is required.'
        )
    try:
        URLValidator(schemes=['http', 'https'])(value)
    except ValidationError as exc:
        raise PortalProvisioningError(
            'invalid_callback_origin', 'A valid portal callback origin is required.'
        ) from exc
    local_hosts = {'localhost', '127.0.0.1', '::1'}
    if parsed.scheme != 'https' and hostname not in local_hosts and not hostname.endswith('.localhost'):
        raise PortalProvisioningError(
            'invalid_callback_origin', 'Portal callback origins must use HTTPS.'
        )
    host = f'[{hostname}]' if ':' in hostname else hostname
    if port is not None:
        host = f'{host}:{port}'
    return f'{parsed.scheme}://{host}'


def portal_session_max_age():
    from django.conf import settings

    return int(
        getattr(settings, 'BRAND_PORTAL_SESSION_TOKEN_MAX_AGE', DEFAULT_PORTAL_SESSION_MAX_AGE)
    )


def make_portal_session_token(portal_workspace, user):
    return signing.dumps(
        {'portal_workspace': portal_workspace.pk, 'user': user.pk},
        salt=PORTAL_SESSION_SALT,
        compress=True,
    )


def user_for_portal_session_token(token, portal_workspace):
    try:
        claims = signing.loads(
            token,
            salt=PORTAL_SESSION_SALT,
            max_age=portal_session_max_age(),
        )
    except signing.BadSignature:
        return None
    if claims.get('portal_workspace') != portal_workspace.pk:
        return None
    user = get_user_model().objects.filter(pk=claims.get('user'), is_active=True).first()
    if user is None:
        return None
    if not BrandPortalRegistration.objects.filter(
        portal_workspace=portal_workspace,
        user=user,
        verified_at__isnull=False,
    ).exists():
        return None
    return user


def portal_workspaces(portal_workspace, user):
    """Return active workspaces provisioned by this portal and still accessible."""
    StaffMember = apps.get_model('common', 'StaffMember')
    active_ids = StaffMember.all_objects.filter(
        user=user, is_active=True, workspace__is_active=True
    ).values_list('workspace_id', flat=True)
    attempts = (
        BrandPortalProvisioning.objects.filter(
            portal_workspace=portal_workspace,
            user=user,
            status=BrandPortalProvisioning.STATUS_COMPLETED,
            target_workspace_id__in=active_ids,
        )
        .exclude(target_workspace=None)
        .select_related('target_workspace')
    )
    results = []
    for attempt in attempts:
        workspace = attempt.target_workspace
        try:
            frontend_url = resolve_workspace_public_frontend_base_url(workspace).rstrip('/')
        except ValueError:
            continue
        results.append(
            {
                'uuid': str(workspace.uuid),
                'name': workspace.name,
                'slug': workspace.slug,
                'frontend_url': frontend_url,
            }
        )
    return results


def profile_cache_key(workspace_id):
    return f'brand_portal:profile:{workspace_id}'


def invalidate_profile_cache(workspace_id):
    cache.delete(profile_cache_key(workspace_id))


def profile_snapshot(workspace):
    """Return the current public runtime profile as a cacheable dictionary."""
    key = profile_cache_key(workspace.pk)
    cached = cache.get(key)
    if cached is not None:
        return dict(cached)
    profile = BrandPortalProfile.objects.filter(workspace=workspace).first()
    if profile is None:
        snapshot = {'configured': False, 'registration_enabled': False}
    else:
        snapshot = {
            'configured': True,
            'public_id': str(profile.public_id),
            **{field: getattr(profile, field) for field in PROFILE_FIELDS},
        }
    cache.set(key, snapshot, timeout=300)
    return dict(snapshot)


@transaction.atomic
def save_profile(workspace, values, *, actor):
    """Create or update a portal profile as a platform administrator."""
    if not is_platform_admin(actor):
        raise PermissionDenied('Only a platform administrator may change a brand portal profile.')
    profile, created = BrandPortalProfile.objects.select_for_update().get_or_create(
        workspace=workspace,
        defaults={'created_by': actor, 'updated_by': actor},
    )
    for field in PROFILE_FIELDS:
        if field in values:
            setattr(profile, field, values[field])
    if created:
        profile.created_by = actor
    profile.updated_by = actor
    profile.full_clean()
    profile.save()
    return profile


class PortalProvisioningError(Exception):
    """A safe, stable provisioning failure that may be returned to the BFF."""

    def __init__(self, code, detail, *, status_code=400):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def _new_profile_snapshot(portal_workspace):
    profile = (
        BrandPortalProfile.objects.select_for_update()
        .filter(workspace=portal_workspace)
        .first()
    )
    if profile is None or not profile.registration_enabled:
        raise PortalProvisioningError(
            'registration_disabled', 'Registration is not available.', status_code=403
        )
    profile.full_clean()
    return {
        'portal_id': str(profile.public_id),
        **{field: getattr(profile, field) for field in PROFILE_FIELDS},
    }


def _get_or_create_attempt(
    portal_workspace, user, idempotency_key, *, name, admin_name
):
    idempotency_key = (idempotency_key or '').strip()
    if not idempotency_key or len(idempotency_key) > 128:
        raise PortalProvisioningError(
            'invalid_idempotency_key', 'A valid Idempotency-Key header is required.'
        )
    try:
        with transaction.atomic():
            attempt = BrandPortalProvisioning.objects.select_for_update().filter(
                portal_workspace=portal_workspace,
                idempotency_key=idempotency_key,
            ).first()
            if attempt is None:
                snapshot = _new_profile_snapshot(portal_workspace)
                snapshot['request'] = {
                    'workspace_name': name,
                    'admin_name': admin_name,
                }
                attempt = BrandPortalProvisioning.objects.create(
                    portal_workspace=portal_workspace,
                    user=user,
                    idempotency_key=idempotency_key,
                    profile_snapshot=snapshot,
                )
    except IntegrityError:
        attempt = BrandPortalProvisioning.objects.get(
            portal_workspace=portal_workspace,
            idempotency_key=idempotency_key,
        )
    if attempt.user_id != user.pk:
        raise PortalProvisioningError(
            'idempotency_conflict',
            'This Idempotency-Key was used for another account.',
            status_code=409,
        )
    return attempt


def _portal_cluster(portal_workspace):
    try:
        return portal_workspace.platform_profile.cluster
    except (AttributeError, apps.get_model('platform', 'WorkspacePlatformProfile').DoesNotExist):
        return None


def _apply_theme(settings_obj, theme, *, extension_keys):
    try:
        theme = validate_storefront_skin(theme, extension_keys=extension_keys)
    except ValueError as exc:
        raise PortalProvisioningError(
            'invalid_default_theme',
            'The configured storefront theme is unavailable.',
        ) from exc
    if not theme:
        return
    custom_settings = dict(settings_obj.custom_settings or {})
    storefront_ui = dict(custom_settings.get('storefront_ui') or {})
    storefront_ui['theme'] = theme
    custom_settings['storefront_ui'] = storefront_ui
    settings_obj.custom_settings = custom_settings
    settings_obj.save(update_fields=['custom_settings', 'updated_at'])
    transaction.on_commit(
        lambda: invalidate_storefront_config_cache(settings_obj.workspace_id)
    )


def _provision_baseline(workspace, user, name, snapshot):
    previous = get_current_workspace()
    set_current_workspace(workspace)
    try:
        settings_obj, _ = provisioning.ensure_settings(
            workspace,
            country=snapshot.get('default_country', ''),
            currency=snapshot.get('default_currency', ''),
            language=snapshot.get('default_language', ''),
            site_name=name,
        )
        provisioning.ensure_currency(settings_obj.default_currency)
        provisioning.ensure_store(workspace)
        templates = ensure_notification_templates(
            workspace,
            language=settings_obj.default_language,
            currency=settings_obj.default_currency,
        )
        for key in snapshot.get('provisioning_extensions', []):
            if not entitlements.is_entitled(workspace, key):
                entitlements.grant(
                    workspace,
                    key,
                    reason=f'Included by brand portal {snapshot["portal_id"]}.',
                )
            extension_services.activate(
                workspace, key, user=user, actor=ACTIVATION_SYSTEM
            )
        # An explicitly configured portal skin wins over an extension default.
        # A blank profile value leaves the first activated extension free to
        # provide its non-destructive default.
        _apply_theme(
            settings_obj,
            snapshot.get('default_theme', ''),
            extension_keys=snapshot.get('provisioning_extensions', []),
        )
    finally:
        set_current_workspace(previous)

    WorkspaceOperation = apps.get_model('platform', 'WorkspaceOperation')
    WorkspaceOperation.objects.create(
        workspace=workspace,
        operation='create',
        status='completed',
        initiated_by=user,
        details={
            'embedded': True,
            'source': 'brand_portal',
            'portal_id': snapshot['portal_id'],
            'plan': snapshot.get('default_plan', ''),
            'extensions': list(snapshot.get('provisioning_extensions', [])),
            'notification_templates': templates['created'],
        },
        completed_at=timezone.now(),
    )


def _update_admin_name(user, admin_name):
    admin_name = (admin_name or '').strip()
    if not admin_name:
        return
    parts = admin_name.split()
    values = {'first_name': parts[0], 'last_name': ' '.join(parts[1:])}
    changed = []
    for field, value in values.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    if changed:
        user.save(update_fields=changed)


def _execute_attempt(attempt_id, user):
    with transaction.atomic():
        attempt = BrandPortalProvisioning.objects.select_for_update().select_related(
            'target_workspace', 'sso_code'
        ).get(pk=attempt_id)
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if attempt.status == BrandPortalProvisioning.STATUS_COMPLETED:
            return attempt, False
        if len(owned_workspace_ids(locked_user)) >= max_owned_workspaces():
            raise PortalProvisioningError(
                'workspace_limit_reached',
                f'An account can own at most {max_owned_workspaces()} workspaces.',
                status_code=409,
            )

        attempt.status = BrandPortalProvisioning.STATUS_PROVISIONING
        attempt.error_code = ''
        attempt.error_detail = ''
        attempt.save(update_fields=['status', 'error_code', 'error_detail', 'updated_at'])
        request_snapshot = attempt.profile_snapshot.get('request', {})
        name = request_snapshot.get('workspace_name', '')
        admin_name = request_snapshot.get('admin_name', '')
        if not name:
            raise PortalProvisioningError(
                'invalid_profile_snapshot', 'The provisioning request snapshot is invalid.'
            )
        _update_admin_name(locked_user, admin_name)

        workspace = WorkspaceService(user=locked_user).create_workspace(
            name=name,
            slug=unique_workspace_slug(name),
            owner_user=locked_user,
            cluster=_portal_cluster(attempt.portal_workspace),
        )
        _provision_baseline(workspace, locked_user, name, attempt.profile_snapshot)
        try:
            frontend_url = resolve_workspace_public_frontend_base_url(workspace).rstrip('/')
        except ValueError as exc:
            raise PortalProvisioningError(
                'workspace_domain_unavailable',
                'The new workspace has no platform frontend domain configured.',
            ) from exc

        PlatformSSOCode = apps.get_model('platform', 'PlatformSSOCode')
        sso_code = PlatformSSOCode.objects.create(
            workspace=workspace,
            user=locked_user,
            next_url='/admin',
            redirect_domain=frontend_url,
        )
        attempt.target_workspace = workspace
        attempt.sso_code = sso_code
        attempt.status = BrandPortalProvisioning.STATUS_COMPLETED
        attempt.completed_at = timezone.now()
        attempt.save(
            update_fields=[
                'target_workspace', 'sso_code', 'status', 'completed_at', 'updated_at'
            ]
        )
        return attempt, True


def _mark_failed(attempt_id, error):
    with transaction.atomic():
        attempt = BrandPortalProvisioning.objects.select_for_update().get(pk=attempt_id)
        if attempt.status == BrandPortalProvisioning.STATUS_COMPLETED:
            return
        attempt.status = BrandPortalProvisioning.STATUS_FAILED
        attempt.target_workspace = None
        attempt.sso_code = None
        attempt.completed_at = None
        attempt.error_code = error.code
        attempt.error_detail = error.detail
        attempt.save(
            update_fields=[
                'status', 'target_workspace', 'sso_code', 'completed_at',
                'error_code', 'error_detail', 'updated_at',
            ]
        )


def provision_workspace_from_portal(
    portal_workspace, user, *, idempotency_key, name, admin_name=''
):
    """Create one workspace from an immutable portal profile snapshot."""
    attempt = _get_or_create_attempt(
        portal_workspace,
        user,
        idempotency_key,
        name=name,
        admin_name=admin_name,
    )
    try:
        return _execute_attempt(attempt.pk, user)
    except PortalProvisioningError as exc:
        _mark_failed(attempt.pk, exc)
        raise
    except extension_services.ExtensionError as exc:
        safe = PortalProvisioningError(
            'extension_activation_failed',
            'A configured workspace extension could not be activated.',
        )
        _mark_failed(attempt.pk, safe)
        raise safe from exc
    except Exception as exc:
        safe = PortalProvisioningError(
            'provisioning_failed', 'The workspace could not be created.'
        )
        _mark_failed(attempt.pk, safe)
        raise safe from exc


def provisioning_response(attempt, *, created):
    workspace = attempt.target_workspace
    sso_code = attempt.sso_code
    redirect_url = f'{sso_code.redirect_domain}/auth/sso?{urlencode({"code": sso_code.code})}'
    return {
        'created': created,
        'workspace': {
            'uuid': str(workspace.uuid),
            'name': workspace.name,
            'slug': workspace.slug,
            'frontend_url': sso_code.redirect_domain,
        },
        'extensions': list(attempt.profile_snapshot.get('provisioning_extensions', [])),
        'redirect_url': redirect_url,
        'sso_expires_at': sso_code.expires_at,
    }
