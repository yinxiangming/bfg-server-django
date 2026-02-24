"""
BFG Web Module Exceptions

Module-specific exceptions for web module
"""

from bfg.core.exceptions import BFGException


class SiteNotFound(BFGException):
    """Site not found"""
    default_message = "Site not found"
    default_code = "site_not_found"


class PageNotFound(BFGException):
    """Page not found"""
    default_message = "Page not found"
    default_code = "page_not_found"


class PostNotFound(BFGException):
    """Post not found"""
    default_message = "Post not found"
    default_code = "post_not_found"


class MediaUploadFailed(BFGException):
    """Media upload failed"""
    default_message = "Media upload failed"
    default_code = "media_upload_failed"


class InvalidSlug(BFGException):
    """Invalid slug"""
    default_message = "Invalid slug format"
    default_code = "invalid_slug"
