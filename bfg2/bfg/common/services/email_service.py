# -*- coding: utf-8 -*-
"""
Workspace email sending service. Uses active EmailConfig per workspace.
Supports optional config argument to avoid repeated DB hits during bulk send.
"""
import logging
from typing import List, Optional

from bfg.common.models import EmailConfig, Workspace
from bfg.common.email_backends import get_backend

logger = logging.getLogger(__name__)


class EmailService:
    """
    Send email using workspace's active EmailConfig (is_default + is_active).
    Does not fall back to server-level Django EMAIL_*.
    Pass config= to use a pre-fetched EmailConfig and avoid DB access (e.g. bulk send).
    """

    @staticmethod
    def get_active_config(workspace: Workspace) -> Optional[EmailConfig]:
        """Return the workspace's default active EmailConfig, or None."""
        return EmailConfig.objects.filter(
            workspace=workspace,
            is_default=True,
            is_active=True,
        ).first()

    @staticmethod
    def send_email(
        workspace: Workspace,
        to_list: List[str],
        subject: str,
        body_plain: str,
        body_html: Optional[str] = None,
        from_email: Optional[str] = None,
        config: Optional[EmailConfig] = None,
    ) -> None:
        """
        Send email using workspace's active EmailConfig, or the given config.

        When sending in bulk, pass a pre-fetched config (e.g. from get_active_config
        once per batch) to avoid querying the database for every message.

        Args:
            workspace: Workspace (used only when config is None).
            to_list: Recipient emails.
            subject: Subject.
            body_plain: Plain text body.
            body_html: Optional HTML body.
            from_email: Optional from address override.
            config: Optional EmailConfig instance; if None, fetches active config for workspace.

        Raises:
            ValueError: If no active config when config is None.
        """
        if config is None:
            config = EmailService.get_active_config(workspace)
        if not config:
            raise ValueError(
                f"No active email config for workspace {workspace.id}. "
                "Set an EmailConfig as default in Admin > Settings > General > Email."
            )
        backend_class = get_backend(config.backend_type)
        backend = backend_class()
        backend.send(
            to_list=to_list,
            subject=subject,
            body_plain=body_plain,
            body_html=body_html,
            from_email=from_email,
            config=config.config,
        )
