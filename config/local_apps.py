"""
Discover local apps from env or by scanning apps directory.
Avoids hardcoding app names in settings/urls.
"""
import os
from pathlib import Path


def get_local_apps():
    """
    Return list of local app names (e.g. ['resale']).
    Uses LOCAL_APPS env (comma-separated) if set; otherwise discovers from apps dir.
    """
    env_val = os.environ.get('LOCAL_APPS', '').strip()
    if env_val:
        return [x.strip() for x in env_val.split(',') if x.strip()]

    # Auto-discover: scan apps directory for packages that have urls.py
    base_dir = Path(__file__).resolve().parent.parent
    apps_dir = base_dir / 'apps'
    if not apps_dir.is_dir():
        return []

    result = []
    for item in apps_dir.iterdir():
        if item.name.startswith('_'):
            continue
        # Resolve symlinks when checking (item may be symlink to app dir)
        target = item.resolve() if item.exists() else item
        if not target.is_dir():
            continue
        urls_file = target / 'urls.py'
        apps_file = target / 'apps.py'
        if urls_file.exists() and apps_file.exists():
            result.append(item.name)
    return sorted(result)


def get_local_app_dotted_names():
    """Return list of dotted app names (e.g. ['apps.resale'])."""
    return [f'apps.{name}' for name in get_local_apps()]
