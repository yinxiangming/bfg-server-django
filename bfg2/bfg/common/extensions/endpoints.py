# -*- coding: utf-8 -*-
"""
How the platform console shows a workspace's extensions and answers a change to one.

The console lists every extension a workspace can switch on or off, with its state and
configuration, and switches or configures one; see ``bfg.platform.views.console_views``.
Saving a configuration is not recorded against anyone.

``entitled`` and ``available`` are two different questions, and a console needs both.
``entitled`` is whether the workspace may use the extension at all — for a deployment
that sells add-ons, whether it has obtained this one — and ``available`` is whether it
is live right now, which additionally wants the extension switched on and everything it
requires available. An add-on nobody has obtained is therefore ``entitled: false``, and
one that was obtained and then switched off is ``entitled: true, available: false``:
without the first field a console could not tell "buy this" from "switch this back on".
Deployments that sell nothing (no ``BFG_EXTENSION_ENTITLEMENT_CHECK``) have every
extension entitled, which is the same answer they have always given.

``status`` also covers an extension whose data has been archived after long enough
switched off, and the way back from it: ``archiving`` and ``restoring`` while one is
running, ``archived`` once the rows are only in storage. ``status_reason`` says which of
those it is and, after a failed run, that it failed; ``archive`` carries the detail — how
much was archived and when, and the sentence explaining a failure. An archived extension
is not activated but restored, which is a route of its own; see
``bfg.common.extensions.archive``.

``status_changed_by`` is whoever last switched an extension on or off, and what it says
depends on who is asking. A platform administrator is told ``{'id', 'username', 'email'}``.
Anyone else, a workspace owner, is told ``{'id', 'username'}`` when the changer is active
staff or the owner of the workspace, and ``BY_PLATFORM`` otherwise, so the workspace's
side never learns which platform administrator made a change. The console passes
``viewer_is_platform_admin``; without it, the answer is the one an owner gets.

Every function takes the workspace to act on instead of reading it from the request:
console requests sit on a public path, so none is bound to the workspace it acts on.
"""

import logging

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from bfg.common.extensions import registry, services

logger = logging.getLogger(__name__)

#: ``status_changed_by`` for a changer who is neither active staff nor the owner of the
#: workspace, as anyone but a platform administrator is told about them.
BY_PLATFORM = {'id': None, 'username': None, 'by_platform': True}


def user_summary(user):
    """``{'id', 'username', 'email'}`` of ``user``, or ``None`` without one."""
    if user is None:
        return None
    return {'id': user.pk, 'username': user.username, 'email': user.email}


def list_extensions(workspace, *, viewer_is_platform_admin=False):
    """Every extension ``workspace`` can switch on or off, with its state and configuration there, by key."""
    from bfg.common.models import WorkspaceExtension

    records = {
        record.key: record
        for record in WorkspaceExtension.all_objects.filter(workspace=workspace).select_related('status_changed_by')
    }
    # Once for the whole list rather than once a row: the deployment's entitlement check
    # may be a query per extension, and ``available`` is worked out from the same answers.
    entitled = services.compute_entitled_keys(workspace)
    available = services.compute_available_keys(workspace, entitled=entitled)
    describe_changer = _changer_describer(workspace, records.values(), viewer_is_platform_admin)
    return [
        _serialize_extension(
            manifest,
            records.get(manifest.key),
            available,
            entitled,
            workspace,
            describe_changer,
            viewer_is_platform_admin,
        )
        for manifest in registry.all_manifests()
        if manifest.is_activatable
    ]


