# -*- coding: utf-8 -*-
"""Platform-admin workspace console endpoints.

These endpoints deliberately expose lifecycle controls without exposing cluster
credentials or allowing a hard delete from the web console.
"""
from datetime import timedelta

from django.apps import apps
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import dateparse, timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bfg.platform.permissions import IsPlatformSuperuser
from bfg.platform.services.audit_service import record_platform_audit, redact_platform_audit_value
from bfg.platform.services.provision_service import suspend_workspace, resume_workspace
from bfg.platform.utils import is_embedded_mode, is_platform_workspace
from bfg.common.exceptions import WorkspaceCapacityUnavailable
from bfg.common.models import normalize_hostname
from bfg.common.services.workspace_service import WorkspaceService
from bfg.common.services.user_service import UserService


def _change_reason(request):
    """Require an operator explanation for every state-changing console request."""
    reason = str(
        request.data.get("reason")
        or request.headers.get("X-Platform-Change-Reason")
        or ""
    ).strip()
    if len(reason) < 3:
        raise ValidationError({"reason": "Provide a change reason of at least 3 characters."})
    return reason[:500]


def _confirmed(request):
    if request.data.get("confirm") is not True:
        raise ValidationError({"confirm": "confirm=true is required."})


def _cluster_snapshot(cluster):
    """Return auditable cluster state without connection secrets."""
    return {
        "id": cluster.id,
        "name": cluster.name,
        "region": cluster.region,
        "api_base_url": cluster.api_base_url,
        "frontend_base_url": cluster.frontend_base_url,
        "db_host": cluster.db_host,
        "db_port": cluster.db_port,
        "redis_configured": bool(cluster.redis_url),
        "s3_bucket": cluster.s3_bucket,
        "max_workspaces": cluster.max_workspaces,
        "is_accepting_new": cluster.is_accepting_new,
        "is_active": cluster.is_active,
        "config_version": cluster.config_version,
    }


