# -*- coding: utf-8 -*-
"""
Creating a workspace through the platform, for the account that will own it.

Who may create one
    An account that owns a workspace or is an active admin of one, whatever
    that workspace's status. Any other account is refused with
    ``workspace_create_forbidden``: having an account is not enough to open
    workspaces with.

How many
    At most ``BFG_MAX_OWNED_WORKSPACES_PER_USER`` (default 3) owned at a time,
    counted by the account's active owner memberships, so suspended and
    inactive workspaces count too. Past that, ``workspace_limit_reached``.

``workspace_create_blocked`` is the one place both rules live. ``me/`` reports
its answer as it stands; ``create_owned_workspace`` asks again with the
account's row locked, so two requests at once cannot both take the last place.

What a create does
    Embedded, the workspace is ready when the request returns: its owner, its
    locale, its currency row, a ``main`` store and its notification templates
    are written in one transaction, and nothing is left to a task, so a broker
    that is down cannot fail a request whose workspace already exists.
    Standalone, the ``provision_workspace`` task still does the rest, since the
    cluster, the API keys and the remote workspace come from there.
"""
import secrets
from typing import Optional

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from bfg.common.exceptions import WorkspaceAlreadyExists
from bfg.core.exceptions import BFGException
from bfg.platform.services.ownership import is_workspace_owner, owned_workspace_ids
from bfg.platform.services.provision_service import provision_workspace
from bfg.platform.utils import is_embedded_mode

DEFAULT_MAX_OWNED_WORKSPACES = 3

CREATE_FORBIDDEN = "workspace_create_forbidden"
LIMIT_REACHED = "workspace_limit_reached"

# Draws of a slug's random part before giving up; each has 65536 values or more.
_SLUG_ATTEMPTS = 20


class WorkspaceCreateForbidden(BFGException):
    """The account may not create workspaces"""
    default_message = "Only the owner or an admin of a workspace can create a workspace."
    default_code = CREATE_FORBIDDEN


class WorkspaceLimitReached(BFGException):
    """The account owns as many workspaces as it may"""
    default_code = LIMIT_REACHED

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"An account can own at most {limit} workspaces.")


def max_owned_workspaces() -> int:
    """How many workspaces one account may own: ``BFG_MAX_OWNED_WORKSPACES_PER_USER``."""
    return int(getattr(settings, "BFG_MAX_OWNED_WORKSPACES_PER_USER", DEFAULT_MAX_OWNED_WORKSPACES))


def workspace_create_blocked(user) -> Optional[str]:
    """``None`` when *user* may create a workspace now, else the code a create request is refused with.

    Takes no lock, so the answer is a report, not a reservation.
    """
    if not getattr(user, "is_authenticated", False):
        return CREATE_FORBIDDEN
    owned = owned_workspace_ids(user)
    if not owned and not _is_workspace_admin(user):
        return CREATE_FORBIDDEN
    if len(owned) >= max_owned_workspaces():
        return LIMIT_REACHED
    return None


def ensure_workspace_create_allowed(user) -> None:
    """Raise the exception for whatever ``workspace_create_blocked`` reports."""
    blocked = workspace_create_blocked(user)
    if blocked == CREATE_FORBIDDEN:
        raise WorkspaceCreateForbidden()
    if blocked == LIMIT_REACHED:
        raise WorkspaceLimitReached(max_owned_workspaces())


def create_owned_workspace(
    user,
    *,
    name: str,
    slug: str = "",
    region: Optional[str] = None,
    country: str = "",
    currency: str = "",
    language: str = "",
    current_workspace_id: Optional[int] = None,
):
    """Create a workspace owned by *user*, who is also made its admin, and return it.

    Raises ``WorkspaceCreateForbidden`` or ``WorkspaceLimitReached`` when *user*
    may not create one, and ``WorkspaceAlreadyExists`` when *slug* is taken. A
    blank *slug* is made from *name*; see ``unique_workspace_slug``.

    Embedded, the workspace is provisioned in the same transaction. *country*,
    *currency* and *language* each fall back to the settings of the workspace
    *current_workspace_id*, when *user* is its active staff or its owner, and
    then to the settings defaults. Standalone, they are not applied: the
    ``provision_workspace`` task is queued once the workspace is committed, as
    it always was.
    """
    User = get_user_model()
    embedded = is_embedded_mode()

    with transaction.atomic():
        # Lock the account before reading anything: its requests queue here, and
        # each one counts the workspaces the request before it committed.
        User.objects.select_for_update().get(pk=user.pk)
        ensure_workspace_create_allowed(user)

        from bfg.common.services.workspace_service import WorkspaceService

        workspace = WorkspaceService(user=user).create_workspace(
            name=name,
            slug=slug or unique_workspace_slug(name),
            owner_user=user,
            region=region,
        )
        if embedded:
            _provision(
                workspace,
                user,
                name=name,
                country=country,
                currency=currency,
                language=language,
                current_workspace_id=current_workspace_id,
            )

    if not embedded:
        provision_workspace.delay(workspace_id=workspace.id, initiated_by_id=user.id)
    return workspace


