"""Read-only Cluster/Brand Portal inventory inside a configured Django shell."""

import json
from urllib.parse import urlsplit

from django.apps import apps
from django.db import connection
from django.db.models import Count


def safe_origin(value):
    """Keep public origins while omitting userinfo, query strings and paths."""
    try:
        parsed = urlsplit(value or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        return f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")
    except ValueError:
        return ""


def inspect():
    """Inspect tables and relationships without changing schema or application data."""
    report = {"database_vendor": connection.vendor, "clusters": [],
              "assigned_workspaces": [], "brand_portals": [], "warnings": []}
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))

    report["brand_portal_tables_present"] = sorted(
        name for name in tables if name.startswith("brand_portal_")
    )
    report["brand_portal_app_loaded"] = any(
        config.name.endswith(".brand_portal") for config in apps.get_app_configs()
    )
    models = []
    for app_label, model_name in (
        ("platform", "Cluster"), ("platform", "WorkspacePlatformProfile"),
        ("common", "WorkspaceDomain"), ("common", "WorkspaceExtension"),
    ):
        try:
            models.append(apps.get_model(app_label, model_name))
        except LookupError:
            report["warnings"].append(f"Missing model/app: {app_label}.{model_name}")
    if report["warnings"]:
        return report
    Cluster, Profile, Domain, Extension = models
    for model in (Cluster, Profile, Domain, Extension):
        if model._meta.db_table not in tables:
            report["warnings"].append(f"Missing table: {model._meta.db_table}")
    if report["warnings"]:
        return report

    for cluster in Cluster.objects.annotate(bound_profiles=Count("workspaces")).order_by("id"):
        report["clusters"].append({
            "id": cluster.pk, "name": cluster.name, "region": cluster.region,
            "api_origin": safe_origin(cluster.api_base_url),
            "frontend_origin": safe_origin(cluster.frontend_base_url),
            "active": cluster.is_active, "accepting_new": cluster.is_accepting_new,
            "bound_profiles": cluster.bound_profiles, "max_workspaces": cluster.max_workspaces,
        })
    for profile in Profile.objects.filter(cluster__isnull=False).select_related("workspace"):
        if profile.workspace_id is None:
            continue
        domains = list(Domain.objects.filter(
            workspace_id=profile.workspace_id, kind=Domain.KIND_SYSTEM_DEFAULT,
        ).values_list("hostname", flat=True))
        report["assigned_workspaces"].append({
            "workspace_id": profile.workspace_id, "workspace_slug": profile.workspace.slug,
            "cluster_id": profile.cluster_id, "system_domains": domains,
        })
    report["brand_portal_activations"] = list(Extension.all_objects.filter(
        key="brand_portal",
    ).values("workspace_id", "status"))

    try:
        Portal = apps.get_model("brand_portal", "BrandPortalProfile")
    except LookupError:
        report["warnings"].append(
            "Brand Portal app is not loaded; existing tables do not enable its routes."
        )
    else:
        if Portal._meta.db_table not in tables:
            report["warnings"].append(f"Missing table: {Portal._meta.db_table}")
        else:
            for portal in Portal.objects.select_related("workspace").order_by("workspace_id"):
                cluster_id = Profile.objects.filter(workspace_id=portal.workspace_id).values_list(
                    "cluster_id", flat=True,
                ).first()
                report["brand_portals"].append({
                    "workspace_id": portal.workspace_id,
                    "workspace_slug": portal.workspace.slug,
                    "registration_enabled": portal.registration_enabled,
                    "cluster_id": cluster_id,
                    "provisioning_extensions": portal.provisioning_extensions,
                    "default_theme": portal.default_theme,
                })
    return report


print(json.dumps(inspect(), ensure_ascii=False, indent=2))
