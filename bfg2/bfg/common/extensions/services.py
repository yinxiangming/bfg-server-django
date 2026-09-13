# -*- coding: utf-8 -*-
"""
Activation of extensions per workspace, and the question everything else asks:
is this extension live for this workspace right now?

An extension is available to a workspace when it is deployed (its manifest was found)
and either it is not workspace-scoped, or the workspace has it active, is entitled to
it, and every extension it requires is available as well. The answer is cached per
workspace and dropped once a change to it commits.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Callable, Dict, FrozenSet, Iterable, List

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from bfg.common.cache_policy import cache_ttl
from bfg.common.extensions import registry
from bfg.common.extensions.manifest import SCOPE_WORKSPACE, ExtensionManifest
from bfg.common.storefront_cache import invalidate_storefront_config_cache

logger = logging.getLogger(__name__)


class ExtensionError(Exception):
    """A state change that cannot be made. ``code`` is stable for API clients."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# ── Availability ─────────────────────────────────────────────────────


def available_cache_key(workspace_id: int) -> str:
    return f'extensions:available:{workspace_id}'


@lru_cache(maxsize=None)
def _load_entitlement_check(path: str) -> Callable:
    return import_string(path)


def is_entitled(workspace, manifest: ExtensionManifest) -> bool:
    """Whether the workspace may use the extension at all.

    ``BFG_EXTENSION_ENTITLEMENT_CHECK`` names a callable ``(workspace, manifest) -> bool``
    for deployments that sell extensions. Without it every workspace is entitled to
    every extension.
    """
    path = getattr(settings, 'BFG_EXTENSION_ENTITLEMENT_CHECK', '')
    if not path:
        return True
    return bool(_load_entitlement_check(path)(workspace, manifest))


def _entitled_or_unavailable(workspace, manifest: ExtensionManifest) -> bool:
    # Answering "what is available" must not fail with the deployment's entitlement
    # backend. A check that raises makes the extension unavailable, not the page 500.
    try:
        return is_entitled(workspace, manifest)
    except Exception:
        logger.exception(
            'Entitlement check failed for extension %s in workspace %s',
            manifest.key, getattr(workspace, 'pk', None),
        )
        return False


def compute_available_keys(workspace) -> FrozenSet[str]:
    """Keys of the extensions available to ``workspace``, read from the database."""
    from bfg.common.models import WorkspaceExtension

    manifests = {manifest.key: manifest for manifest in registry.all_manifests()}
    available = {key for key, manifest in manifests.items() if manifest.scope != SCOPE_WORKSPACE}
    if workspace is not None:
        active_keys = WorkspaceExtension.all_objects.filter(
            workspace=workspace,
            status=WorkspaceExtension.STATUS_ACTIVE,
        ).values_list('key', flat=True)
        for key in active_keys:
            manifest = manifests.get(key)
            if (
                manifest is not None
                and manifest.scope == SCOPE_WORKSPACE
                and _entitled_or_unavailable(workspace, manifest)
            ):
                available.add(key)

    # An extension is only as available as what it requires, all the way down.
    changed = True
    while changed:
        changed = False
        for key in list(available):
            if any(required not in available for required in manifests[key].requires):
                available.discard(key)
                changed = True
    return frozenset(available)


def available_keys(workspace) -> FrozenSet[str]:
    """``compute_available_keys``, cached per workspace."""
    if workspace is None:
        return compute_available_keys(None)
    cache_key = available_cache_key(workspace.id)
    cached = cache.get(cache_key)
    if cached is not None:
        return frozenset(cached)
    keys = compute_available_keys(workspace)
    cache.set(cache_key, sorted(keys), cache_ttl())
    return keys


def is_available(workspace, key: str) -> bool:
    manifest = registry.get_manifest(key)
    if manifest is None:
        return False
    if manifest.scope != SCOPE_WORKSPACE:
        return True
    if workspace is None:
        return False
    return key in available_keys(workspace)


def availability(workspace, *, public_only: bool = False) -> Dict[str, List[str]]:
    """What a client needs to decide which plugins to load.

    ``offered`` lists every extension a workspace can switch on; ``available`` the ones
    live for ``workspace``. With ``public_only`` both lists keep only extensions that
    show up outside the admin.
    """
    manifests = registry.all_manifests()
    if public_only:
        manifests = [manifest for manifest in manifests if manifest.has_public_surface]
    live = available_keys(workspace)
    return {
        'available': sorted(manifest.key for manifest in manifests if manifest.key in live),
        'offered': sorted(manifest.key for manifest in manifests if manifest.is_activatable),
    }


def workspaces_with(key: str) -> List:
    """Active workspaces for which ``key`` is available.

    For scheduled work, which has no request to take a workspace from.
    """
    from bfg.common.models import Workspace, WorkspaceExtension

    manifest = registry.get_manifest(key)
    if manifest is None:
        return []
    workspaces = Workspace.objects.filter(is_active=True).order_by('id')
    if manifest.scope == SCOPE_WORKSPACE:
        workspaces = workspaces.filter(
            extension_records__key=key,
            extension_records__status=WorkspaceExtension.STATUS_ACTIVE,
        )
    return [workspace for workspace in workspaces if is_available(workspace, key)]


def invalidate(workspace_id: int) -> None:
    """Drop cached answers that depend on which extensions a workspace uses."""
    cache.delete(available_cache_key(workspace_id))
    invalidate_storefront_config_cache(workspace_id)


# ── State changes ────────────────────────────────────────────────────


def _manifest_to_change(key: str) -> ExtensionManifest:
    manifest = registry.get_manifest(key)
    if manifest is None:
        raise ExtensionError('unknown_extension', f'No extension named {key!r} is deployed.')
    if not manifest.is_activatable:
        raise ExtensionError(
            'not_activatable', f'{key} is always available and cannot be switched on or off.'
        )
    return manifest


