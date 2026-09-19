# -*- coding: utf-8 -*-
"""Fenced capacity reservations for future Cluster placement work.

The Platform may reserve room for an unplaced Workspace, but it must not turn
that reservation into a routing change. A separate authenticated data-plane
adapter will eventually own copy, verification, cutover, and compensation.
"""
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bfg.platform.services.control_audit import redact_control_value


DEFAULT_RESERVATION_SECONDS = 60 * 60
MIN_RESERVATION_SECONDS = 5 * 60
MAX_RESERVATION_SECONDS = 24 * 60 * 60


class PlacementQueueError(Exception):
    """A safe, public failure for a placement control action."""

    def __init__(self, code, detail, *, status_code=409):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def reservation_seconds():
    """Return a bounded rollback window from deployment configuration."""
    configured = getattr(settings, "PLATFORM_PLACEMENT_RESERVATION_SECONDS", DEFAULT_RESERVATION_SECONDS)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = DEFAULT_RESERVATION_SECONDS
    return max(MIN_RESERVATION_SECONDS, min(MAX_RESERVATION_SECONDS, value))


def _event(request, event_type, **details):
    PlacementEvent = apps.get_model("platform", "WorkspacePlacementEvent")
    sequence = request.events.count() + 1
    return PlacementEvent.objects.create(
        request=request,
        sequence=sequence,
        event_type=event_type,
        details=redact_control_value(details),
    )


def _profile_for_update(workspace):
    WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
    WorkspacePlatformProfile.objects.get_or_create(workspace=workspace)
    return WorkspacePlatformProfile.objects.select_for_update().select_related("cluster").get(workspace=workspace)


def _expire_request(request):
    """Expire one locked reservation and write its durable operation evidence."""
    PlacementRequest = apps.get_model("platform", "WorkspacePlacementRequest")
    PlatformAuditEvent = apps.get_model("platform", "PlatformAuditEvent")
    profile = _profile_for_update(request.workspace)
    # A late data-plane callback must not pass the request's original fence.
    profile.placement_fence += 1
    profile.save(update_fields=["placement_fence", "updated_at"])
    request.status = PlacementRequest.STATUS_EXPIRED
    request.save(update_fields=["status", "updated_at"])
    _event(request, "reservation_expired", placement_fence=profile.placement_fence)
    PlatformAuditEvent.objects.create(
        action="workspace.placement_expired",
        target_type="workspace",
        target_id=str(request.workspace_id),
        reason="Placement reservation TTL elapsed",
        before={
            "placement_request_id": str(request.id),
            "status": PlacementRequest.STATUS_RESERVED,
            "target_cluster_id": request.target_cluster_id,
        },
        after={"status": PlacementRequest.STATUS_EXPIRED, "placement_fence": profile.placement_fence},
    )
    return request


def _expire_reserved_for_target(target_cluster, now, *, limit=None):
    """Release expired reservations while the target Cluster lock is held."""
    PlacementRequest = apps.get_model("platform", "WorkspacePlacementRequest")
    queryset = PlacementRequest.objects.select_for_update().filter(
        target_cluster=target_cluster,
        status=PlacementRequest.STATUS_RESERVED,
        reservation_expires_at__lte=now,
    ).select_related("workspace").order_by("reservation_expires_at", "id")
    rows = list(queryset[:limit] if limit is not None else queryset)
    return [_expire_request(request) for request in rows]


