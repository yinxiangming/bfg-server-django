# -*- coding: utf-8 -*-
"""
Email backend adapters for workspace EmailConfig.
Registry maps backend_type to BackendClass; each backend declares backend_type_id,
label, and config_schema (SchemaConfig) for UI editing and loading.
"""
from .base import BaseEmailBackend
from .smtp import SMTPBackend
from .mailgun import MailgunBackend

_BACKEND_REGISTRY = {
    SMTPBackend.backend_type_id: SMTPBackend,
    MailgunBackend.backend_type_id: MailgunBackend,
}


def get_backend(backend_type: str) -> type:
    """Return backend class for backend_type. Raises KeyError if unknown."""
    return _BACKEND_REGISTRY[backend_type]


def list_backend_types():
    """Return list of {id, label, config_schema} for API and UI (SchemaConfig)."""
    return [
        {
            'id': cls.backend_type_id,
            'label': cls.label,
            'config_schema': getattr(cls, 'config_schema', {}),
        }
        for cls in _BACKEND_REGISTRY.values()
    ]


def get_backend_type_choices():
    """Return Django choices (value, label) for EmailConfig.backend_type from registry."""
    return [(b['id'], b['label']) for b in list_backend_types()]
