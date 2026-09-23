"""Superuser-only business-data archive actions for the Platform control plane.

Configuration exports and business-data archives are deliberately separate
contracts. These actions expose the local data-plane adapter without reviving the
legacy Platform console models or routes.
"""

from django.apps import apps
from django.http import Http404
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from bfg.platform.data_plane import DataPlaneError, get_data_plane_adapter
from bfg.platform.services.control_actions import (
    claim_action,
    complete_action,
    require_confirmation,
    require_reason,
)
from bfg.platform.services.control_audit import record_control_audit


class PlatformDataPlaneActionsMixin:
    """Actions mixed into the canonical Platform workspace control viewset."""

    @staticmethod
    def _data_workspace(pk):
        Workspace = apps.get_model("common", "Workspace")
        try:
            return Workspace.objects.select_related("platform_profile__cluster").get(pk=pk)
        except (Workspace.DoesNotExist, TypeError, ValueError) as exc:
            raise Http404 from exc

    @staticmethod
    def _snapshot_item(snapshot):
        return {
            "id": str(snapshot.id),
            "workspace_id": snapshot.workspace_id,
            "kind": snapshot.kind,
            "status": snapshot.status,
            "artifact_sha256": snapshot.artifact_sha256 or None,
            "manifest_sha256": snapshot.manifest_sha256 or None,
            "row_count": snapshot.row_count,
            "media_count": snapshot.media_count,
            "media_bytes": snapshot.media_bytes,
            "source_cluster_id": snapshot.source_cluster_id or None,
            "target_cluster_id": snapshot.target_cluster_id or None,
            "failure_code": snapshot.failure_code or None,
            "created_at": snapshot.created_at,
            "completed_at": snapshot.completed_at,
        }

    @action(detail=True, methods=["get"], url_path="data-snapshots")
    def data_snapshots(self, request, pk=None):
        """List business-data archives without exposing artifact paths."""
        workspace = self._data_workspace(pk)
        Snapshot = apps.get_model("platform", "WorkspaceDataSnapshot")
        return Response([
            self._snapshot_item(snapshot)
            for snapshot in Snapshot.objects.filter(workspace=workspace).order_by("-created_at")[:100]
        ])

    @action(detail=True, methods=["post"], url_path="data-export")
    def data_export(self, request, pk=None):
        """Create a local business-data and media archive."""
        require_confirmation(request)
        reason = require_reason(request)
        workspace = self._data_workspace(pk)
        Snapshot = apps.get_model("platform", "WorkspaceDataSnapshot")
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        if profile and profile.remote_workspace_uuid:
            return Response(
                {"detail": "Business-data export must run on the Workspace's data plane.", "code": "remote_data_plane_required"},
                status=status.HTTP_409_CONFLICT,
            )
        action_request, replay = claim_action(
            request,
            action="workspace.data_export",
            target_type="workspace",
            target_id=workspace.id,
            payload={"reason": reason},
        )
        if replay is not None:
            return replay

        snapshot = Snapshot.objects.create(
            workspace=workspace,
            kind=Snapshot.KIND_ARCHIVE,
            status=Snapshot.STATUS_EXPORTING,
            requested_by=request.user,
            source_cluster_id=cluster.id if cluster else "",
        )
        try:
            result = get_data_plane_adapter().export(workspace, snapshot_id=str(snapshot.id))
        except DataPlaneError as exc:
            snapshot.status = Snapshot.STATUS_FAILED
            snapshot.failure_code = exc.code
            snapshot.completed_at = timezone.now()
            snapshot.save(update_fields=["status", "failure_code", "completed_at"])
            body = {"detail": "The workspace data archive could not be created.", "code": exc.code}
            complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
            record_control_audit(
                request=request,
                action="workspace.data_export",
                target_type="workspace",
                target_id=workspace.id,
                reason=reason,
                result="failed",
                after={"snapshot_id": str(snapshot.id), "code": exc.code},
            )
            return Response(body, status=status.HTTP_409_CONFLICT)

        snapshot.status = Snapshot.STATUS_READY
        snapshot.artifact_uri = result.artifact_uri
        snapshot.artifact_sha256 = result.artifact_sha256
        snapshot.manifest_sha256 = result.manifest_sha256
        snapshot.manifest = result.manifest
        snapshot.row_count = result.row_count
        snapshot.media_count = result.media_count
        snapshot.media_bytes = result.media_bytes
        snapshot.completed_at = timezone.now()
        snapshot.save(update_fields=[
            "status", "artifact_uri", "artifact_sha256", "manifest_sha256", "manifest",
            "row_count", "media_count", "media_bytes", "completed_at",
        ])
        body = self._snapshot_item(snapshot)
        complete_action(action_request, result="succeeded", response_status=status.HTTP_201_CREATED, response_body=body)
        record_control_audit(
            request=request,
            action="workspace.data_export",
            target_type="workspace",
            target_id=workspace.id,
            reason=reason,
            after={
                "snapshot_id": str(snapshot.id),
                "format": result.manifest["format"],
                "row_count": result.row_count,
                "media_count": result.media_count,
            },
        )
        return Response(body, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="data-verify")
    def data_verify(self, request, pk=None):
        """Verify an archive before any restore is attempted."""
        require_confirmation(request)
        reason = require_reason(request)
        workspace = self._data_workspace(pk)
        snapshot_id = str(request.data.get("snapshot_id") or "").strip()
        Snapshot = apps.get_model("platform", "WorkspaceDataSnapshot")
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id, workspace=workspace)
        except (Snapshot.DoesNotExist, ValueError):
            return Response(
                {"detail": "Data snapshot not found.", "code": "data_snapshot_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        action_request, replay = claim_action(
            request,
            action="workspace.data_verify",
            target_type="workspace",
            target_id=workspace.id,
            payload={"snapshot_id": snapshot_id, "reason": reason},
        )
        if replay is not None:
            return replay
        try:
            result = get_data_plane_adapter().validate(
                snapshot.artifact_uri,
                expected_workspace_uuid=workspace.uuid,
            )
        except DataPlaneError as exc:
            snapshot.status = Snapshot.STATUS_FAILED
            snapshot.failure_code = exc.code
            snapshot.save(update_fields=["status", "failure_code"])
            body = {"detail": "The workspace data archive failed verification.", "code": exc.code}
            complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
            record_control_audit(
                request=request,
                action="workspace.data_verify",
                target_type="workspace",
                target_id=workspace.id,
                reason=reason,
                result="failed",
                after={"snapshot_id": snapshot_id, "code": exc.code},
            )
            return Response(body, status=status.HTTP_409_CONFLICT)
        if snapshot.artifact_sha256 != result.artifact_sha256 or snapshot.manifest_sha256 != result.manifest_sha256:
            body = {
                "detail": "The workspace data archive metadata no longer matches the stored snapshot.",
                "code": "snapshot_metadata_mismatch",
            }
            snapshot.status = Snapshot.STATUS_FAILED
            snapshot.failure_code = body["code"]
            snapshot.save(update_fields=["status", "failure_code"])
            complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
            return Response(body, status=status.HTTP_409_CONFLICT)

        snapshot.status = Snapshot.STATUS_VERIFIED
        snapshot.failure_code = ""
        snapshot.save(update_fields=["status", "failure_code"])
        body = self._snapshot_item(snapshot)
        complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=body)
        record_control_audit(
            request=request,
            action="workspace.data_verify",
            target_type="workspace",
            target_id=workspace.id,
            reason=reason,
            after={"snapshot_id": snapshot_id, "artifact_sha256": result.artifact_sha256},
        )
        return Response(body)

    @action(detail=False, methods=["post"], url_path="data-restore")
    def data_restore(self, request):
        """Restore a verified local archive into an empty target workspace."""
        require_confirmation(request)
        reason = require_reason(request)
        snapshot_id = str(request.data.get("snapshot_id") or "").strip()
        target_id = request.data.get("target_workspace_id")
        Snapshot = apps.get_model("platform", "WorkspaceDataSnapshot")
        Workspace = apps.get_model("common", "Workspace")
        try:
            source_snapshot = Snapshot.objects.select_related("workspace").get(id=snapshot_id)
            target = Workspace.objects.select_related("platform_profile__cluster").get(pk=target_id)
        except (Snapshot.DoesNotExist, ValueError):
            return Response(
                {"detail": "Data snapshot not found.", "code": "data_snapshot_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Workspace.DoesNotExist:
            return Response(
                {"detail": "Target workspace not found.", "code": "target_workspace_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        if source_snapshot.status != Snapshot.STATUS_VERIFIED:
            return Response(
                {"detail": "Verify the data snapshot before restoring it.", "code": "snapshot_not_verified"},
                status=status.HTTP_409_CONFLICT,
            )
        source_profile = getattr(source_snapshot.workspace, "platform_profile", None)
        target_profile = getattr(target, "platform_profile", None)
        if (
            (source_profile and source_profile.remote_workspace_uuid)
            or (target_profile and target_profile.remote_workspace_uuid)
        ):
            return Response(
                {"detail": "Cross-Cluster restore requires a coordinated data-plane transfer.", "code": "remote_data_plane_required"},
                status=status.HTTP_409_CONFLICT,
            )
        action_request, replay = claim_action(
            request,
            action="workspace.data_restore",
            target_type="workspace",
            target_id=target.id,
            payload={"snapshot_id": snapshot_id, "reason": reason},
        )
        if replay is not None:
            return replay
        restore_snapshot = Snapshot.objects.create(
            workspace=target,
            kind=Snapshot.KIND_RESTORE,
            status=Snapshot.STATUS_RESTORING,
            requested_by=request.user,
            source_cluster_id=getattr(getattr(source_profile, "cluster", None), "id", ""),
            target_cluster_id=getattr(getattr(target_profile, "cluster", None), "id", ""),
        )
        try:
            result = get_data_plane_adapter().restore(source_snapshot.artifact_uri, target_workspace=target)
        except DataPlaneError as exc:
            restore_snapshot.status = Snapshot.STATUS_FAILED
            restore_snapshot.failure_code = exc.code
            restore_snapshot.completed_at = timezone.now()
            restore_snapshot.save(update_fields=["status", "failure_code", "completed_at"])
            body = {"detail": "The workspace data archive could not be restored.", "code": exc.code}
            complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
            record_control_audit(
                request=request,
                action="workspace.data_restore",
                target_type="workspace",
                target_id=target.id,
                reason=reason,
                result="failed",
                after={"snapshot_id": snapshot_id, "code": exc.code},
            )
            return Response(body, status=status.HTTP_409_CONFLICT)
        restore_snapshot.status = Snapshot.STATUS_COMPLETED
        restore_snapshot.artifact_uri = result.artifact_uri
        restore_snapshot.artifact_sha256 = result.artifact_sha256
        restore_snapshot.manifest_sha256 = result.manifest_sha256
        restore_snapshot.manifest = result.manifest
        restore_snapshot.row_count = result.row_count
        restore_snapshot.media_count = result.media_count
        restore_snapshot.media_bytes = result.media_bytes
        restore_snapshot.completed_at = timezone.now()
        restore_snapshot.save(update_fields=[
            "status", "artifact_uri", "artifact_sha256", "manifest_sha256", "manifest",
            "row_count", "media_count", "media_bytes", "completed_at",
        ])
        body = self._snapshot_item(restore_snapshot)
        complete_action(action_request, result="succeeded", response_status=status.HTTP_201_CREATED, response_body=body)
        record_control_audit(
            request=request,
            action="workspace.data_restore",
            target_type="workspace",
            target_id=target.id,
            reason=reason,
            after={"snapshot_id": snapshot_id, "restore_snapshot_id": str(restore_snapshot.id)},
        )
        return Response(body, status=status.HTTP_201_CREATED)
