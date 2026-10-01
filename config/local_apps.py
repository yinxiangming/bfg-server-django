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
            f'Use a directory under apps/ (e.g. custom_app), or leave LOCAL_APPS empty for auto-discovery. '
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
    Return list of local app names (e.g. ['custom_app']).
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
    """Return list of dotted app names (e.g. ['apps.custom_app'])."""
    return [f'apps.{name}' for name in get_local_apps()]


def apply_local_app_settings(namespace, app_names):
    """Load optional model-free host_settings contributions from installed local apps.

    SETTINGS adds new uppercase keys; PUBLIC_PATHS may exempt only the app's
    own API prefix. Host configuration and another app's keys cannot be replaced.
    Import errors inside a declared module fail startup instead of being hidden.
    """
    from importlib import import_module
    from importlib.util import find_spec

    additions = {}
    public_paths = list(namespace.get('BFG_EXTRA_PUBLIC_PATHS', ()))
    for app_name in app_names:
        module_name = f'{app_name}.host_settings'
        if find_spec(module_name) is None:
            continue
        contribution = import_module(module_name)
        values = getattr(contribution, 'SETTINGS', {})
        if not isinstance(values, dict):
            raise ImproperlyConfigured(f'{module_name}.SETTINGS must be a dict')
        for key, value in values.items():
            if not isinstance(key, str) or not key.isidentifier() or not key.isupper():
                raise ImproperlyConfigured(f'{module_name}: invalid setting key {key!r}')
            if key in namespace or key in additions:
                raise ImproperlyConfigured(f'{module_name}: setting {key} already belongs to the host or another app')
            additions[key] = value
        paths = getattr(contribution, 'PUBLIC_PATHS', ())
        prefix = f'/api/v1/{app_name.rsplit(".", 1)[-1]}/'
        if not isinstance(paths, (tuple, list)) or any(
            not isinstance(path, str) or not path.startswith(prefix)
            or any(part in {'.', '..'} for part in path.split('/'))
            or '?' in path or '#' in path or '\\' in path
            for path in paths
        ):
            raise ImproperlyConfigured(f'{module_name}: PUBLIC_PATHS must stay within {prefix}')
        public_paths.extend(paths)
    # Validate all declarations before publishing any contributions.
    namespace.update(additions)
    namespace['BFG_EXTRA_PUBLIC_PATHS'] = tuple(dict.fromkeys(public_paths))
