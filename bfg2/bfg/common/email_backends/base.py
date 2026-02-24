# -*- coding: utf-8 -*-
"""
Base email backend interface.
Backends declare backend_type_id, label, and config_schema for UI editing and loading.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


def schema_field(
    field_type: str,
    required: bool = False,
    default: Any = None,
    sensitive: bool = False,
    **kwargs: Any
) -> Dict[str, Any]:
    """Build a config_schema field entry for SchemaConfig (UI edit/load and validation)."""
    out: Dict[str, Any] = {'type': field_type, 'required': required, **kwargs}
    if default is not None:
        out['default'] = default
    if sensitive:
        out['sensitive'] = True
    return out


class BaseEmailBackend(ABC):
    """
    Abstract base for email backends.
    Subclasses must set backend_type_id, label, config_schema and implement send().
    config_schema is used by the API and UI for editing/loading (SchemaConfig).
    """

    backend_type_id: str = ''
    label: str = ''
    config_schema: Dict[str, Dict[str, Any]] = {}

    @abstractmethod
    def send(
        self,
        to_list: List[str],
        subject: str,
        body_plain: str,
        body_html: Optional[str] = None,
        from_email: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        """
        Send email.

        Args:
            to_list: Recipient email addresses.
            subject: Subject line.
            body_plain: Plain text body.
            body_html: Optional HTML body.
            from_email: From address (may be overridden by config).
            config: Backend-specific config dict from EmailConfig.config.

        Raises:
            Exception: On send failure.
        """
        pass
