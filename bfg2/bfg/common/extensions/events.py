# -*- coding: utf-8 -*-
"""
Hear events only from the workspaces that use an extension.

    from bfg.common.extensions import listen_for

    listen_for('reviews', 'order.delivered', ask_for_a_review)

The callback is registered with ``global_dispatcher`` like any other listener, and is
called only while the extension is available to the workspace the event belongs to.
The listener of a workspace extension skips an event that names no workspace, and
logs a warning the first time it does.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional

from bfg.common.extensions import registry, services
from bfg.common.extensions.manifest import SCOPE_WORKSPACE

logger = logging.getLogger(__name__)


def event_workspace(event_data) -> Optional[Any]:
    """The workspace an event belongs to, or ``None``.

    ``BaseService.emit_event`` puts it at the top of the event; an event such as
    ``workspace.created`` carries it in ``data`` instead.
    """
    if not isinstance(event_data, dict):
        return None
    workspace = event_data.get('workspace')
    data = event_data.get('data')
    if workspace is None and isinstance(data, dict):
        workspace = data.get('workspace')
    return workspace


def listen_for(
    key: str,
    event_name: str,
    callback: Callable[[dict], Any],
    *,
    workspace_of: Optional[Callable[[dict], Any]] = None,
) -> Callable[[dict], Any]:
    """Register ``callback`` for ``event_name``, called only while ``key`` is available.

    ``workspace_of`` takes the event and returns its workspace, for an event that keeps
    it somewhere ``event_workspace`` does not look. Returns the listener as registered;
    ``global_dispatcher.remove_listener`` accepts either it or ``callback``.
    """
    from bfg.core.events import global_dispatcher

    find_workspace = workspace_of or event_workspace
    reported = set()

    def report_once(problem, level, message):
        # A listener that never runs leaves no other trace. Once per listener is enough
        # to find it without repeating the line for every event.
        if problem not in reported:
            reported.add(problem)
            logger.log(level, message, callback, event_name, key)

    @functools.wraps(callback)
    def listener(event_data):
        manifest = registry.get_manifest(key)
        if manifest is None:
            report_once(
                'undeclared', logging.ERROR,
                'Listener %r for %s waits on extension %r, which no installed app declares',
            )
            return None
        workspace = find_workspace(event_data)
        if workspace is None and manifest.scope == SCOPE_WORKSPACE:
            report_once(
                'no_workspace', logging.WARNING,
                'Listener %r skipped a %s event that names no workspace; %r is switched on per workspace',
            )
            return None
        if not services.is_available(workspace, key):
            return None
        return callback(event_data)

    global_dispatcher.listen(event_name, listener)
    return listener
