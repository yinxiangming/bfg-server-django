"""
BFG Common Module Exceptions

Module-specific exceptions for common module
"""

from bfg.core.exceptions import BFGException


class WorkspaceAlreadyExists(BFGException):
    """Workspace already exists"""
    default_message = "Workspace already exists"
    default_code = "workspace_already_exists"


class CustomerNotFound(BFGException):
    """Customer not found"""
    default_message = "Customer not found"
    default_code = "customer_not_found"


class VerificationEmailNotSent(BFGException):
    """The mail that confirms an address could not be sent"""
    default_message = "The confirmation email could not be sent"
    default_code = "verification_email_not_sent"
