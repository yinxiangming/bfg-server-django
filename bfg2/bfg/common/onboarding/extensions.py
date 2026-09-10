# -*- coding: utf-8 -*-
"""
Let installed apps contribute to the setup checklist.

BFG ships the checklist every shop needs — currency, tax, legal pages, a
payment method. A deployment always has more than that: this codebase alone adds
marketplace channels, address lookup, WeChat identity and a legacy importer, and
none of them belong in a library that other installs use without them.

Discovery is by convention, the same as ``dashboard_extensions``: an app exposes
``<app>/onboarding_setup.py`` and it is picked up. Nothing to register, no
import-order dance in ``AppConfig.ready``, and an app that is not installed
contributes nothing rather than leaving a dead row on the checklist.

A provider module may define any of:

``ONBOARDING_ITEMS``
    ``{step_key: [Item, ...]}`` — rows appended to a step BFG already defines.
``ONBOARDING_STEPS``
    ``[Step, ...]`` — a whole step of its own, appended after BFG's.
``get_custom_settings_patch(plan, workspace)``
    Returns a dict merged into ``Settings.custom_settings`` when a template is
    applied, so an app can pre-fill its own config from the country/industry
    pick. Return ``None`` to write nothing.
``ONBOARDING_INDUSTRIES``
    ``[{key, name, name_zh, icon, description, description_zh}, ...]`` — extra
    industries offered in the wizard's dropdown.
``get_template_fragment(country, industry, plan)``
    Contribute to the template itself: extra product categories, extra pages,
    extra menus, storefront display defaults. Return ``None`` to add nothing.
    This is how an app ships an industry BFG has never heard of — a consignment
    shop's category tree does not belong in a library that most installs use
    without one.

Item keys must be namespaced by the contributing app (``channels.connected``,
not ``connected``) — the checklist is a flat key space and ``skip`` addresses
rows by key.
"""

import logging
from importlib import import_module
from typing import Any, Dict, List, Optional, Tuple

from django.apps import apps

logger = logging.getLogger(__name__)

PROVIDER_MODULE = 'onboarding_setup'

_cache: Optional[Dict[str, Any]] = None


def _iter_provider_modules():
    for app_config in apps.get_app_configs():
        module_name = f'{app_config.name}.{PROVIDER_MODULE}'
        try:
            yield app_config, import_module(module_name)
        except ModuleNotFoundError as exc:
            # Only swallow "this app has no provider". A provider that exists but
            # imports something missing is a bug, and hiding it would show up as
            # a checklist that silently lost a row.
            if exc.name == module_name:
                continue
            logger.exception('Onboarding provider %s failed to import', module_name)
        except Exception:
            logger.exception('Onboarding provider %s failed to import', module_name)


def collect() -> Tuple[List[Any], Dict[str, List[Any]], List[Any]]:
    """``(extra_steps, items_by_step_key, patch_providers)``, computed once."""
    data = collect_all()
    return data['steps'], data['items'], data['patch_providers']


def collect_all() -> Dict[str, Any]:
    """Everything the installed apps contribute, discovered once per process."""
    global _cache
    if _cache is not None:
        return _cache

    extra_steps: List[Any] = []
    items: Dict[str, List[Any]] = {}
    patch_providers: List[Any] = []
    industries: List[Dict[str, Any]] = []
    fragment_providers: List[Any] = []

    for app_config, module in _iter_provider_modules():
        for step in getattr(module, 'ONBOARDING_STEPS', ()) or ():
            extra_steps.append(step)
        contributed = getattr(module, 'ONBOARDING_ITEMS', None) or {}
        if isinstance(contributed, dict):
            for step_key, step_items in contributed.items():
                items.setdefault(step_key, []).extend(step_items)
        else:
            logger.warning(
                'ONBOARDING_ITEMS in app %s is %s, expected dict',
                app_config.name, type(contributed).__name__,
            )
        provider = getattr(module, 'get_custom_settings_patch', None)
        if callable(provider):
            patch_providers.append((app_config.name, provider))
        for industry in getattr(module, 'ONBOARDING_INDUSTRIES', ()) or ():
            if isinstance(industry, dict) and industry.get('key'):
                industries.append({**industry, 'owner': app_config.name})
            else:
                logger.warning('ONBOARDING_INDUSTRIES entry in %s has no key', app_config.name)
        fragment = getattr(module, 'get_template_fragment', None)
        if callable(fragment):
            fragment_providers.append((app_config.name, fragment))

    _cache = {
        'steps': extra_steps,
        'items': items,
        'patch_providers': patch_providers,
        'industries': industries,
        'fragment_providers': fragment_providers,
    }
    return _cache


def contributed_industries() -> List[Dict[str, Any]]:
    return list(collect_all()['industries'])


def template_fragments(country: str, industry: str, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every app's addition to the rendered template, in discovery order.

    Returned rather than merged here so the caller decides how each key
    combines — categories and pages append, display settings override.
    """
    fragments = []

    for app_name, provider in collect_all()['fragment_providers']:
        try:
            fragment = provider(country=country, industry=industry, plan=plan)
        except Exception:
            logger.exception('Onboarding template fragment failed for app %s', app_name)
            continue
        if not fragment:
            continue
        if not isinstance(fragment, dict):
            logger.warning('Onboarding template fragment from %s is not a dict', app_name)
            continue
        fragments.append(fragment)

    return fragments


def reset_cache() -> None:
    """Drop the discovery cache. For tests that install a provider mid-run."""
    global _cache
    _cache = None


def custom_settings_patch(plan: Dict[str, Any], workspace) -> Dict[str, Any]:
    """Merge every contributor's settings patch, one level deep.

    Shallow-merging the top level and replacing below it is deliberate: two apps
    writing the same ``custom_settings`` sub-key would otherwise interleave into
    a half-and-half dict that satisfies neither.
    """
    providers = collect_all()['patch_providers']
    merged: Dict[str, Any] = {}

    for app_name, provider in providers:
        try:
            patch = provider(plan=plan, workspace=workspace)
        except Exception:
            logger.exception('Onboarding settings patch failed for app %s', app_name)
            continue
        if not patch:
            continue
        if not isinstance(patch, dict):
            logger.warning('Onboarding settings patch from %s is not a dict', app_name)
            continue
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value

    return merged
