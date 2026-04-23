# -*- coding: utf-8 -*-
"""
Runtime server version metadata for health checks and client compatibility.
"""

import importlib
import os

from django.conf import settings

# Workspace API process app line — override in containers with WORKSPACE_SERVER_APP_VERSION.
_DEFAULT_WORKSPACE_SERVER_APP_VERSION = '0.1.0'


def _django_local_extension_apps():
    """
    Installed workspace Django apps under apps.<name> (symlinks to extensions/*-server).
    Each entry: {"id": "<folder>", "version": "<str or empty>"} from package __version__ if set.
    """
    try:
        from config.local_apps import get_local_apps
    except Exception:
        return []
    out = []
    for name in get_local_apps():
        ver = ''
        try:
            mod = importlib.import_module(f'apps.{name}')
            v = getattr(mod, '__version__', None)
            if v is not None:
                ver = str(v)
        except Exception:
            pass
        out.append({'id': name, 'version': ver})
    return out


def get_server_version_payload():
    """
    Return version fields for the running server process.

    Optional env vars (CI / containers):
    - BUILD_ID, GIT_SHA: deployment revision shown when set.
    """
    import bfg

    spectacular = getattr(settings, 'SPECTACULAR_SETTINGS', None) or {}
    payload = {
        'api_version': 'v1',
        'schema_version': spectacular.get('VERSION') or '',
        'bfg_version': getattr(bfg, '__version__', 'unknown'),
        'workspace_server_app_version': os.environ.get(
            'WORKSPACE_SERVER_APP_VERSION', _DEFAULT_WORKSPACE_SERVER_APP_VERSION
        ),
        'django_local_apps': _django_local_extension_apps(),
    }
    build_id = os.environ.get('BUILD_ID') or os.environ.get('GIT_SHA')
    if build_id:
        payload['build_id'] = build_id
    return payload
