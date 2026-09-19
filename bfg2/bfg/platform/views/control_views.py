# -*- coding: utf-8 -*-
"""Django-superuser-only Platform control-plane endpoints.

This module deliberately does not share the owner console route. The owner
console remains tenant-scoped; these endpoints manage deployment lifecycle and
infrastructure and always require a Django superuser.
"""
import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.apps import apps
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bfg.common.models import normalize_hostname
from bfg.common.extensions import registry
from bfg.common.services.user_service import UserService
from bfg.common.services.workspace_service import WorkspaceService
from bfg.platform.permissions import IsPlatformSuperuser
from bfg.platform.services.cluster_health import (
    ClusterHealthProbeConfigurationError,
    probe_cluster_health,
)
from bfg.platform.services.control_actions import (
    claim_action,
    complete_action,
    require_confirmation,
    require_reason,
)
from bfg.platform.services.control_audit import record_control_audit, redact_control_value
from bfg.platform.services.provision_service import resume_workspace, suspend_workspace
from bfg.platform.services import console_admin, entitlements, exchange_rates, pricing, usage
from bfg.platform.services import platform_variables as variables
from bfg.platform.utils import is_embedded_mode, is_platform_workspace
from bfg.platform.views.console_admin_views import _body, _day, _limit, _moment
from config.authentication import BearerTokenAuthentication


class PlatformControlAccessViewSet(viewsets.ViewSet):
    """Authentication and authorization shared by every control-plane route."""

    authentication_classes = [BearerTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, IsPlatformSuperuser]


class PlatformControlStatusViewSet(PlatformControlAccessViewSet):
    """A small, protected capability document for Platform navigation.

    The established ``/workspaces/me/`` payload is intentionally unchanged so
    existing workspace clients keep their exact contract. A successful status
    response is itself proof that the caller is a Django superuser; every
    mutating control endpoint still authorizes independently.
    """

    def list(self, request):
        return Response({
            "is_platform_superuser": True,
            "platform_capabilities": {
                "cluster_management": True,
                "audit_log": True,
                "configuration": True,
                "exchange_rates": True,
            },
        })


def _workspace_or_404(pk):
    Workspace = apps.get_model("common", "Workspace")
    try:
        return Workspace.objects.select_related("platform_profile__cluster").get(pk=pk)
    except (Workspace.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404 from exc


def _owner_users(workspace):
    User = apps.get_model("common", "User")
    if is_embedded_mode():
        StaffMember = apps.get_model("common", "StaffMember")
        ids = StaffMember.all_objects.filter(
            workspace=workspace, is_active=True, role__code__in=["admin", "owner"],
        ).values_list("user_id", flat=True)
    else:
        PlatformMembership = apps.get_model("platform", "PlatformMembership")
        ids = PlatformMembership.objects.filter(
            profile__workspace=workspace, is_active=True, role="owner",
        ).values_list("user_id", flat=True)
    return User.objects.filter(id__in=ids, is_active=True).order_by("id")


def _user_item(user):
    return {"id": user.id, "username": user.username, "email": user.email or None} if user else None


def _workspace_item(workspace, *, viewer=None):
    profile = getattr(workspace, "platform_profile", None)
    cluster = getattr(profile, "cluster", None) if profile else None
    owner = _owner_users(workspace).first()
    StaffMember = apps.get_model("common", "StaffMember")
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "is_active": workspace.is_active,
        "is_platform": is_platform_workspace(workspace),
        "suspended_at": profile.suspended_at if profile and profile.suspended_at else None,
        "scheduled_deletion_at": (
            profile.scheduled_deletion_at if profile and profile.scheduled_deletion_at else None
        ),
        "created_at": workspace.created_at,
        "domains": list(workspace.domains.values_list("hostname", flat=True)),
        "owner": _user_item(owner),
        "owned_by_viewer": bool(viewer and owner and owner.pk == viewer.pk),
        "staff_count": StaffMember.all_objects.filter(workspace=workspace, is_active=True).count(),
        "active_extensions": [],
        "cluster": (
            {"id": cluster.id, "name": cluster.name, "region": cluster.region, "is_active": cluster.is_active}
            if cluster else None
        ),
        "capabilities": {"extension_management": False, "usage": True},
    }


