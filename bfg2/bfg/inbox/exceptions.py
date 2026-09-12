# -*- coding: utf-8 -*-
"""
Exceptions raised by the inbox module.
"""

from bfg.core.exceptions import ValidationError


class TemplateNotFound(ValidationError):
    """
    No active message template for a notification, in the workspace or the platform.

    A configuration gap rather than a transient failure: a task should log it and
    stop, because no retry can create the template. Subclasses ValidationError,
    which is what ``MessageService.send_from_template`` raised before, so callers
    that catch that keep working.
    """