def _clean_config(manifest: ExtensionManifest, config) -> dict:
    if not isinstance(config, dict):
        raise ExtensionError('invalid_config', 'The configuration must be a JSON object.')
    if manifest.clean_config is None:
        return config
    try:
        cleaned = manifest.clean_config(config)
    except ValidationError as exc:
        raise ExtensionError('invalid_config', ' '.join(exc.messages))
    except ValueError as exc:
        raise ExtensionError('invalid_config', str(exc))
    return cleaned if isinstance(cleaned, dict) else config


def _actor(user):
    return user if user is not None and getattr(user, 'is_authenticated', False) else None


def _locked_records(workspace, keys: Iterable[str], *, ensure: str = '') -> Dict[str, object]:
    """Lock the workspace's records for ``keys``, in key order, until the transaction ends.

    ``ensure`` first creates an inactive record for that key when there is none, so there
    is a row to lock: two requests changing an extension the workspace never used then
    wait for each other instead of racing to insert it. A change that fails takes the new
    row with it when its transaction rolls back.
    """
    from bfg.common.models import WorkspaceExtension

    if ensure:
        try:
            with transaction.atomic():
                WorkspaceExtension.all_objects.get_or_create(
                    workspace=workspace,
                    key=ensure,
                    defaults={'status': WorkspaceExtension.STATUS_INACTIVE},
                )
        except IntegrityError:
            pass  # Inserted by a concurrent request; the lock below waits for it.
    rows = (
        WorkspaceExtension.all_objects.select_for_update()
        .filter(workspace=workspace, key__in=sorted(set(keys)))
        .order_by('key')
    )
    return {row.key: row for row in rows}


@transaction.atomic
def activate(workspace, key: str, *, user=None, config=None):
    """Switch ``key`` on for ``workspace`` and return its record.

    Activating an extension that is already active changes nothing. ``config``, when
    given, is validated and stored with the activation. The records of the extensions
    ``key`` requires stay locked until the activation commits, so none of them can be
    switched off underneath it.
    """
    from bfg.common.models import WorkspaceExtension

    manifest = _manifest_to_change(key)
    record = _locked_records(workspace, [key, *manifest.requires], ensure=key)[key]
    if record.status == WorkspaceExtension.STATUS_ACTIVE:
        return record
    if record.status in (WorkspaceExtension.STATUS_ARCHIVING, WorkspaceExtension.STATUS_RESTORING):
        raise ExtensionError(
            'busy', f'{key} is {record.status}; try again once that finishes.', status=record.status
        )
    if record.status == WorkspaceExtension.STATUS_ARCHIVED:
        raise ExtensionError('archived', f"{key}'s data was archived; restore it before activating.")

    available = compute_available_keys(workspace)
    missing = [required for required in manifest.requires if required not in available]
    if missing:
        raise ExtensionError('requires_inactive', f'Activate {", ".join(missing)} first.', requires=missing)
    unmet = [prerequisite for prerequisite in manifest.prerequisites if not prerequisite.is_met(workspace)]
    if unmet:
        raise ExtensionError(
            'prerequisite_failed',
            ' '.join(prerequisite.message for prerequisite in unmet),
            prerequisites=[prerequisite.code for prerequisite in unmet],
        )
    if not is_entitled(workspace, manifest):
        raise ExtensionError('not_entitled', f'This workspace is not entitled to {key}.')

    now = timezone.now()
    if config is not None:
        record.config = _clean_config(manifest, config)
    record.status = WorkspaceExtension.STATUS_ACTIVE
    record.status_reason = ''
    record.status_changed_at = now
    record.status_changed_by = _actor(user)
    record.activated_at = now
    record.save()

    if manifest.on_activate is not None:
        manifest.on_activate(workspace, record)
    transaction.on_commit(lambda: invalidate(workspace.id))
    return record


@transaction.atomic
def deactivate(workspace, key: str, *, user=None, reason: str = 'deactivated'):
    """Switch ``key`` off for ``workspace``, keeping its data and configuration.

    Returns the record, or ``None`` when the workspace never used the extension.
    """
    from bfg.common.models import WorkspaceExtension

    manifest = _manifest_to_change(key)
    dependent_keys = [candidate.key for candidate in registry.all_manifests() if key in candidate.requires]
    records = _locked_records(workspace, [key, *dependent_keys])
    record = records.get(key)
    if record is None or record.status not in (WorkspaceExtension.STATUS_ACTIVE, WorkspaceExtension.STATUS_PAUSED):
        return record

    dependents = sorted(
        dependent for dependent in dependent_keys
        if dependent in records and records[dependent].status == WorkspaceExtension.STATUS_ACTIVE
    )
    if dependents:
        raise ExtensionError(
            'required_by_active', f'Deactivate {", ".join(dependents)} first.', required_by=dependents
        )

    record.status = WorkspaceExtension.STATUS_INACTIVE
    record.status_reason = reason
    record.status_changed_at = timezone.now()
    record.status_changed_by = _actor(user)
    record.save()

    if manifest.on_deactivate is not None:
        manifest.on_deactivate(workspace, record)
    transaction.on_commit(lambda: invalidate(workspace.id))
    return record


@transaction.atomic
def update_config(workspace, key: str, config):
    """Validate and store ``workspace``'s configuration for ``key``.

    Configuration may be saved before the extension is activated, for extensions that
    cannot work until it is filled in.
    """
    manifest = _manifest_to_change(key)
    cleaned = _clean_config(manifest, config)
    record = _locked_records(workspace, [key], ensure=key)[key]
    record.config = cleaned
    record.save(update_fields=['config', 'updated_at'])
    transaction.on_commit(lambda: invalidate(workspace.id))
    return record
