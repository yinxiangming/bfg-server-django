"""
BFG2 Core Module

Export all core utilities
"""

from .exceptions import *
from .services import BaseService
from .managers import WorkspaceManager, BaseManager
from .cache import CacheMixin, CacheService
from .events import global_dispatcher, EventDispatcher
from .permissions import (
    IsWorkspaceAdmin,
    IsWorkspaceStaff,
    HasPermission,
    IsOwnerOrStaff,
)
from .middleware import WorkspaceMiddleware
from .schema_convert import (
    pydantic_model_to_config_schema,
    pydantic_model_to_form_schema,
    validation_error_to_message,
)

__all__ = [
    # Exceptions
    'BFGException',
    'ValidationError',
    'PermissionDenied',
    'NotFound',
    'AuthenticationFailed',
    # Services
    'BaseService',
    # Managers
    'WorkspaceManager',
    'BaseManager',
    # Cache
    'CacheMixin',
    'CacheService',
    # Events
    'global_dispatcher',
    'EventDispatcher',
    # Permissions
    'IsWorkspaceAdmin',
    'IsWorkspaceStaff',
    'HasPermission',
    'IsOwnerOrStaff',
    # Middleware
    'WorkspaceMiddleware',
    # Schema conversion (Pydantic -> client SchemaConfigEditor / SchemaForm)
    'pydantic_model_to_config_schema',
    'pydantic_model_to_form_schema',
    'validation_error_to_message',
]