class PlatformConsoleWorkspaceViewSet(viewsets.ViewSet):
    """Cross-workspace management for platform administrators only."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]

    def _workspace(self, pk):
        Workspace = apps.get_model("common", "Workspace")
        return Workspace.objects.select_related("platform_profile__cluster").get(pk=pk)

    def _administrator_users(self, workspace):
        """Return eligible reset recipients using the ownership model for this mode."""
        User = apps.get_model("common", "User")
        if is_embedded_mode():
            StaffMember = apps.get_model("common", "StaffMember")
            user_ids = StaffMember.all_objects.filter(
                workspace=workspace, is_active=True, role__code__in=["admin", "owner"],
            ).values_list("user_id", flat=True)
        else:
            PlatformMembership = apps.get_model("platform", "PlatformMembership")
            # PlatformMembership ownership is durable; StaffMember roles may change
            # inside the tenant and must not grant cross-workspace reset authority.
            user_ids = PlatformMembership.objects.filter(
                profile__workspace=workspace, is_active=True, role="owner",
            ).values_list("user_id", flat=True)
        return User.objects.filter(id__in=user_ids, is_active=True).order_by("id")

    def _owner(self, workspace):
        user = self._administrator_users(workspace).first()
        if not user:
            return None
        return {"id": user.id, "username": user.username, "email": user.email or None}

    def _item(self, workspace):
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        owner = self._owner(workspace)
        domains = list(workspace.domains.values_list("hostname", flat=True))
        staff_count = apps.get_model("common", "StaffMember").all_objects.filter(
            workspace=workspace, is_active=True
        ).count()
        return {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "is_active": workspace.is_active,
            "is_platform": is_platform_workspace(workspace),
            "suspended_at": profile.suspended_at.isoformat() if profile and profile.suspended_at else None,
            "scheduled_deletion_at": (
                profile.scheduled_deletion_at.isoformat()
                if profile and profile.scheduled_deletion_at else None
            ),
            "created_at": workspace.created_at,
            "domains": domains,
            "owner": owner,
            "owned_by_viewer": bool(owner and owner["id"] == self.request.user.id),
            "staff_count": staff_count,
            "active_extensions": [],
            "cluster": ({"id": cluster.id, "name": cluster.name, "region": cluster.region,
                         "is_active": cluster.is_active} if cluster else None),
        }

    def list(self, request):
        Workspace = apps.get_model("common", "Workspace")
        queryset = Workspace.objects.select_related("platform_profile__cluster").order_by("-created_at")
        term = (request.query_params.get("search") or "").strip()
        if term:
            from django.db.models import Q
            queryset = queryset.filter(Q(name__icontains=term) | Q(slug__icontains=term))
        return Response([self._item(workspace) for workspace in queryset[:500]])

    def retrieve(self, request, pk=None):
        try:
            workspace = self._workspace(pk)
        except apps.get_model("common", "Workspace").DoesNotExist:
            return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = self._item(workspace)
        payload["email"] = workspace.email
        payload["phone"] = workspace.phone
        payload["settings"] = workspace.settings or {}
        payload["extensions"] = []
        return Response(payload)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        workspace = self._workspace(pk)
        before = {"is_active": workspace.is_active}
        suspend_workspace(workspace, initiated_by=request.user, reason=reason)
        record_platform_audit(
            request=request, action="workspace.suspend", target_type="workspace",
            target_id=workspace.id, reason=reason, before=before,
            after={"is_active": workspace.is_active},
        )
        return Response(self._item(workspace))

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        workspace = self._workspace(pk)
        before = {"is_active": workspace.is_active}
        resume_workspace(workspace, initiated_by=request.user)
        record_platform_audit(
            request=request, action="workspace.resume", target_type="workspace",
            target_id=workspace.id, reason=reason, before=before,
            after={"is_active": workspace.is_active},
        )
        return Response(self._item(workspace))

    @action(detail=True, methods=["post"])
    def delete(self, request, pk=None):
        """Schedule a recoverable deletion; never remove tenant data here."""
        _confirmed(request)
        reason = _change_reason(request)
        WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")
        Workspace = apps.get_model("common", "Workspace")
        WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
        with transaction.atomic():
            try:
                workspace = Workspace.objects.select_for_update().select_related(
                    "platform_profile__cluster"
                ).get(pk=pk)
            except Workspace.DoesNotExist:
                return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
            profile, _ = WorkspacePlatformProfile.objects.get_or_create(workspace=workspace)
            # A second submit must not silently extend the deletion window.
            if profile.scheduled_deletion_at:
                return Response(self._item(workspace))
            before = {"is_active": workspace.is_active, "scheduled_deletion_at": None}
            workspace.is_active = False
            workspace.save(update_fields=["is_active"])
            profile.scheduled_deletion_at = timezone.now() + timedelta(days=30)
            profile.save(update_fields=["scheduled_deletion_at", "updated_at"])
            WorkspaceOperation.objects.create(workspace=workspace, operation="delete", status="completed",
                                              initiated_by=request.user, details={"soft": True, "reason": reason},
                                              completed_at=timezone.now())
            record_platform_audit(
                request=request, action="workspace.deletion_scheduled", target_type="workspace",
                target_id=workspace.id, reason=reason, before=before,
                after={"is_active": False, "scheduled_deletion_at": profile.scheduled_deletion_at.isoformat()},
            )
            # ``select_related`` can hold a stale one-to-one object when a profile was
            # created through ``get_or_create`` above. Re-read before serializing the
            # response so the UI receives the actual deletion deadline.
            return Response(self._item(self._workspace(workspace.id)))

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        """Cancel a scheduled deletion and restore a workspace to active state."""
        _confirmed(request)
        reason = _change_reason(request)
        Workspace = apps.get_model("common", "Workspace")
        with transaction.atomic():
            try:
                workspace = Workspace.objects.select_for_update().select_related(
                    "platform_profile__cluster"
                ).get(pk=pk)
            except Workspace.DoesNotExist:
                return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
            profile = getattr(workspace, "platform_profile", None)
            if not profile or not profile.scheduled_deletion_at:
                return Response({
                    "detail": "This workspace is not scheduled for deletion.",
                    "code": "workspace_not_scheduled_for_deletion",
                }, status=status.HTTP_409_CONFLICT)
            scheduled_at = profile.scheduled_deletion_at
            resume_workspace(workspace, initiated_by=request.user)
            record_platform_audit(
                request=request, action="workspace.deletion_cancelled", target_type="workspace",
                target_id=workspace.id, reason=reason,
                before={"is_active": False, "scheduled_deletion_at": scheduled_at.isoformat()},
                after={"is_active": True, "scheduled_deletion_at": None},
            )
            return Response(self._item(workspace))

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        workspace = self._workspace(pk)
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        owner = self._owner(workspace)
        data = {
            "format": "idlevo-workspace-v1",
            "scope": "configuration-template",
            "does_not_include": ["members", "business_data", "media"],
            "workspace": {"name": workspace.name, "slug": workspace.slug, "email": workspace.email,
                          "phone": workspace.phone, "settings": workspace.settings or {}},
            "owner_email": owner["email"] if owner else None,
            "cluster": {"id": cluster.id, "name": cluster.name, "region": cluster.region} if cluster else None,
            # Importing a hostname never proves control. The destination always
            # restores custom domains as pending, non-primary candidates.
            "custom_domains": list(workspace.domains.filter(
                kind=apps.get_model("common", "WorkspaceDomain").KIND_CUSTOM,
            ).values("hostname")),
            "exported_at": timezone.now().isoformat(),
        }
        record_platform_audit(
            request=request, action="workspace.exported", target_type="workspace",
            target_id=workspace.id, reason="Workspace configuration export downloaded.",
            after={"format": data["format"]},
        )
        import json
        response = HttpResponse(json.dumps(data, indent=2, default=str), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="workspace-{workspace.slug}.json"'
        return response

    @action(detail=False, methods=["post"], url_path="import-workspace")
    @transaction.atomic
    def import_workspace(self, request):
        _confirmed(request)
        reason = _change_reason(request)
        data = request.data if isinstance(request.data, dict) else {}
        export_format = data.get("format")
        if export_format and export_format != "idlevo-workspace-v1":
            return Response({
                "detail": "This is not a supported Idlevo workspace configuration export.",
                "code": "unsupported_workspace_import_format",
            }, status=status.HTTP_400_BAD_REQUEST)
        source = data.get("workspace", data)
        if not isinstance(source, dict):
            return Response({"detail": "workspace must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        name = str(source.get("name", "")).strip()
        if not name:
            return Response({"detail": "workspace.name is required."}, status=status.HTTP_400_BAD_REQUEST)
        Workspace = apps.get_model("common", "Workspace")
        slug = source.get("slug") or None
        if slug and Workspace.objects.filter(slug=slug).exists():
            return Response({"detail": "A workspace with this slug already exists."}, status=status.HTTP_409_CONFLICT)
        User = apps.get_model("common", "User")
        owner_email = str(data.get("owner_email", "")).strip().lower()
        if not owner_email:
            return Response({
                "detail": "owner_email is required to import a workspace configuration.",
                "code": "workspace_import_owner_required",
            }, status=status.HTTP_400_BAD_REQUEST)
        owner = User.objects.filter(email__iexact=owner_email, is_active=True).first()
        if not owner:
            return Response({
                "detail": "The import owner must be an active user on this Platform.",
                "code": "workspace_import_owner_not_found",
            }, status=status.HTTP_400_BAD_REQUEST)

        cluster_data = data.get("cluster") if isinstance(data.get("cluster"), dict) else {}
        cluster = None
        cluster_id = str(cluster_data.get("id") or "").strip()
        if cluster_id:
            Cluster = apps.get_model("platform", "Cluster")
            try:
                cluster = Cluster.objects.get(pk=cluster_id)
            except Cluster.DoesNotExist:
                return Response({
                    "detail": "The exported Cluster is not available on this Platform.",
                    "code": "workspace_import_cluster_not_found",
                }, status=status.HTTP_409_CONFLICT)

        domains_data = data.get("custom_domains", [])
        if not isinstance(domains_data, list) or len(domains_data) > 20:
            return Response({"detail": "custom_domains must contain at most 20 domains."}, status=status.HTTP_400_BAD_REQUEST)
        custom_domains = []
        for item in domains_data:
            hostname = normalize_hostname(item.get("hostname") if isinstance(item, dict) else item)
            if not hostname:
                return Response({"detail": "A custom domain is invalid."}, status=status.HTTP_400_BAD_REQUEST)
            custom_domains.append(hostname)
        if len(set(custom_domains)) != len(custom_domains):
            return Response({"detail": "Custom domains must be unique."}, status=status.HTTP_400_BAD_REQUEST)
        WorkspaceDomain = apps.get_model("common", "WorkspaceDomain")
        conflicts = list(WorkspaceDomain.objects.filter(hostname__in=custom_domains).values_list("hostname", flat=True))
        if conflicts:
            return Response({
                "detail": "One or more custom domains are already assigned on this Platform.",
                "code": "workspace_import_domain_conflict",
                "domains": conflicts,
            }, status=status.HTTP_409_CONFLICT)

        try:
            workspace = WorkspaceService(user=request.user).create_workspace(
                name=name, slug=slug, owner_user=owner, email=source.get("email", ""),
                phone=source.get("phone", ""), settings=source.get("settings") or {},
                region=(cluster.region if cluster else cluster_data.get("region")) or "us",
                cluster=cluster,
            )
        except WorkspaceCapacityUnavailable as exc:
            return Response(
                {"detail": str(exc), "code": exc.default_code},
                status=status.HTTP_409_CONFLICT,
            )
        WorkspaceDomain.objects.bulk_create([
            WorkspaceDomain(
                workspace=workspace,
                hostname=hostname,
                kind=WorkspaceDomain.KIND_CUSTOM,
                verification_status=WorkspaceDomain.VERIFICATION_PENDING,
                ssl_status=WorkspaceDomain.SSL_NONE,
                is_primary=False,
            )
            for hostname in custom_domains
        ])
        record_platform_audit(
            request=request, action="workspace.imported", target_type="workspace",
            target_id=workspace.id, reason=reason,
            after={"slug": workspace.slug, "cluster_id": workspace.platform_profile.cluster_id, "custom_domains": custom_domains},
        )
        return Response(self._item(workspace), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reset-admin-password")
    def reset_admin_password(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        workspace = self._workspace(pk)
        administrators = self._administrator_users(workspace)
        requested_email = str(request.data.get("email") or "").strip()
        recipient = (
            administrators.filter(email__iexact=requested_email).first()
            if requested_email else administrators.first()
        )
        if not recipient or not recipient.email:
            return Response(
                {"detail": "Choose an active Workspace administrator with an email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        from django.conf import settings
        frontend_url = (getattr(settings, "FRONTEND_URL", "") or getattr(cluster, "frontend_base_url", "")).rstrip("/")
        if not frontend_url:
            return Response({"detail": "Password reset frontend is not configured."}, status=status.HTTP_409_CONFLICT)
        if not UserService.request_password_reset(recipient.email, frontend_url):
            return Response(
                {"detail": "The password reset email could not be sent. Check email delivery settings and try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        record_platform_audit(
            request=request, action="workspace.password_reset_requested", target_type="workspace",
            target_id=workspace.id, reason=reason, after={"administrator_id": recipient.id},
        )
        return Response({"detail": "If the account exists, a password reset email has been sent."})


class PlatformConsoleClusterViewSet(viewsets.ViewSet):
    """Platform-owned cluster inventory and safe operational settings."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]

    _WRITABLE_FIELDS = {
        "name", "region", "api_base_url", "frontend_base_url", "db_host", "db_port",
        "redis_url", "s3_bucket", "max_workspaces", "is_accepting_new", "is_active",
    }

    def _cluster(self, pk):
        Cluster = apps.get_model("platform", "Cluster")
        return Cluster.objects.get(pk=pk)

    def _workspace_count(self, cluster):
        return cluster.workspaces.count()

    def _item(self, cluster):
        workspace_count = self._workspace_count(cluster)
        max_workspaces = cluster.max_workspaces
        capacity_percentage = 100 if max_workspaces == 0 else min(
            100, int((workspace_count / max_workspaces) * 100)
        )
        return {
            "id": cluster.id,
            "name": cluster.name,
            "region": cluster.region,
            "api_base_url": cluster.api_base_url,
            "frontend_base_url": cluster.frontend_base_url,
            "db_host": cluster.db_host,
            "db_port": cluster.db_port,
            # Connection credentials remain write-only even for a superuser browser
            # session. A replacement can be submitted, but a stored secret is never
            # sent back over the API or copied into an audit/client cache.
            "redis_configured": bool(cluster.redis_url),
            "s3_bucket": cluster.s3_bucket,
            "max_workspaces": max_workspaces,
            "config_version": cluster.config_version,
            "workspace_count": workspace_count,
            "capacity_percentage": capacity_percentage,
            "is_accepting_new": cluster.is_accepting_new,
            "is_active": cluster.is_active,
            "health_status": cluster.health_status,
            "last_health_check": cluster.last_health_check,
            "created_at": cluster.created_at,
            "updated_at": cluster.updated_at,
        }

    def _validated_values(self, data, *, creating):
        from rest_framework import serializers

        fields = {key: data[key] for key in self._WRITABLE_FIELDS if key in data}
        if creating:
            fields["id"] = data.get("id")
            required = {
                "id", "name", "region", "api_base_url", "db_host", "redis_url", "s3_bucket",
            }
            missing = sorted(key for key in required if not fields.get(key))
            if missing:
                raise serializers.ValidationError({key: "This field is required." for key in missing})

        if "id" in fields:
            fields["id"] = str(fields["id"]).strip()
            if not fields["id"] or len(fields["id"]) > 32:
                raise serializers.ValidationError({"id": "Use a non-empty identifier of 32 characters or fewer."})

        if "name" in fields:
            fields["name"] = str(fields["name"]).strip()
            if not fields["name"]:
                raise serializers.ValidationError({"name": "This field may not be blank."})

        if "region" in fields and fields["region"] not in {"us", "eu", "apac"}:
            raise serializers.ValidationError({"region": "Choose us, eu, or apac."})

        for key in ("api_base_url", "frontend_base_url"):
            if key in fields and fields[key]:
                value = str(fields[key]).strip()
                if not value.startswith(("http://", "https://")):
                    raise serializers.ValidationError({key: "Use an http:// or https:// URL."})
                fields[key] = value

        if "redis_url" in fields:
            value = str(fields["redis_url"]).strip()
            # Existing deployments historically stored an HTTP health endpoint here.
            # Keep those clusters editable while accepting native Redis URLs for new ones.
            if not value.startswith(("redis://", "rediss://", "http://", "https://")):
                raise serializers.ValidationError({"redis_url": "Use a Redis or HTTP URL."})
            fields["redis_url"] = value

        for key in ("db_port", "max_workspaces"):
            if key in fields:
                try:
                    fields[key] = int(fields[key])
                except (TypeError, ValueError):
                    raise serializers.ValidationError({key: "Use a whole number."})
                if fields[key] < (1 if key == "db_port" else 0):
                    raise serializers.ValidationError({key: "Use a positive value." if key == "db_port" else "Use zero or more."})

        for key in ("is_accepting_new", "is_active"):
            if key in fields and not isinstance(fields[key], bool):
                raise serializers.ValidationError({key: "Use true or false."})

        return fields

    def list(self, request):
        Cluster = apps.get_model("platform", "Cluster")
        return Response([self._item(cluster) for cluster in Cluster.objects.all()])

    def retrieve(self, request, pk=None):
        try:
            return Response(self._item(self._cluster(pk)))
        except apps.get_model("platform", "Cluster").DoesNotExist:
            return Response({"detail": "Cluster not found."}, status=status.HTTP_404_NOT_FOUND)

    def create(self, request):
        _confirmed(request)
        reason = _change_reason(request)
        values = self._validated_values(request.data, creating=True)
        Cluster = apps.get_model("platform", "Cluster")
        if Cluster.objects.filter(pk=values["id"]).exists():
            return Response({"detail": "A cluster with this identifier already exists."}, status=status.HTTP_409_CONFLICT)
        cluster = Cluster.objects.create(**values)
        record_platform_audit(
            request=request, action="cluster.created", target_type="cluster", target_id=cluster.id,
            reason=reason, after=_cluster_snapshot(cluster),
        )
        return Response(self._item(cluster), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        try:
            expected_version = int(request.data.get("expected_version"))
        except (TypeError, ValueError):
            raise ValidationError({"expected_version": "Provide the configuration version you read."})
        if expected_version < 1:
            raise ValidationError({"expected_version": "Use a positive configuration version."})
        try:
            with transaction.atomic():
                Cluster = apps.get_model("platform", "Cluster")
                cluster = Cluster.objects.select_for_update().get(pk=pk)
                if cluster.config_version != expected_version:
                    return Response({
                        "detail": "This Cluster changed while you were editing it. Reload and review the latest configuration.",
                        "code": "cluster_version_conflict",
                        "current_version": cluster.config_version,
                    }, status=status.HTTP_409_CONFLICT)
                values = self._validated_values(request.data, creating=False)
                if values.get("is_accepting_new") is True and values.get("is_active", cluster.is_active) is False:
                    raise ValidationError({"is_accepting_new": "An inactive Cluster cannot accept new workspaces."})
                if values.get("is_active") is False:
                    values["is_accepting_new"] = False
                if "max_workspaces" in values and values["max_workspaces"] < self._workspace_count(cluster):
                    return Response(
                        {"detail": "Capacity cannot be below the number of assigned workspaces."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                before = _cluster_snapshot(cluster)
                for field, value in values.items():
                    setattr(cluster, field, value)
                if values:
                    cluster.config_version += 1
                    cluster.save(update_fields=[*values.keys(), "config_version", "updated_at"])
                    record_platform_audit(
                        request=request, action="cluster.updated", target_type="cluster", target_id=cluster.id,
                        reason=reason, before=before, after=_cluster_snapshot(cluster),
                    )
                return Response(self._item(cluster))
        except apps.get_model("platform", "Cluster").DoesNotExist:
            return Response({"detail": "Cluster not found."}, status=status.HTTP_404_NOT_FOUND)


class PlatformConsoleAuditEventViewSet(viewsets.ViewSet):
    """Read-only, paginated history of sensitive Platform control-plane changes."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]
    _DEFAULT_LIMIT = 50
    _MAX_LIMIT = 100

    @staticmethod
    def _event_item(event):
        """Serialize an event without request metadata or unredacted snapshots."""
        return {
            "id": str(event.id),
            "action": event.action,
            "target": {"type": event.target_type, "id": event.target_id},
            "reason": event.reason,
            "actor": (
                {"id": event.actor_id, "username": event.actor.username}
                if event.actor_id else None
            ),
            "before": redact_platform_audit_value(event.before or {}),
            "after": redact_platform_audit_value(event.after or {}),
            "created_at": event.created_at,
        }

    def _limit(self, request):
        raw_limit = request.query_params.get("limit", self._DEFAULT_LIMIT)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ValidationError({"limit": "Use a whole number between 1 and 100."})
        if not 1 <= limit <= self._MAX_LIMIT:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."})
        return limit

    def _cursor(self, request):
        cursor = request.query_params.get("cursor")
        if not cursor:
            return None
        try:
            payload = signing.loads(cursor, salt="platform-audit-events", max_age=60 * 60 * 24 * 30)
            created_at = dateparse.parse_datetime(payload["created_at"])
            event_id = payload["id"]
        except (KeyError, TypeError, ValueError, signing.BadSignature):
            raise ValidationError({"cursor": "Use a valid audit-event cursor."})
        if not created_at:
            raise ValidationError({"cursor": "Use a valid audit-event cursor."})
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at, timezone.get_current_timezone())
        return created_at, event_id

    @staticmethod
    def _next_cursor(event):
        return signing.dumps(
            {"created_at": event.created_at.isoformat(), "id": str(event.id)},
            salt="platform-audit-events",
        )

    def list(self, request):
        PlatformAuditEvent = apps.get_model("platform", "PlatformAuditEvent")
        events = PlatformAuditEvent.objects.select_related("actor").order_by("-created_at", "-id")
        for field, maximum in (("action", 100), ("target_type", 64), ("target_id", 255)):
            value = (request.query_params.get(field) or "").strip()
            if len(value) > maximum:
                raise ValidationError({field: f"Use {maximum} characters or fewer."})
            if value:
                events = events.filter(**{field: value})

        cursor = self._cursor(request)
        if cursor:
            created_at, event_id = cursor
            events = events.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=event_id))

        limit = self._limit(request)
        page = list(events[:limit + 1])
        has_next = len(page) > limit
        page = page[:limit]
        return Response({
            "results": [self._event_item(event) for event in page],
            "next": self._next_cursor(page[-1]) if has_next and page else None,
        })
