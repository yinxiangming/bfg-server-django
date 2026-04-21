"""
Discover local apps from env or by scanning apps directory.
Avoids hardcoding app names in settings/urls.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def _validate_app_package(apps_dir: Path, name: str) -> None:
    """Ensure apps/<name>/ exists and looks like a Django app package."""
    pkg = apps_dir / name
    if not pkg.exists():
        raise ImproperlyConfigured(
            f'LOCAL_APPS includes "{name}" but {pkg} does not exist. '
            f'Use a directory under apps/ (e.g. resale), or leave LOCAL_APPS empty for auto-discovery. '
            f'Platform APIs live in bfg.platform and are mounted from config/urls.py (not under apps/).'
        )
    target = pkg.resolve() if pkg.is_dir() or pkg.is_symlink() else pkg
    if not target.is_dir():
        raise ImproperlyConfigured(
            f'LOCAL_APPS entry "{name}" is not a directory: {pkg}'
        )
    if not (target / 'urls.py').is_file() or not (target / 'apps.py').is_file():
        raise ImproperlyConfigured(
            f'LOCAL_APPS entry "{name}" must have urls.py and apps.py under {target}'
        )


def get_local_apps():
    """
    Return list of local app names (e.g. ['resale']).
    Uses LOCAL_APPS env (comma-separated) if set; otherwise discovers from apps dir.
    """
    base_dir = Path(__file__).resolve().parent.parent
    apps_dir = base_dir / 'apps'

    env_val = os.environ.get('LOCAL_APPS', '').strip()
    if env_val:
        names = [x.strip() for x in env_val.split(',') if x.strip()]
        for name in names:
            _validate_app_package(apps_dir, name)
        return names

    # Auto-discover: scan apps directory for packages that have urls.py
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