def expire_due_reservations(*, limit=100):
    """Expire a bounded number of due reservations with the same locking as create.

    This is intended for a scheduler or explicit management command. It never
    changes a workspace's Cluster assignment; it only releases capacity and
    fences out a delayed data-plane worker.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be a positive whole number") from exc
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")

    Cluster = apps.get_model("platform", "Cluster")
    PlacementRequest = apps.get_model("platform", "WorkspacePlacementRequest")
    now = timezone.now()
    target_ids = list(
        PlacementRequest.objects.filter(
            status=PlacementRequest.STATUS_RESERVED,
            reservation_expires_at__lte=now,
        ).order_by("target_cluster_id").values_list("target_cluster_id", flat=True).distinct()
    )
    expired = []
    for target_id in target_ids:
        if len(expired) >= limit:
            break
        with transaction.atomic():
            target = Cluster.objects.select_for_update().filter(pk=target_id).first()
            if target is None:
                continue
            # The query has an explicit cap so a maintenance invocation cannot
            # turn into an unbounded write during an incident.
            expired.extend(_expire_reserved_for_target(target, now, limit=limit - len(expired)))
    return expired


def create_reservation(*, workspace, target_cluster_id, expected_profile_fence, initiated_by):
    """Reserve target capacity for an unplaced Workspace without changing routing."""
    Cluster = apps.get_model("platform", "Cluster")
    PlacementRequest = apps.get_model("platform", "WorkspacePlacementRequest")

    try:
        expected_fence = int(expected_profile_fence)
    except (TypeError, ValueError) as exc:
        raise PlacementQueueError(
            "placement_fence_required",
            "Reload the workspace and provide its current placement fence.",
            status_code=400,
        ) from exc
    if expected_fence < 0:
        raise PlacementQueueError(
            "placement_fence_required",
            "Reload the workspace and provide its current placement fence.",
            status_code=400,
        )

    target_cluster_id = str(target_cluster_id or "").strip()
    if not target_cluster_id or len(target_cluster_id) > 32:
        raise PlacementQueueError(
            "placement_target_required",
            "Choose an available target Cluster.",
            status_code=400,
        )

    with transaction.atomic():
        # Serialize capacity decisions through the target before taking a
        # workspace fence. Expiry cleanup follows the same lock order.
        try:
            target = Cluster.objects.select_for_update().get(pk=target_cluster_id)
        except Cluster.DoesNotExist as exc:
            raise PlacementQueueError(
                "placement_target_not_found",
                "The selected target Cluster is not available.",
            ) from exc

        now = timezone.now()
        _expire_reserved_for_target(target, now)
        profile = _profile_for_update(workspace)
        if profile.placement_fence != expected_fence:
            raise PlacementQueueError(
                "placement_fence_conflict",
                "This workspace placement changed while you were reviewing it. Reload and try again.",
            )
        if profile.cluster_id:
            raise PlacementQueueError(
                "workspace_live_migration_unsupported",
                "Live Cluster migration is unavailable until a verified data-plane adapter is configured.",
            )
        if profile.remote_workspace_uuid:
            raise PlacementQueueError(
                "workspace_placement_requires_data_plane",
                "This workspace has remote data and cannot be placed without a verified data-plane adapter.",
            )
        if PlacementRequest.objects.select_for_update().filter(
            workspace=workspace,
            status=PlacementRequest.STATUS_RESERVED,
        ).exists():
            raise PlacementQueueError(
                "workspace_placement_already_reserved",
                "This workspace already has a pending placement reservation.",
            )
        assigned = apps.get_model("platform", "WorkspacePlatformProfile").objects.filter(cluster=target).count()
        reserved = PlacementRequest.objects.filter(
            target_cluster=target,
            status=PlacementRequest.STATUS_RESERVED,
            reservation_expires_at__gt=now,
        ).count()
        if not target.is_active or not target.is_accepting_new:
            raise PlacementQueueError(
                "placement_target_unavailable",
                "The selected target Cluster is not accepting new workspace placements.",
            )
        if assigned + reserved >= target.max_workspaces:
            raise PlacementQueueError(
                "cluster_capacity_reserved",
                "The selected target Cluster has no unreserved workspace capacity.",
            )

        profile.placement_fence += 1
        profile.save(update_fields=["placement_fence", "updated_at"])
        request = PlacementRequest.objects.create(
            workspace=workspace,
            target_cluster=target,
            profile_fence=profile.placement_fence,
            reservation_expires_at=now + timedelta(seconds=reservation_seconds()),
            created_by=initiated_by,
        )
        _event(
            request,
            "requested",
            source_cluster_id=None,
            target_cluster_id=target.id,
            placement_fence=profile.placement_fence,
        )
        _event(
            request,
            "capacity_reserved",
            reservation_expires_at=request.reservation_expires_at,
        )
    return request


def rollback_reservation(*, request):
    """Release one pending reservation and fence out delayed data-plane work."""
    PlacementRequest = apps.get_model("platform", "WorkspacePlacementRequest")
    with transaction.atomic():
        request = (
            PlacementRequest.objects.select_for_update()
            .select_related("workspace", "target_cluster", "source_cluster", "created_by")
            .get(pk=request.pk)
        )
        if request.status != PlacementRequest.STATUS_RESERVED:
            raise PlacementQueueError(
                "placement_reservation_not_active",
                "This placement reservation is no longer active.",
            )
        profile = _profile_for_update(request.workspace)
        _event(request, "rollback_requested")
        profile.placement_fence += 1
        profile.save(update_fields=["placement_fence", "updated_at"])
        request.status = PlacementRequest.STATUS_ROLLED_BACK
        request.rolled_back_at = timezone.now()
        request.save(update_fields=["status", "rolled_back_at", "updated_at"])
        _event(request, "capacity_released", placement_fence=profile.placement_fence)
    return request
