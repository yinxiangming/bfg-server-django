# -*- coding: utf-8 -*-
"""
Find the manifest of every installed extension.

Discovery is by convention, the same as ``onboarding_setup`` and
``dashboard_extensions``: an app exposes ``<app>/extension.py`` defining
``EXTENSION = ExtensionManifest(...)``. The installed apps cannot change without a
restart, so discovery runs once per process.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from importlib import import_module
from typing import Dict, List, Optional

from django.apps import apps

from bfg.common.extensions.manifest import ExtensionManifest

logger = logging.getLogger(__name__)

MANIFEST_MODULE = 'extension'
MANIFEST_ATTRIBUTE = 'EXTENSION'

_cache: Optional[Dict[str, ExtensionManifest]] = None


def _discover() -> Dict[str, ExtensionManifest]:
    manifests: Dict[str, ExtensionManifest] = {}
    for app_config in apps.get_app_configs():
        module_name = f'{app_config.name}.{MANIFEST_MODULE}'
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            # Only "this app ships no manifest" is expected. A manifest that imports
            # something missing is a bug, and swallowing it would make the extension
            # look undeployed.
            if exc.name != module_name:
                logger.exception('Extension manifest %s failed to import', module_name)
            continue
        except Exception:
            logger.exception('Extension manifest %s failed to import', module_name)
            continue

        manifest = getattr(module, MANIFEST_ATTRIBUTE, None)
        if not isinstance(manifest, ExtensionManifest):
            logger.error('%s defines no %s manifest', module_name, MANIFEST_ATTRIBUTE)
            continue
        if manifest.key in manifests:
            logger.error(
                'Extension key %r is declared by both %s and %s; ignoring the second',
                manifest.key, manifests[manifest.key].app_label, app_config.label,
            )
            continue
        manifests[manifest.key] = replace(manifest, app_label=app_config.label)
    return manifests


def _manifests() -> Dict[str, ExtensionManifest]:
    global _cache
    if _cache is None:
        _cache = _discover()
    return _cache


def all_manifests() -> List[ExtensionManifest]:
    """Every deployed extension, ordered by key."""
    return sorted(_manifests().values(), key=lambda manifest: manifest.key)


def get_manifest(key: str) -> Optional[ExtensionManifest]:
    return _manifests().get(key)


def manifest_for_app(app_label: str) -> Optional[ExtensionManifest]:
    """The manifest shipped by the app with this label, if it ships one."""
    for manifest in _manifests().values():
        if manifest.app_label == app_label:
            return manifest
    return None


def reset_cache() -> None:
    """Forget discovered manifests. For tests that install or fake a manifest mid-run."""
    global _cache
    _cache = None