def unique_workspace_slug(name: str) -> str:
    """A slug no workspace has yet, made from *name*.

    The slug of the name itself when it is free. When it is taken, four random
    hex digits follow it; a name with nothing to slugify, one written in Chinese
    for instance, gets ``ws-`` and eight. The random part is drawn again while it
    collides.
    """
    Workspace = apps.get_model("common", "Workspace")
    max_length = Workspace._meta.get_field("slug").max_length
    base = slugify(name)[:max_length].strip("-")
    if base and not Workspace.objects.filter(slug=base).exists():
        return base
    for _ in range(_SLUG_ATTEMPTS):
        if base:
            # The slug can become a hostname label, so the name stays readable in it.
            candidate = f"{base[:max_length - 5].rstrip('-')}-{secrets.token_hex(2)}"
        else:
            candidate = f"ws-{secrets.token_hex(4)}"
        if not Workspace.objects.filter(slug=candidate).exists():
            return candidate
    raise WorkspaceAlreadyExists(f"No free slug found for a workspace named {name!r}")


# ── Embedded provisioning ─────────────────────────────────────────────────────

def _provision(workspace, user, *, name, country, currency, language, current_workspace_id) -> None:
    """Give a new workspace what its storefront needs, and record its creation."""
    from bfg.common.middleware import get_current_workspace, set_current_workspace
    from bfg.common.onboarding import provisioning
    from bfg.inbox.notification_templates import ensure_notification_templates

    WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
    WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")

    current = _current_locale(user, current_workspace_id)
    # Every step names the workspace. Binding it as well, as provision_workspace
    # does, keeps anything reached through a tenant-scoped manager from coming up
    # empty on this public path.
    previous = get_current_workspace()
    set_current_workspace(workspace)
    try:
        settings_obj, _ = provisioning.ensure_settings(
            workspace,
            country=country or current.get("country", ""),
            currency=currency or current.get("currency", ""),
            language=language or current.get("language", ""),
            site_name=name,
        )
        provisioning.ensure_currency(settings_obj.default_currency)
        provisioning.ensure_store(workspace)
        templates = ensure_notification_templates(
            workspace, language=settings_obj.default_language, currency=settings_obj.default_currency,
        )
    finally:
        set_current_workspace(previous)

    WorkspacePlatformProfile.objects.get_or_create(workspace=workspace)
    WorkspaceOperation.objects.create(
        workspace=workspace,
        operation="create",
        status="completed",
        initiated_by=user,
        details={"embedded": True, "notification_templates": templates["created"]},
        completed_at=timezone.now(),
    )


def _is_workspace_admin(user) -> bool:
    """Whether *user* is an active admin of any workspace, whatever its status."""
    StaffMember = apps.get_model("common", "StaffMember")
    # Across every workspace, so not through the tenant-scoped manager.
    return StaffMember.all_objects.filter(user=user, is_active=True, role__code="admin").exists()


def _current_locale(user, workspace_id) -> dict:
    """Country, currency and language of workspace *workspace_id*, if *user* works there.

    The id comes from the caller's access token, which can outlive a membership,
    so it counts only while *user* is still active staff or the owner there.
    """
    if not workspace_id:
        return {}
    Settings = apps.get_model("common", "Settings")
    StaffMember = apps.get_model("common", "StaffMember")
    settings_obj = Settings.objects.select_related("workspace").filter(workspace_id=workspace_id).first()
    if settings_obj is None:
        return {}
    workspace = settings_obj.workspace
    works_there = (
        StaffMember.all_objects.filter(workspace=workspace, user=user, is_active=True).exists()
        or is_workspace_owner(user, workspace)
    )
    if not works_there:
        return {}
    return {
        "country": settings_obj.country,
        "currency": settings_obj.default_currency,
        "language": settings_obj.default_language,
    }
