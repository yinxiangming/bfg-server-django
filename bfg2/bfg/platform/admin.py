# -*- coding: utf-8 -*-
from django.contrib import admin
from bfg.common.models import SocialAuthConfig, WorkspaceDomain
from bfg.platform.models import (
    Cluster,
    FeatureDefinition,
    WorkspaceOperation,
    WorkspacePlatformProfile,
    WorkspaceSSOConfig,
)


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "region", "health_status", "current_workspaces", "max_workspaces", "is_active"]
    list_filter = ["region", "is_active", "health_status"]
    search_fields = ["id", "name"]
    readonly_fields = ["last_health_check", "current_workspaces"]


@admin.register(FeatureDefinition)
class FeatureDefinitionAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "category", "default_enabled", "min_plan"]
    list_filter = ["category", "default_enabled"]
    search_fields = ["key", "name"]


@admin.register(WorkspaceOperation)
class WorkspaceOperationAdmin(admin.ModelAdmin):
    list_display = ["workspace", "operation", "status", "initiated_by", "started_at", "completed_at"]
    list_filter = ["operation", "status"]
    search_fields = ["workspace__name", "workspace__slug"]
    readonly_fields = ["id", "started_at", "completed_at"]


@admin.register(WorkspacePlatformProfile)
class WorkspacePlatformProfileAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "workspace",
        "remote_workspace_uuid",
        "region",
        "cluster",
        "suspended_at",
    ]
    list_filter = ["region"]
    search_fields = ["workspace__name", "workspace__slug", "remote_workspace_uuid"]
    readonly_fields = ["platform_api_key", "agent_api_key"]


@admin.register(WorkspaceDomain)
class WorkspaceDomainAdmin(admin.ModelAdmin):
    list_display = [
        "hostname",
        "workspace",
        "kind",
        "verification_status",
        "ssl_status",
        "is_primary",
    ]
    list_filter = ["kind", "verification_status", "ssl_status", "is_primary"]
    search_fields = ["hostname", "workspace__name", "workspace__slug"]


@admin.register(WorkspaceSSOConfig)
class WorkspaceSSOConfigAdmin(admin.ModelAdmin):
    list_display = ["email_domain", "workspace", "protocol", "enforce_sso", "auto_provision", "is_active"]
    list_filter = ["protocol", "enforce_sso", "is_active"]
    search_fields = ["email_domain", "workspace__name"]


@admin.register(SocialAuthConfig)
class SocialAuthConfigAdmin(admin.ModelAdmin):
    """Social-login clients, including the platform default.

    Lives on the platform side because the default — the row with no workspace —
    belongs to the operator and is reachable from no tenant's admin. Workspace
    rows are listed too so support can see which shop overrides the default,
    but those are normally edited by the shop itself.
    """
    list_display = ["id", "provider", "owner", "client_id", "is_active", "is_configured", "updated_at"]
    list_filter = ["provider", "is_active"]
    search_fields = ["client_id", "workspace__slug", "workspace__name"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Owner", ordering="workspace")
    def owner(self, obj):
        return obj.workspace or "— platform default —"

    @admin.display(boolean=True, description="Configured")
    def is_configured(self, obj):
        return obj.is_configured

    def save_model(self, request, obj, form, change):
        """Keep the one-default-per-provider rule that MySQL cannot enforce.

        The constraint is conditional, so MySQL skips creating it (system check
        W036) and a second platform row would otherwise save silently and make
        which client a tenant inherits a coin toss.
        """
        from django.core.exceptions import ValidationError

        if obj.workspace_id is None:
            clash = SocialAuthConfig.objects.filter(
                workspace__isnull=True, provider=obj.provider
            ).exclude(pk=obj.pk)
            if clash.exists():
                raise ValidationError(
                    f"A platform default for {obj.provider} already exists; edit that row instead."
                )
        super().save_model(request, obj, form, change)
