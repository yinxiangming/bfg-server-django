# -*- coding: utf-8 -*-
"""Platform-admin workspace console endpoints.

These endpoints deliberately expose lifecycle controls without exposing cluster
credentials or allowing a hard delete from the web console.
"""
from datetime import timedelta

from django.apps import apps
from django.contrib.auth.forms import PasswordResetForm
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bfg.platform.permissions import IsPlatformAdmin
from bfg.platform.services.provision_service import suspend_workspace, resume_workspace
from bfg.platform.utils import is_platform_workspace
from bfg.common.services.workspace_service import WorkspaceService


class PlatformConsoleWorkspaceViewSet(viewsets.ViewSet):
    """Cross-workspace management for platform administrators only."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _workspace(self, pk):
        Workspace = apps.get_model("common", "Workspace")
        return Workspace.objects.select_related("platform_profile__cluster").get(pk=pk)

    def _owner(self, workspace):
        StaffMember = apps.get_model("common", "StaffMember")
        member = (StaffMember.all_objects.filter(workspace=workspace, is_active=True,
                                                  role__code__in=["admin", "owner"])
                   .select_related("user").order_by("id").first())
        if not member:
            return None
        user = member.user
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
        workspace = self._workspace(pk)
        suspend_workspace(workspace, initiated_by=request.user, reason=request.data.get("reason", ""))
        return Response(self._item(workspace))

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        workspace = self._workspace(pk)
        resume_workspace(workspace, initiated_by=request.user)
        return Response(self._item(workspace))

    @action(detail=True, methods=["post"])
    def delete(self, request, pk=None):
        """Schedule a recoverable deletion; never remove tenant data here."""
        if request.data.get("confirm") is not True:
            return Response({"detail": "confirm=true is required."}, status=status.HTTP_400_BAD_REQUEST)
        WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")
        workspace = self._workspace(pk)
        workspace.is_active = False
        workspace.save(update_fields=["is_active"])
        profile = getattr(workspace, "platform_profile", None)
        if profile:
            profile.scheduled_deletion_at = timezone.now() + timedelta(days=30)
            profile.save(update_fields=["scheduled_deletion_at", "updated_at"])
        WorkspaceOperation.objects.create(workspace=workspace, operation="delete", status="completed",
                                          initiated_by=request.user, details={"soft": True},
                                          completed_at=timezone.now())
        return Response(self._item(workspace))

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        workspace = self._workspace(pk)
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        data = {
            "format": "idlevo-workspace-v1",
            "workspace": {"name": workspace.name, "slug": workspace.slug, "email": workspace.email,
                          "phone": workspace.phone, "settings": workspace.settings or {}},
            "domains": list(workspace.domains.values_list("hostname", flat=True)),
            "cluster": {"id": cluster.id, "name": cluster.name, "region": cluster.region} if cluster else None,
            "exported_at": timezone.now().isoformat(),
        }
        import json
        response = HttpResponse(json.dumps(data, indent=2, default=str), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="workspace-{workspace.slug}.json"'
        return response

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def import_workspace(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        source = data.get("workspace", data)
        name = str(source.get("name", "")).strip()
        if not name:
            return Response({"detail": "workspace.name is required."}, status=status.HTTP_400_BAD_REQUEST)
        Workspace = apps.get_model("common", "Workspace")
        slug = source.get("slug") or None
        if slug and Workspace.objects.filter(slug=slug).exists():
            return Response({"detail": "A workspace with this slug already exists."}, status=status.HTTP_409_CONFLICT)
        User = apps.get_model("common", "User")
        owner = None
        owner_email = str(data.get("owner_email", "")).strip().lower()
        if owner_email:
            owner = User.objects.filter(email__iexact=owner_email).first()
        workspace = WorkspaceService(user=request.user).create_workspace(
            name=name, slug=slug, owner_user=owner, email=source.get("email", ""),
            phone=source.get("phone", ""), settings=source.get("settings") or {},
            region=(data.get("cluster") or {}).get("region") or "us",
        )
        return Response(self._item(workspace), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reset-admin-password")
    def reset_admin_password(self, request, pk=None):
        workspace = self._workspace(pk)
        owner = self._owner(workspace)
        email = str(request.data.get("email") or (owner or {}).get("email") or "").strip()
        if email:
            form = PasswordResetForm({"email": email})
            if form.is_valid():
                form.save(request=request, use_https=request.is_secure(),
                          subject_template_name="registration/password_reset_subject.txt",
                          email_template_name="registration/password_reset_email.html")
        return Response({"detail": "If the account exists, a password reset email has been sent."})
