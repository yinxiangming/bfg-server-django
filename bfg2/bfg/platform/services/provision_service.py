# -*- coding: utf-8 -*-
"""
Workspace Provision Service
Handles the lifecycle of creating and managing Workspaces.

Supports two modes:
  - Embedded: creates everything in the same DB; skips PlatformMembership/remote UUID
  - Standalone: creates WorkspacePlatformProfile + PlatformMembership + remote UUID
"""
import secrets
from uuid import uuid4
from django.apps import apps
from django.utils import timezone
from celery import shared_task

from bfg.platform.utils import is_embedded_mode


def generate_api_key(prefix: str = "ws") -> str:
    """Generate a secure random API key."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


@shared_task(bind=True, max_retries=3)
def provision_workspace(self, workspace_id: int, cluster_id: str = None, initiated_by_id: int = None):
    """
    Celery task: Provision a workspace after creation.

    Embedded mode:
      1. Create WorkspacePlatformProfile (no cluster, no API keys, no remote UUID)
      2. Record WorkspaceOperation
      3. Mark workspace active

    Standalone mode:
      1. Create WorkspacePlatformProfile (with cluster, API keys, remote UUID)
      2. Create PlatformMembership for the initiating user
      3. Record WorkspaceOperation
      4. Mark workspace active
    """
    WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
    WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")
    Workspace = apps.get_model("common", "Workspace")
    User = apps.get_model("common", "User")

    embedded = is_embedded_mode()

    try:
        workspace = Workspace.objects.get(id=workspace_id)
        initiated_by = User.objects.filter(id=initiated_by_id).first() if initiated_by_id else None

        # Record operation start
        operation = WorkspaceOperation.objects.create(
            workspace=workspace,
            operation="create",
            status="running",
            initiated_by=initiated_by,
            details={"cluster_id": cluster_id, "embedded": embedded},
        )

        if embedded:
            # Embedded: lightweight profile, no cluster/keys/remote UUID
            profile, created = WorkspacePlatformProfile.objects.get_or_create(
                workspace=workspace,
                defaults={
                    "region": "local",
                },
            )
        else:
            # Standalone: full profile with cluster, API keys, remote UUID
            PlatformMembership = apps.get_model("platform", "PlatformMembership")

            profile, created = WorkspacePlatformProfile.objects.get_or_create(
                workspace=workspace,
                defaults={
                    "cluster_id": cluster_id,
                    "region": "us",
                    "platform_api_key": generate_api_key("plat"),
                    "agent_api_key": generate_api_key("agent"),
                    "remote_workspace_uuid": uuid4(),
                },
            )

            # Create PlatformMembership for the initiating user (owner)
            if initiated_by:
                PlatformMembership.objects.get_or_create(
                    user=initiated_by,
                    profile=profile,
                    defaults={"role": "owner"},
                )

        # Mark workspace as active
        workspace.is_active = True
        workspace.save(update_fields=["is_active"])

        # Mark operation complete
        operation.status = "completed"
        operation.completed_at = timezone.now()
        operation.save(update_fields=["status", "completed_at"])

        return {"workspace_id": workspace_id, "status": "provisioned", "embedded": embedded}

    except Exception as exc:
        # Mark operation failed if it was created
        try:
            WorkspaceOperation.objects.filter(
                workspace_id=workspace_id, operation="create", status="running"
            ).update(status="failed", error_message=str(exc), completed_at=timezone.now())
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=60)


def suspend_workspace(workspace, initiated_by=None, reason: str = "") -> None:
    """Suspend a workspace (read-only mode)."""
    WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")

    workspace.is_active = False
    workspace.save(update_fields=["is_active"])

    profile = getattr(workspace, "platform_profile", None)
    if profile:
        profile.suspended_at = timezone.now()
        profile.save(update_fields=["suspended_at"])

    WorkspaceOperation.objects.create(
        workspace=workspace,
        operation="suspend",
        status="completed",
        initiated_by=initiated_by,
        details={"reason": reason},
        completed_at=timezone.now(),
    )


def resume_workspace(workspace, initiated_by=None) -> None:
    """Resume a suspended workspace."""
    WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")

    workspace.is_active = True
    workspace.save(update_fields=["is_active"])

    profile = getattr(workspace, "platform_profile", None)
    if profile:
        profile.suspended_at = None
        profile.save(update_fields=["suspended_at"])

    WorkspaceOperation.objects.create(
        workspace=workspace,
        operation="resume",
        status="completed",
        initiated_by=initiated_by,
        details={},
        completed_at=timezone.now(),
    )