def extension_state(workspace, key, record=None, *, viewer_is_platform_admin=False):
    """One extension's state and configuration in ``workspace``, as the console shows it.

    ``record`` is the workspace's ``WorkspaceExtension`` when the caller has it in hand,
    such as one it has just changed; otherwise it is read here. Public because the state
    of an extension is worth reporting after something other than a state change — after
    a workspace has obtained the add-on, for one.
    """
    from bfg.common.models import WorkspaceExtension

    if record is None:
        record = (
            WorkspaceExtension.all_objects.filter(workspace=workspace, key=key)
            .select_related('status_changed_by')
            .first()
        )
    entitled = services.compute_entitled_keys(workspace)
    available = services.compute_available_keys(workspace, entitled=entitled)
    describe_changer = _changer_describer(workspace, [record], viewer_is_platform_admin)
    return _serialize_extension(
        registry.get_manifest(key),
        record,
        available,
        entitled,
        workspace,
        describe_changer,
        viewer_is_platform_admin,
    )


def error_response(exc):
    """The answer to a change an extension refused: 404 for a key no app declares, 400 otherwise."""
    http_status = (
        status.HTTP_404_NOT_FOUND if exc.code == 'unknown_extension' else status.HTTP_400_BAD_REQUEST
    )
    return Response({'code': exc.code, 'detail': exc.message, **exc.details}, status=http_status)


def activate(workspace, key, *, user, data, viewer_is_platform_admin=False):
    """Switch ``key`` on for ``workspace``. ``data`` is the request body, which may carry ``config``."""
    config = data.get('config') if hasattr(data, 'get') else None
    return _respond(
        workspace,
        key,
        lambda: services.activate(workspace, key, user=user, config=config),
        viewer_is_platform_admin,
    )


def deactivate(workspace, key, *, user, viewer_is_platform_admin=False):
    """Switch ``key`` off for ``workspace``."""
    return _respond(
        workspace, key, lambda: services.deactivate(workspace, key, user=user), viewer_is_platform_admin
    )


def restore(workspace, key, *, user, viewer_is_platform_admin=False):
    """Bring ``key``'s archived data back for ``workspace`` and switch it on.

    Loading runs here unless ``BFG_EXTENSION_ARCHIVE_RESTORE_ASYNC`` is on, in which case
    the answer comes back ``restoring`` and a worker finishes it. Either way the state and
    the reason say where it has got to, so a console shows the same fields for both.
    """
    from bfg.common.extensions import archive

    def begin_and_load():
        record = archive.begin_restore(workspace, key, user=user)
        if getattr(settings, 'BFG_EXTENSION_ARCHIVE_RESTORE_ASYNC', False):
            from bfg.common.tasks import finish_extension_restore

            transaction.on_commit(
                lambda: finish_extension_restore.delay(workspace.pk, key)
            )
            return record
        return archive.finish_restore(workspace, key)

    try:
        return _respond(workspace, key, begin_and_load, viewer_is_platform_admin)
    except archive.ArchiveNotConfigured as unconfigured:
        return Response(
            {'code': 'archive_not_configured', 'detail': unconfigured.reason},
            status=status.HTTP_409_CONFLICT,
        )


