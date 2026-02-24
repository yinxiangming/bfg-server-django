"""
BFG Core Exceptions

Custom exception classes for the BFG system
"""


class BFGException(Exception):
    """BFG base exception class"""
    default_message = "An error occurred"
    default_code = "error"
    
    def __init__(self, message=None, code=None, details=None):
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details or {}
        super().__init__(self.message)


# General exceptions
class ValidationError(BFGException):
    """Data validation error"""
    default_message = "Validation error"
    default_code = "validation_error"


class PermissionDenied(BFGException):
    """Insufficient permissions"""
    default_message = "Permission denied"
    default_code = "permission_denied"


class NotFound(BFGException):
    """Resource not found"""
    default_message = "Resource not found"
    default_code = "not_found"


class AuthenticationFailed(BFGException):
    """Authentication failed"""
    default_message = "Authentication failed"
    default_code = "authentication_failed"
