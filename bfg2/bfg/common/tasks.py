# -*- coding: utf-8 -*-
"""
Background work for bfg.common.

Each task is a wrapper and nothing more: what it does lives in a service that a
management command calls just as well, because neither deployment runs a scheduler and
the command is the entry point that always works. A task that held logic of its own
would be logic nobody could run by hand.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def archive_unused_extensions(limit=None):
    """Archive the extensions that have been switched off for long enough.

    The same sweep as ``manage.py archive_unused_extensions``. Answers what it did, so a
    worker's result carries the same report the command prints.
    """
    from bfg.common.extensions import archive

    return archive.sweep(limit=limit)


@shared_task
def finish_extension_restore(workspace_id, key):
    """Load back the archive of an extension already on ``restoring``.

    Queued by a console that answers a restore request before the loading is done; the
    record is on ``restoring`` before this is queued, so a request that finds it there
    knows why. A failure puts it back on ``archived`` with the reason, which is the answer
    the console shows — there is nothing here to retry into, since the same request again
    is the same work again.
    """
    from bfg.common.extensions import archive
    from bfg.common.models import Workspace

    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        logger.error('Cannot restore extension %s: workspace %s is gone', key, workspace_id)
        return None
    record = archive.finish_restore(workspace, key)
    return {'workspace_id': workspace_id, 'key': key, 'status': record.status}