class PlatformControlWorkspaceViewSet(PlatformControlAccessViewSet):
    """Superuser lifecycle controls for every Workspace in the deployment."""

    class Pagination(LimitOffsetPagination):
        default_limit = 100
        max_limit = 500
        limit_query_param = "page_size"

    _STATUSES = {"active", "suspended", "inactive"}

    def list(self, request):
        Workspace = apps.get_model("common", "Workspace")
        queryset = Workspace.objects.select_related("platform_profile__cluster").order_by("-created_at")
        term = (request.query_params.get("search") or "").strip()
        if term:
            queryset = queryset.filter(Q(name__icontains=term) | Q(slug__icontains=term))
        requested_status = (request.query_params.get("status") or "").strip()
        if requested_status:
            if requested_status not in self._STATUSES:
                raise ValidationError({"status": "Use active, suspended, or inactive."})
            if requested_status == "active":
                queryset = queryset.filter(is_active=True, platform_profile__suspended_at__isnull=True)
            elif requested_status == "suspended":
                queryset = queryset.filter(platform_profile__suspended_at__isnull=False)
            else:
                queryset = queryset.filter(is_active=False, platform_profile__suspended_at__isnull=True)
        cluster_id = (request.query_params.get("cluster") or "").strip()
        if len(cluster_id) > 32:
            raise ValidationError({"cluster": "Use a Cluster ID of 32 characters or fewer."})
        if cluster_id:
            queryset = queryset.filter(platform_profile__cluster_id=cluster_id)
        paginator = self.Pagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([_workspace_item(workspace, viewer=request.user) for workspace in page])

    def retrieve(self, request, pk=None):
        workspace = _workspace_or_404(pk)
        payload = _workspace_item(workspace, viewer=request.user)
        payload.update({
            "email": workspace.email,
            "phone": workspace.phone,
            "settings": workspace.settings or {},
            "extensions": [],
        })
        return Response(payload)

    @action(detail=True, methods=["get"])
    def operations(self, request, pk=None):
        workspace = _workspace_or_404(pk)
        try:
            limit = int(request.query_params.get("limit", 20))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."}) from exc
        if not 1 <= limit <= 100:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."})
        WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")
        operations = WorkspaceOperation.objects.filter(workspace=workspace).select_related("initiated_by")[:limit]
        return Response([
            {
                "id": str(operation.id),
                "operation": operation.operation,
                "status": operation.status,
                "initiated_by": _user_item(operation.initiated_by),
                "details": redact_control_value(operation.details or {}),
                "error": "Operation failed. Inspect secured server logs." if operation.status == "failed" else None,
                "started_at": operation.started_at,
                "completed_at": operation.completed_at,
            }
            for operation in operations
        ])

    def _lifecycle(self, request, pk, *, action_name, operation):
        require_confirmation(request)
        reason = require_reason(request)
        workspace = _workspace_or_404(pk)
        action_request, replay = claim_action(
            request,
            action=f"workspace.{action_name}",
            target_type="workspace",
            target_id=workspace.id,
            payload={"reason": reason},
        )
        if replay is not None:
            return replay
        Workspace = apps.get_model("common", "Workspace")
        with transaction.atomic():
            workspace = Workspace.objects.select_for_update().select_related("platform_profile__cluster").get(pk=workspace.pk)
            profile = getattr(workspace, "platform_profile", None)
            before = {"is_active": workspace.is_active, "suspended_at": profile.suspended_at if profile else None}
            if action_name == "resume":
                operation(workspace, initiated_by=request.user)
            else:
                operation(workspace, initiated_by=request.user, reason=reason)
            payload = _workspace_item(workspace, viewer=request.user)
            profile = getattr(workspace, "platform_profile", None)
            complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=payload)
            record_control_audit(
                request=request, action=f"workspace.{action_name}", target_type="workspace",
                target_id=workspace.id, reason=reason, before=before,
                after={"is_active": workspace.is_active, "suspended_at": profile.suspended_at if profile else None},
            )
        return Response(payload)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._lifecycle(request, pk, action_name="suspend", operation=suspend_workspace)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._lifecycle(request, pk, action_name="resume", operation=resume_workspace)

    @action(detail=True, methods=["post"])
    def delete(self, request, pk=None):
        """Schedule a recoverable deletion; it never removes tenant data."""
        require_confirmation(request)
        reason = require_reason(request)
        workspace = _workspace_or_404(pk)
        action_request, replay = claim_action(
            request, action="workspace.deletion_scheduled", target_type="workspace", target_id=workspace.id,
            payload={"reason": reason},
        )
        if replay is not None:
            return replay
        Workspace = apps.get_model("common", "Workspace")
        WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
        WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")
        with transaction.atomic():
            workspace = Workspace.objects.select_for_update().select_related("platform_profile__cluster").get(pk=workspace.pk)
            profile, _ = WorkspacePlatformProfile.objects.get_or_create(workspace=workspace)
            if not profile.scheduled_deletion_at:
                before = {"is_active": workspace.is_active, "scheduled_deletion_at": None}
                workspace.is_active = False
                workspace.save(update_fields=["is_active"])
                profile.scheduled_deletion_at = timezone.now() + timedelta(days=30)
                profile.save(update_fields=["scheduled_deletion_at", "updated_at"])
                WorkspaceOperation.objects.create(
                    workspace=workspace, operation="delete", status="completed", initiated_by=request.user,
                    details={"soft": True, "reason": reason}, completed_at=timezone.now(),
                )
                record_control_audit(
                    request=request, action="workspace.deletion_scheduled", target_type="workspace",
                    target_id=workspace.id, reason=reason, before=before,
                    after={"is_active": False, "scheduled_deletion_at": profile.scheduled_deletion_at},
                )
            workspace = _workspace_or_404(workspace.pk)
            payload = _workspace_item(workspace, viewer=request.user)
            complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=payload)
        return Response(payload)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        require_confirmation(request)
        reason = require_reason(request)
        workspace = _workspace_or_404(pk)
        action_request, replay = claim_action(
            request, action="workspace.deletion_cancelled", target_type="workspace", target_id=workspace.id,
            payload={"reason": reason},
        )
        if replay is not None:
            return replay
        Workspace = apps.get_model("common", "Workspace")
        with transaction.atomic():
            workspace = Workspace.objects.select_for_update().select_related("platform_profile__cluster").get(pk=workspace.pk)
            profile = getattr(workspace, "platform_profile", None)
            if not profile or not profile.scheduled_deletion_at:
                body = {"detail": "This workspace is not scheduled for deletion.", "code": "workspace_not_scheduled_for_deletion"}
                complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
                return Response(body, status=status.HTTP_409_CONFLICT)
            before = {"is_active": workspace.is_active, "scheduled_deletion_at": profile.scheduled_deletion_at}
            resume_workspace(workspace, initiated_by=request.user)
            profile.scheduled_deletion_at = None
            profile.save(update_fields=["scheduled_deletion_at", "updated_at"])
            payload = _workspace_item(workspace, viewer=request.user)
            complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=payload)
            record_control_audit(
                request=request, action="workspace.deletion_cancelled", target_type="workspace",
                target_id=workspace.id, reason=reason, before=before,
                after={"is_active": workspace.is_active, "scheduled_deletion_at": None},
            )
        return Response(payload)

    @action(detail=True, methods=["get", "patch"], url_path="usage-cap")
    def usage_cap(self, request, pk=None):
        """Read or change one Workspace's enforced monthly metering allowance."""
        workspace = _workspace_or_404(pk)
        if request.method == "GET":
            return Response(console_admin.usage_cap_entry(workspace))
        require_confirmation(request)
        data = _body(request)
        if "cap_points" not in data:
            raise ValidationError({"code": usage.InvalidUsageCap.default_code, "detail": "Send cap_points or null to follow the default."})
        reason = require_reason(request)
        action_request, replay = claim_action(
            request, action="workspace.usage_cap_updated", target_type="workspace", target_id=workspace.id,
            payload={"cap_points": data["cap_points"], "reason": reason},
        )
        if replay is not None:
            return replay
        before = console_admin.usage_cap_entry(workspace)
        try:
            body = console_admin.set_usage_cap(workspace, data["cap_points"])
        except usage.InvalidUsageCap as exc:
            body = {"code": exc.code, "detail": exc.message}
            complete_action(action_request, result="failed", response_status=status.HTTP_400_BAD_REQUEST, response_body=body)
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=body)
        record_control_audit(
            request=request, action="workspace.usage_cap_updated", target_type="workspace",
            target_id=workspace.id, reason=reason, before=before, after=body,
        )
        return Response(body)

    @staticmethod
    def _entitlement_item(workspace, row):
        return {
            "id": row.pk,
            "key": row.key,
            "status": row.status,
            "source": row.source,
            "starts_at": row.starts_at,
            "current_period_end": row.current_period_end,
            "reason": row.reason,
            "is_effective": entitlements.is_entitled(workspace, row.key),
        }

    @staticmethod
    def _grant_key(data):
        key = data.get("key")
        if not isinstance(key, str):
            raise ValidationError({"code": "invalid_grant", "detail": "Send an extension key, or an empty key for the base plan."})
        key = key.strip()
        if not console_admin.extension_key_exists(key):
            raise ValidationError({"code": console_admin.UNKNOWN_EXTENSION, "detail": f"No extension named {key}."})
        return key

    @staticmethod
    def _grant_months(data):
        months, never = data.get("months"), data.get("never_expires")
        if never not in (None, True, False) or bool(never) == (months is not None):
            raise ValidationError({"code": "invalid_grant", "detail": "Choose a finite term or never expires."})
        if never:
            return None
        if isinstance(months, bool) or not isinstance(months, int) or not 1 <= months <= 120:
            raise ValidationError({"code": "invalid_grant", "detail": "months must be a whole number from 1 to 120."})
        return months

    @action(detail=True, methods=["get"], url_path="grants/available-features")
    def available_grant_features(self, request, pk=None):
        _workspace_or_404(pk)
        return Response({"features": sorted(
            manifest.key for manifest in registry.all_manifests()
            if manifest.is_activatable and manifest.key
        )})

    @action(detail=True, methods=["get", "post"], url_path="grants")
    def grants(self, request, pk=None):
        workspace = _workspace_or_404(pk)
        WorkspaceEntitlement = apps.get_model("platform", "WorkspaceEntitlement")
        if request.method == "GET":
            rows = WorkspaceEntitlement.all_objects.filter(workspace=workspace).order_by("-created_at", "-id")
            return Response([self._entitlement_item(workspace, row) for row in rows])
        require_confirmation(request)
        data = _body(request)
        key = self._grant_key(data)
        months = self._grant_months(data)
        reason = require_reason(request)
        action_request, replay = claim_action(
            request, action="workspace.entitlement_granted", target_type="workspace", target_id=workspace.id,
            payload={"key": key, "months": months, "reason": reason},
        )
        if replay is not None:
            return replay
        try:
            granted = console_admin.grant_entitlement(workspace, key, months=months, reason=reason, user=request.user)
        except console_admin.AlreadyEntitled as exc:
            body = {"code": exc.code, "detail": exc.message, **exc.details}
            complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
            return Response(body, status=status.HTTP_409_CONFLICT)
        entitlement = granted["entitlement"]
        body = {"workspace": workspace.id, "entitlement": {**entitlement, "is_effective": True}}
        complete_action(action_request, result="succeeded", response_status=status.HTTP_201_CREATED, response_body=body)
        record_control_audit(
            request=request, action="workspace.entitlement_granted", target_type="workspace",
            target_id=workspace.id, reason=reason, after=body,
        )
        return Response(body, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path=r"grants/(?P<grant_id>[0-9]+)/revoke")
    def revoke_grant(self, request, pk=None, grant_id=None):
        """End a granted entitlement while preserving both it and its audit trail."""
        require_confirmation(request)
        reason = require_reason(request)
        workspace = _workspace_or_404(pk)
        WorkspaceEntitlement = apps.get_model("platform", "WorkspaceEntitlement")
        try:
            entitlement = WorkspaceEntitlement.all_objects.get(pk=grant_id, workspace=workspace)
        except WorkspaceEntitlement.DoesNotExist as exc:
            raise Http404 from exc
        action_request, replay = claim_action(
            request, action="workspace.entitlement_revoked", target_type="workspace_entitlement", target_id=entitlement.id,
            payload={"workspace": workspace.id, "reason": reason},
        )
        if replay is not None:
            return replay
        with transaction.atomic():
            entitlement = WorkspaceEntitlement.all_objects.select_for_update().get(pk=entitlement.pk)
            before = self._entitlement_item(workspace, entitlement)
            if entitlement.status != WorkspaceEntitlement.STATUS_ENDED:
                entitlement.status = WorkspaceEntitlement.STATUS_ENDED
                entitlement.ended_reason = reason
                entitlement.save(update_fields=["status", "ended_reason", "updated_at"])
            body = {"workspace": workspace.id, "entitlement": self._entitlement_item(workspace, entitlement)}
            complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=body)
            record_control_audit(
                request=request, action="workspace.entitlement_revoked", target_type="workspace",
                target_id=workspace.id, reason=reason, before={"entitlement": before}, after=body,
            )
        return Response(body)

    @action(detail=True, methods=["post"])
    def export(self, request, pk=None):
        """Export configuration only, never members, business data, media, or secrets."""
        require_confirmation(request)
        reason = require_reason(request)
        workspace = _workspace_or_404(pk)
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        owner = _owner_users(workspace).first()
        data = {
            "format": "idlevo-workspace-v1",
            "scope": "configuration-template",
            "does_not_include": ["members", "business_data", "media", "credentials"],
            "workspace": {"name": workspace.name, "slug": workspace.slug, "email": workspace.email,
                          "phone": workspace.phone, "settings": workspace.settings or {}},
            "owner_email": owner.email if owner and owner.email else None,
            "cluster": {"id": cluster.id, "name": cluster.name, "region": cluster.region} if cluster else None,
            "custom_domains": list(workspace.domains.filter(kind="custom").values("hostname")),
            "exported_at": timezone.now().isoformat(),
        }
        record_control_audit(
            request=request, action="workspace.exported", target_type="workspace", target_id=workspace.id,
            reason=reason, after={"format": data["format"], "scope": data["scope"]},
        )
        response = HttpResponse(json.dumps(data, indent=2, default=str), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="workspace-{workspace.slug}.json"'
        return response

    @action(detail=False, methods=["post"], url_path="import-workspace")
    def import_workspace(self, request):
        """Import only a reviewed configuration template into a new Workspace."""
        require_confirmation(request)
        reason = require_reason(request)
        data = request.data if isinstance(request.data, dict) else {}
        if data.get("format") not in (None, "", "idlevo-workspace-v1"):
            return Response(
                {"detail": "This is not a supported Idlevo workspace configuration export.", "code": "unsupported_workspace_import_format"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        source = data.get("workspace", data)
        if not isinstance(source, dict):
            return Response({"detail": "workspace must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        name = str(source.get("name") or "").strip()
        if not name:
            return Response({"detail": "workspace.name is required."}, status=status.HTTP_400_BAD_REQUEST)
        owner_email = str(data.get("owner_email") or "").strip().lower()
        if not owner_email:
            return Response(
                {"detail": "owner_email is required to import a workspace configuration.", "code": "workspace_import_owner_required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        User = apps.get_model("common", "User")
        owner = User.objects.filter(email__iexact=owner_email, is_active=True).first()
        if not owner:
            return Response(
                {"detail": "The import owner must be an active user on this Platform.", "code": "workspace_import_owner_not_found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cluster_data = data.get("cluster") if isinstance(data.get("cluster"), dict) else {}
        cluster_id = str(cluster_data.get("id") or "").strip()
        cluster = None
        if cluster_id:
            Cluster = apps.get_model("platform", "Cluster")
            cluster = Cluster.objects.filter(pk=cluster_id).first()
            if not cluster:
                return Response(
                    {"detail": "The exported Cluster is not available on this Platform.", "code": "workspace_import_cluster_not_found"},
                    status=status.HTTP_409_CONFLICT,
                )
        raw_domains = data.get("custom_domains", [])
        if not isinstance(raw_domains, list) or len(raw_domains) > 20:
            return Response({"detail": "custom_domains must contain at most 20 domains."}, status=status.HTTP_400_BAD_REQUEST)
        domains = []
        for item in raw_domains:
            hostname = normalize_hostname(item.get("hostname") if isinstance(item, dict) else item)
            if not hostname:
                return Response({"detail": "A custom domain is invalid."}, status=status.HTTP_400_BAD_REQUEST)
            domains.append(hostname)
        if len(set(domains)) != len(domains):
            return Response({"detail": "Custom domains must be unique."}, status=status.HTTP_400_BAD_REQUEST)
        Workspace = apps.get_model("common", "Workspace")
        WorkspaceDomain = apps.get_model("common", "WorkspaceDomain")
        slug = str(source.get("slug") or "").strip() or None
        action_request, replay = claim_action(
            request, action="workspace.imported", target_type="workspace", target_id="new",
            payload={
                "workspace": source, "owner_id": owner.id, "cluster_id": cluster_id or None,
                "custom_domains": domains, "reason": reason,
            },
        )
        if replay is not None:
            return replay
        with transaction.atomic():
            if slug and Workspace.objects.filter(slug=slug).exists():
                body = {"detail": "A workspace with this slug already exists."}
                complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
                return Response(body, status=status.HTTP_409_CONFLICT)
            conflicts = list(WorkspaceDomain.objects.filter(hostname__in=domains).values_list("hostname", flat=True))
            if conflicts:
                body = {"detail": "One or more custom domains are already assigned on this Platform.", "code": "workspace_import_domain_conflict", "domains": conflicts}
                complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
                return Response(body, status=status.HTTP_409_CONFLICT)
            workspace = WorkspaceService(user=request.user).create_workspace(
                name=name,
                slug=slug,
                owner_user=owner,
                email=source.get("email", ""),
                phone=source.get("phone", ""),
                settings=source.get("settings") or {},
                region=cluster.region if cluster else str(cluster_data.get("region") or "us"),
                cluster=cluster,
            )
            WorkspaceDomain.objects.bulk_create([
                WorkspaceDomain(
                    workspace=workspace, hostname=hostname, kind=WorkspaceDomain.KIND_CUSTOM,
                    verification_status=WorkspaceDomain.VERIFICATION_PENDING,
                    ssl_status=WorkspaceDomain.SSL_NONE, is_primary=False,
                )
                for hostname in domains
            ])
            workspace = _workspace_or_404(workspace.pk)
            body = _workspace_item(workspace, viewer=request.user)
            complete_action(action_request, result="succeeded", response_status=status.HTTP_201_CREATED, response_body=body)
            record_control_audit(
                request=request, action="workspace.imported", target_type="workspace", target_id=workspace.id,
                reason=reason, after={"slug": workspace.slug, "cluster_id": cluster_id or None, "custom_domains": domains},
            )
        return Response(body, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reset-admin-password")
    def reset_admin_password(self, request, pk=None):
        require_confirmation(request)
        reason = require_reason(request)
        workspace = _workspace_or_404(pk)
        requested_email = str(request.data.get("email") or "").strip()
        administrators = _owner_users(workspace)
        recipient = administrators.filter(email__iexact=requested_email).first() if requested_email else administrators.first()
        if not recipient or not recipient.email:
            return Response({"detail": "Choose an active Workspace administrator with an email address."}, status=status.HTTP_400_BAD_REQUEST)
        frontend_url = str(getattr(settings, "FRONTEND_URL", "")).rstrip("/")
        if not frontend_url:
            return Response({"detail": "Password reset frontend is not configured."}, status=status.HTTP_409_CONFLICT)
        action_request, replay = claim_action(
            request, action="workspace.password_reset_requested", target_type="workspace", target_id=workspace.id,
            payload={"administrator_id": recipient.id, "frontend_url": frontend_url, "reason": reason},
        )
        if replay is not None:
            return replay
        delivered = UserService.request_password_reset(recipient.email, frontend_url)
        if not delivered:
            body = {"detail": "The password reset email could not be sent. Check email delivery settings and try again."}
            complete_action(action_request, result="failed", response_status=status.HTTP_503_SERVICE_UNAVAILABLE, response_body=body)
            record_control_audit(
                request=request, action="workspace.password_reset_requested", target_type="workspace",
                target_id=workspace.id, reason=reason, after={"administrator_id": recipient.id}, result="failed",
            )
            return Response(body, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        body = {"detail": "If the account exists, a password reset email has been sent."}
        complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=body)
        record_control_audit(
            request=request, action="workspace.password_reset_requested", target_type="workspace",
            target_id=workspace.id, reason=reason, after={"administrator_id": recipient.id},
        )
        return Response(body)


def _cluster_snapshot(cluster):
    return {
        "id": cluster.id, "name": cluster.name, "region": cluster.region,
        "api_base_url": cluster.api_base_url, "frontend_base_url": cluster.frontend_base_url,
        "db_host": cluster.db_host, "db_port": cluster.db_port,
        "redis_configured": bool(cluster.redis_url), "s3_bucket": cluster.s3_bucket,
        "max_workspaces": cluster.max_workspaces, "is_accepting_new": cluster.is_accepting_new,
        "is_active": cluster.is_active, "config_version": cluster.config_version,
    }


class PlatformControlClusterViewSet(PlatformControlAccessViewSet):
    """Cluster inventory and guarded configuration changes for superusers."""

    _WRITABLE = {
        "name", "region", "api_base_url", "frontend_base_url", "db_host", "db_port", "redis_url",
        "s3_bucket", "max_workspaces", "is_accepting_new", "is_active",
    }

    @staticmethod
    def _item(cluster):
        count = cluster.workspaces.count()
        capacity = 100 if cluster.max_workspaces == 0 else min(100, int((count / cluster.max_workspaces) * 100))
        return {
            **_cluster_snapshot(cluster), "workspace_count": count, "capacity_percentage": capacity,
            "health_status": cluster.health_status, "last_health_check": cluster.last_health_check,
            "created_at": cluster.created_at, "updated_at": cluster.updated_at,
        }

    @staticmethod
    def _cluster(pk):
        Cluster = apps.get_model("platform", "Cluster")
        try:
            return Cluster.objects.get(pk=pk)
        except Cluster.DoesNotExist as exc:
            raise Http404 from exc

    def _values(self, data, *, creating):
        if not isinstance(data, dict):
            raise ValidationError({"detail": "Send the change as a JSON object."})
        values = {key: data[key] for key in self._WRITABLE if key in data}
        if creating:
            values["id"] = str(data.get("id") or "").strip()
            required = {"id", "name", "region", "api_base_url", "db_host", "redis_url", "s3_bucket"}
            missing = sorted(key for key in required if not values.get(key))
            if missing:
                raise ValidationError({key: "This field is required." for key in missing})
        if "id" in values and (not values["id"] or len(values["id"]) > 32):
            raise ValidationError({"id": "Use a non-empty identifier of 32 characters or fewer."})
        if "name" in values:
            values["name"] = str(values["name"]).strip()
            if not values["name"]:
                raise ValidationError({"name": "This field may not be blank."})
        if "region" in values and values["region"] not in {"us", "eu", "apac"}:
            raise ValidationError({"region": "Choose us, eu, or apac."})
        for key in ("api_base_url", "frontend_base_url"):
            if key in values and values[key]:
                value = str(values[key]).strip()
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    raise ValidationError({key: "Use an absolute http:// or https:// URL without credentials."})
                values[key] = value
        if "redis_url" in values:
            value = str(values["redis_url"]).strip()
            if not value.startswith(("redis://", "rediss://", "http://", "https://")):
                raise ValidationError({"redis_url": "Use a Redis or HTTP URL."})
            values["redis_url"] = value
        for key, minimum in (("db_port", 1), ("max_workspaces", 0)):
            if key in values:
                try:
                    values[key] = int(values[key])
                except (TypeError, ValueError) as exc:
                    raise ValidationError({key: "Use a whole number."}) from exc
                if values[key] < minimum:
                    raise ValidationError({key: "Use a positive value." if minimum else "Use zero or more."})
        for key in ("is_accepting_new", "is_active"):
            if key in values and not isinstance(values[key], bool):
                raise ValidationError({key: "Use true or false."})
        return values

    def list(self, request):
        Cluster = apps.get_model("platform", "Cluster")
        return Response([self._item(cluster) for cluster in Cluster.objects.all()])

    def retrieve(self, request, pk=None):
        return Response(self._item(self._cluster(pk)))

    @action(detail=True, methods=["get"], url_path="health-observations")
    def health_observations(self, request, pk=None):
        """Return recent server-side probe results without response bodies."""
        try:
            limit = int(request.query_params.get("limit", 20))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."}) from exc
        if not 1 <= limit <= 100:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."})
        cluster = self._cluster(pk)
        Observation = apps.get_model("platform", "ClusterHealthObservation")
        rows = Observation.objects.filter(cluster=cluster).select_related("observed_by")[:limit]
        return Response([
            {
                "id": row.id,
                "health_status": row.health_status,
                "http_status": row.http_status,
                "outcome": row.outcome,
                "observed_at": row.observed_at,
            }
            for row in rows
        ])

    def create(self, request):
        require_confirmation(request)
        reason = require_reason(request)
        values = self._values(request.data, creating=True)
        action_request, replay = claim_action(
            request, action="cluster.created", target_type="cluster", target_id=values["id"],
            payload={"values": values, "reason": reason},
        )
        if replay is not None:
            return replay
        Cluster = apps.get_model("platform", "Cluster")
        with transaction.atomic():
            if Cluster.objects.filter(pk=values["id"]).exists():
                body = {"detail": "A cluster with this identifier already exists."}
                complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
                return Response(body, status=status.HTTP_409_CONFLICT)
            cluster = Cluster.objects.create(**values)
            body = self._item(cluster)
            complete_action(action_request, result="succeeded", response_status=status.HTTP_201_CREATED, response_body=body)
            record_control_audit(
                request=request, action="cluster.created", target_type="cluster", target_id=cluster.id,
                reason=reason, after=_cluster_snapshot(cluster),
            )
        return Response(body, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        require_confirmation(request)
        reason = require_reason(request)
        try:
            expected_version = int(request.data.get("expected_version"))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"expected_version": "Provide the configuration version you read."}) from exc
        if expected_version < 1:
            raise ValidationError({"expected_version": "Use a positive configuration version."})
        values = self._values(request.data, creating=False)
        action_request, replay = claim_action(
            request, action="cluster.updated", target_type="cluster", target_id=pk,
            payload={"expected_version": expected_version, "values": values, "reason": reason},
        )
        if replay is not None:
            return replay
        Cluster = apps.get_model("platform", "Cluster")
        with transaction.atomic():
            try:
                cluster = Cluster.objects.select_for_update().get(pk=pk)
            except Cluster.DoesNotExist as exc:
                raise Http404 from exc
            if cluster.config_version != expected_version:
                body = {"detail": "This Cluster changed while you were editing it. Reload and review the latest configuration.", "code": "cluster_version_conflict", "current_version": cluster.config_version}
                complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
                return Response(body, status=status.HTTP_409_CONFLICT)
            if values.get("is_accepting_new") is True and values.get("is_active", cluster.is_active) is False:
                raise ValidationError({"is_accepting_new": "An inactive Cluster cannot accept new workspaces."})
            if values.get("is_active") is False:
                values["is_accepting_new"] = False
            if "max_workspaces" in values and values["max_workspaces"] < cluster.workspaces.count():
                body = {"detail": "Capacity cannot be below the number of assigned workspaces."}
                complete_action(action_request, result="failed", response_status=status.HTTP_400_BAD_REQUEST, response_body=body)
                return Response(body, status=status.HTTP_400_BAD_REQUEST)
            before = _cluster_snapshot(cluster)
            for field, value in values.items():
                setattr(cluster, field, value)
            if values:
                cluster.config_version += 1
                cluster.save(update_fields=[*values.keys(), "config_version", "updated_at"])
                record_control_audit(
                    request=request, action="cluster.updated", target_type="cluster", target_id=cluster.id,
                    reason=reason, before=before, after=_cluster_snapshot(cluster),
                )
            body = self._item(cluster)
            complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=body)
        return Response(body)

    @action(detail=True, methods=["post"], url_path="health-check")
    def health_check(self, request, pk=None):
        """Run the restricted server-side probe for this Cluster."""
        require_confirmation(request)
        reason = require_reason(request)
        cluster = self._cluster(pk)
        action_request, replay = claim_action(
            request, action="cluster.health_checked", target_type="cluster", target_id=cluster.id,
            payload={"config_version": cluster.config_version, "reason": reason},
        )
        if replay is not None:
            return replay
        try:
            probe = probe_cluster_health(cluster)
        except ClusterHealthProbeConfigurationError:
            body = {"detail": "Cluster health probes are not configured for this endpoint.", "code": "cluster_health_probe_unavailable"}
            Cluster = apps.get_model("platform", "Cluster")
            Observation = apps.get_model("platform", "ClusterHealthObservation")
            with transaction.atomic():
                locked = Cluster.objects.select_for_update().get(pk=cluster.pk)
                Observation.objects.create(
                    cluster=locked, health_status="unknown", outcome="configuration_unavailable",
                    observed_by=request.user,
                )
                complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
                record_control_audit(
                    request=request, action="cluster.health_checked", target_type="cluster", target_id=locked.id,
                    reason=reason, after={"outcome": "configuration_unavailable"}, result="failed",
                )
            return Response(body, status=status.HTTP_409_CONFLICT)
        Cluster = apps.get_model("platform", "Cluster")
        Observation = apps.get_model("platform", "ClusterHealthObservation")
        with transaction.atomic():
            locked = Cluster.objects.select_for_update().get(pk=cluster.pk)
            if locked.config_version != cluster.config_version:
                body = {"detail": "This Cluster changed while its health check was running. Reload and try again.", "code": "cluster_version_conflict", "current_version": locked.config_version}
                Observation.objects.create(
                    cluster=locked, health_status=probe.health_status, http_status=probe.http_status,
                    outcome="configuration_changed", observed_by=request.user,
                )
                complete_action(action_request, result="failed", response_status=status.HTTP_409_CONFLICT, response_body=body)
                record_control_audit(
                    request=request, action="cluster.health_checked", target_type="cluster", target_id=locked.id,
                    reason=reason, after={"outcome": "configuration_changed"}, result="failed",
                )
                return Response(body, status=status.HTTP_409_CONFLICT)
            before = {"health_status": locked.health_status, "last_health_check": locked.last_health_check}
            locked.health_status = probe.health_status
            locked.last_health_check = timezone.now()
            locked.save(update_fields=["health_status", "last_health_check", "updated_at"])
            Observation.objects.create(
                cluster=locked, health_status=probe.health_status, http_status=probe.http_status,
                observed_by=request.user,
            )
            body = self._item(locked)
            complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=body)
            record_control_audit(
                request=request, action="cluster.health_checked", target_type="cluster", target_id=locked.id,
                reason=reason, before=before,
                after={"health_status": locked.health_status, "last_health_check": locked.last_health_check, "http_status": probe.http_status},
            )
        return Response(body)


class PlatformControlVariableViewSet(PlatformControlAccessViewSet):
    """Audited deployment variables, without reusing the historical console route."""

    lookup_field = "key"
    lookup_value_regex = r"[a-z][a-z0-9_]*"

    def list(self, request):
        return Response(console_admin.variable_entries())

    def partial_update(self, request, key=None):
        require_confirmation(request)
        data = _body(request)
        if "value" not in data:
            raise ValidationError({"code": variables.InvalidPlatformVariable.default_code, "detail": "Send the new value with a reason."})
        reason = require_reason(request)
        try:
            before = console_admin.variable_entry(key)
        except variables.UnknownPlatformVariable as exc:
            return Response({"code": exc.code, "detail": exc.message}, status=status.HTTP_404_NOT_FOUND)
        action_request, replay = claim_action(
            request, action="configuration.variable_updated", target_type="platform_variable", target_id=key,
            payload={"value": data["value"], "reason": reason},
        )
        if replay is not None:
            return replay
        try:
            entry = console_admin.change_variable(key, data["value"], user=request.user, reason=reason)
        except variables.InvalidPlatformVariable as exc:
            body = {"code": exc.code, "detail": exc.message}
            complete_action(action_request, result="failed", response_status=status.HTTP_400_BAD_REQUEST, response_body=body)
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        body = entry
        complete_action(action_request, result="succeeded", response_status=status.HTTP_200_OK, response_body=body)
        record_control_audit(
            request=request, action="configuration.variable_updated", target_type="platform_variable",
            target_id=key, reason=reason, before=before, after=entry,
        )
        return Response(body)


class PlatformControlMeterPriceViewSet(PlatformControlAccessViewSet):
    """Append-only, idempotent meter pricing with a durable audit reason."""

    def list(self, request):
        return Response(console_admin.meter_price_entries(request.query_params.get("meter")))

    def create(self, request):
        require_confirmation(request)
        data = _body(request)
        reason = require_reason(request)
        for field in ("meter", "vendor_cost", "unit_size"):
            if data.get(field) in (None, ""):
                raise ValidationError({"code": pricing.InvalidMeterPrice.default_code, "detail": f"{field} is required to price a meter.", "field": field})
        meter = str(data["meter"]).strip()
        effective_from = _moment(data.get("effective_from"), "effective_from", pricing.InvalidMeterPrice.default_code)
        action_request, replay = claim_action(
            request, action="configuration.meter_price_added", target_type="meter", target_id=meter,
            payload={
                "vendor_cost": data["vendor_cost"], "unit_size": data["unit_size"],
                "margin": data.get("margin"), "effective_from": effective_from, "reason": reason,
            },
        )
        if replay is not None:
            return replay
        before = console_admin.meter_price_entries(meter)
        try:
            entry = console_admin.add_meter_price(
                meter, vendor_cost=data["vendor_cost"], unit_size=data["unit_size"], margin=data.get("margin"),
                effective_from=effective_from,
            )
        except pricing.InvalidMeterPrice as exc:
            body = {"code": exc.code, "detail": exc.message}
            complete_action(action_request, result="failed", response_status=status.HTTP_400_BAD_REQUEST, response_body=body)
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        complete_action(action_request, result="succeeded", response_status=status.HTTP_201_CREATED, response_body=entry)
        record_control_audit(
            request=request, action="configuration.meter_price_added", target_type="meter", target_id=meter,
            reason=reason, before={"prices": before}, after=entry,
        )
        return Response(entry, status=status.HTTP_201_CREATED)


class PlatformControlExchangeRateViewSet(PlatformControlAccessViewSet):
    """Audited manual exchange-rate corrections for one currency pair and date."""

    def list(self, request):
        return Response(console_admin.exchange_rate_entries(
            base=request.query_params.get("base"), currency=request.query_params.get("currency"),
            limit=_limit(request.query_params.get("limit")),
        ))

    def create(self, request):
        require_confirmation(request)
        data = _body(request)
        reason = require_reason(request)
        for field in ("from", "to", "rate"):
            if data.get(field) in (None, ""):
                raise ValidationError({"code": exchange_rates.InvalidExchangeRate.default_code, "detail": f"{field} is required to store a rate.", "field": field})
        from_code, to_code = str(data["from"]), str(data["to"])
        effective_date = _day(data.get("effective_date"), "effective_date", exchange_rates.InvalidExchangeRate.default_code)
        target_id = f"{from_code.strip().upper()}:{to_code.strip().upper()}:{effective_date or timezone.localdate()}"
        action_request, replay = claim_action(
            request, action="configuration.exchange_rate_set", target_type="exchange_rate", target_id=target_id,
            payload={"from": from_code, "to": to_code, "rate": data["rate"], "effective_date": str(effective_date or ""), "reason": reason},
        )
        if replay is not None:
            return replay
        before = console_admin.exchange_rate_entries(base=from_code, currency=to_code, limit=200)
        try:
            entry = console_admin.set_exchange_rate(from_code, to_code, data["rate"], on=effective_date, user=request.user)
        except exchange_rates.InvalidExchangeRate as exc:
            body = {"code": exc.code, "detail": exc.message}
            complete_action(action_request, result="failed", response_status=status.HTTP_400_BAD_REQUEST, response_body=body)
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        complete_action(action_request, result="succeeded", response_status=status.HTTP_201_CREATED, response_body=entry)
        record_control_audit(
            request=request, action="configuration.exchange_rate_set", target_type="exchange_rate", target_id=target_id,
            reason=reason, before={"rates": before}, after=entry,
        )
        return Response(entry, status=status.HTTP_201_CREATED)

class PlatformControlAuditEventViewSet(PlatformControlAccessViewSet):
    """A bounded, cursor-paginated read of redacted control-plane events."""

    default_limit = 50
    max_limit = 100

    @staticmethod
    def _item(event):
        return {
            "id": str(event.id), "action": event.action,
            "target": {"type": event.target_type, "id": event.target_id},
            "reason": event.reason, "result": event.result,
            "actor": {"id": event.actor_id, "username": event.actor.username} if event.actor_id else None,
            "before": redact_control_value(event.before or {}),
            "after": redact_control_value(event.after or {}), "created_at": event.created_at,
        }

    def _limit(self, request):
        try:
            limit = int(request.query_params.get("limit", self.default_limit))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."}) from exc
        if not 1 <= limit <= self.max_limit:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."})
        return limit

    @staticmethod
    def _cursor(request):
        cursor = request.query_params.get("cursor")
        if not cursor:
            return None
        try:
            payload = signing.loads(cursor, salt="platform-control-audit", max_age=60 * 60 * 24 * 30)
            created_at = datetime.fromisoformat(payload["created_at"])
            event_id = payload["id"]
        except (KeyError, TypeError, ValueError, signing.BadSignature) as exc:
            raise ValidationError({"cursor": "Use a valid audit-event cursor."}) from exc
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at, timezone.get_current_timezone())
        return created_at, event_id

    @staticmethod
    def _next_cursor(event):
        return signing.dumps({"created_at": event.created_at.isoformat(), "id": str(event.id)}, salt="platform-control-audit")

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
        page = list(events[:self._limit(request) + 1])
        has_next = len(page) > self._limit(request)
        page = page[:self._limit(request)]
        return Response({"results": [self._item(event) for event in page], "next": self._next_cursor(page[-1]) if has_next and page else None})
