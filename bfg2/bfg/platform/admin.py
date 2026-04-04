# -*- coding: utf-8 -*-
from django.contrib import admin
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
        "remote_workspace_uuid",
        "region",
        "cluster",
        "ssl_status",
        "suspended_at",
    ]
    list_filter = ["region", "ssl_status"]
    search_fields = ["custom_domain", "remote_workspace_uuid"]
    readonly_fields = ["platform_api_key", "agent_api_key"]


@admin.register(WorkspaceSSOConfig)
class WorkspaceSSOConfigAdmin(admin.ModelAdmin):
    list_display = ["email_domain", "workspace", "protocol", "enforce_sso", "auto_provision", "is_active"]
    list_filter = ["protocol", "enforce_sso", "is_active"]
    search_fields = ["email_domain", "workspace__name"]
