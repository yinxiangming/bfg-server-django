import logging
from importlib import import_module
from typing import Any

from django.apps import apps

logger = logging.getLogger(__name__)

DASHBOARD_STATS_MODULE = "dashboard_stats"
DASHBOARD_STATS_PROVIDER = "get_me_dashboard_stats"


def collect_me_dashboard_stats(request: Any, workspace: Any, customer: Any) -> dict[str, Any]:
    """
    Collect optional account dashboard stats from installed apps.

    Apps can expose `<app>.dashboard_stats.get_me_dashboard_stats(...)` and
    return a dict that will be merged into the `/me/dashboard-stats/` payload.
    """
    stats: dict[str, Any] = {}

    for app_config in apps.get_app_configs():
        module_name = f"{app_config.name}.{DASHBOARD_STATS_MODULE}"
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                continue
            logger.exception("Dashboard stats module %s failed to import", module_name)
            continue

        provider = getattr(module, DASHBOARD_STATS_PROVIDER, None)
        if not callable(provider):
            continue

        try:
            app_stats = provider(request=request, workspace=workspace, customer=customer)
        except Exception:
            logger.exception("Dashboard stats provider failed for app %s", app_config.name)
            continue

        if isinstance(app_stats, dict):
            stats.update(app_stats)
        else:
            logger.warning(
                "Dashboard stats provider for app %s returned %s, expected dict",
                app_config.name,
                type(app_stats).__name__,
            )

    return stats
