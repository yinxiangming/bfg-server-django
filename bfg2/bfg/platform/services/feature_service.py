# -*- coding: utf-8 -*-
"""
Feature Flag Service
Manages feature flags for workspaces based on their subscription plan.
Flags are stored in Settings.features JSON field.
"""
from django.apps import apps


def get_workspace_features(workspace) -> dict:
    """
    Get all feature flags for a workspace.
    Reads from Settings.features JSON field (BFG core).
    Falls back to empty dict if settings not found.
    """
    try:
        Settings = apps.get_model("common", "Settings")
        settings_obj = Settings.objects.filter(workspace=workspace).first()
        if settings_obj:
            return settings_obj.features or {}
    except Exception:
        pass
    return {}


def sync_plan_features(workspace, plan) -> None:
    """
    Sync feature flags from a SubscriptionPlan to workspace Settings.features.
    Called when a workspace subscribes or changes plan.
    plan.features is expected to be a list of feature key strings.
    """
    try:
        Settings = apps.get_model("common", "Settings")
        settings_obj, _ = Settings.objects.get_or_create(workspace=workspace)
        features = settings_obj.features or {}
        for feat_key in (plan.features or []):
            if isinstance(feat_key, str):
                features[feat_key] = True
        settings_obj.features = features
        settings_obj.save(update_fields=["features"])
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to sync plan features for workspace {workspace.id}: {e}")


def set_workspace_feature(workspace, key: str, enabled: bool) -> None:
    """
    Manually set a single feature flag for a workspace (Platform admin override).
    """
    try:
        Settings = apps.get_model("common", "Settings")
        settings_obj, _ = Settings.objects.get_or_create(workspace=workspace)
        features = settings_obj.features or {}
        features[key] = enabled
        settings_obj.features = features
        settings_obj.save(update_fields=["features"])
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to set feature {key} for workspace {workspace.id}: {e}")