def update_config(workspace, key, *, data, viewer_is_platform_admin=False):
    """Store the ``config`` the request body ``data`` carries for ``key``."""
    if not hasattr(data, 'get') or 'config' not in data:
        return Response(
            {'code': 'invalid_config', 'detail': 'Send the configuration as {"config": {...}}.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return _respond(
        workspace, key, lambda: services.update_config(workspace, key, data['config']), viewer_is_platform_admin
    )


def _respond(workspace, key, change, viewer_is_platform_admin):
    # The extension once ``change`` is made, or why it was refused.
    try:
        record = change()
    except services.ExtensionError as exc:
        return error_response(exc)
    return Response(
        extension_state(workspace, key, record, viewer_is_platform_admin=viewer_is_platform_admin)
    )


def _changer_describer(workspace, records, viewer_is_platform_admin):
    # What status_changed_by says about whoever last switched each of ``records``. Which
    # of those people belong to the workspace is looked up once for all the records.
    if viewer_is_platform_admin:
        return user_summary
    changer_ids = {record.status_changed_by_id for record in records if record is not None} - {None}
    insiders = _insiders(workspace, changer_ids)

    def describe(user):
        if user is None:
            return None
        if user.pk in insiders:
            return {'id': user.pk, 'username': user.username}
        return dict(BY_PLATFORM)

    return describe


def _insiders(workspace, user_ids):
    # Those of ``user_ids`` who are active staff or the owner of ``workspace``, in at most
    # two queries however many there are: the staff, then the owner if anyone is left.
    from bfg.common.models import StaffMember
    # The console lives in bfg.platform, which is also where ownership is recorded.
    from bfg.platform.services.ownership import workspace_owners

    if not user_ids:
        return set()
    insiders = set(
        StaffMember.all_objects.filter(workspace=workspace, user_id__in=user_ids, is_active=True)
        .values_list('user_id', flat=True)
    )
    if user_ids - insiders:
        owner = workspace_owners([workspace.pk]).get(workspace.pk)
        if owner is not None and owner.pk in user_ids:
            insiders.add(owner.pk)
    return insiders


def _serialize_extension(
    manifest, record, available, entitled, workspace, describe_changer, viewer_is_platform_admin=False
):
    # ``record`` is the workspace's WorkspaceExtension for the extension, None when the
    # workspace never used it; ``available`` and ``entitled`` are what
    # services.compute_available_keys and services.compute_entitled_keys returned for the
    # workspace.
    from bfg.common.models import WorkspaceExtension

    return {
        'key': manifest.key,
        'name': str(manifest.name),
        'name_zh': str(manifest.name_zh),
        'description': str(manifest.description),
        'description_zh': str(manifest.description_zh),
        'icon': manifest.icon,
        'admin_url': manifest.admin_url,
        'pricing': manifest.pricing,
        'surfaces': list(manifest.surfaces),
        'requires': list(manifest.requires),
        'meters': list(manifest.meters),
        'config_schema': manifest.config_schema,
        'status': record.status if record else WorkspaceExtension.STATUS_INACTIVE,
        'status_reason': record.status_reason if record else '',
        'status_changed_at': record.status_changed_at if record else None,
        'status_changed_by': describe_changer(record.status_changed_by) if record else None,
        'activated_at': record.activated_at if record else None,
        'available': manifest.key in available,
        'entitled': manifest.key in entitled,
        'unmet_prerequisites': _unmet_prerequisites(manifest, workspace),
        'config': record.config if record else {},
        'archive': _archive_summary(record, viewer_is_platform_admin),
    }


def _archive_summary(record, viewer_is_platform_admin):
    """What has become of the extension's archived data, for a console to show.

    ``status`` and ``status_reason`` already say whether an archive or a restore is
    running and whether the last one failed; this is the detail behind them — how much was
    archived, when, and the sentence explaining a failure, which is longer than
    ``status_reason`` has room for. ``location`` is a key in the deployment's private
    storage and is told to platform administrators only: an owner is being shown what
    happened to their data, not where the deployment keeps it.
    """
    if record is None:
        return None
    state = record.archive_state or {}
    summary = {
        'archived_at': state.get('finished_at') or '',
        'rows': state.get('rows') or 0,
        'tables': state.get('tables') or 0,
        'restored_at': state.get('restored_at') or '',
        'error': state.get('error') or '',
        'error_code': state.get('error_code') or '',
        'failed_at': state.get('failed_at') or '',
    }
    if viewer_is_platform_admin:
        summary['location'] = record.archive_location
    return summary


def _unmet_prerequisites(manifest, workspace):
    # A prerequisite check that raises is reported as unmet, so one broken check
    # cannot take the whole extension list down with it.
    unmet = []
    for prerequisite in manifest.prerequisites:
        try:
            met = prerequisite.is_met(workspace)
        except Exception:
            logger.exception('Prerequisite %s of extension %s failed', prerequisite.code, manifest.key)
            met = False
        if not met:
            unmet.append(prerequisite.message)
    return unmet
