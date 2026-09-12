# -*- coding: utf-8 -*-
"""
Onboarding tokens carry a confirmed email address from verify-email to
finalize-onboarding.

finalize-onboarding hands out a JWT pair, so it cannot take an email address on
trust. verify-email has just consumed the key from the confirmation mail, so it
returns one of these instead: it names the user and the address, is signed with
SECRET_KEY, and expires after ``ONBOARDING_TOKEN_MAX_AGE`` seconds.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing

SALT = 'config.onboarding-token'
DEFAULT_MAX_AGE = 60 * 60


def make_onboarding_token(email_address):
    """Sign a token for an allauth ``EmailAddress`` that was just confirmed."""
    return signing.dumps(
        {'user': email_address.user_id, 'email': email_address.email.lower()},
        salt=SALT,
    )


def user_for_onboarding_token(token):
    """Return the user a still-valid token was issued to, or ``None``.

    A token stops counting once the user's email address changes.
    """
    if not token:
        return None
    max_age = getattr(settings, 'ONBOARDING_TOKEN_MAX_AGE', DEFAULT_MAX_AGE)
    try:
        claims = signing.loads(token, salt=SALT, max_age=max_age)
    except signing.BadSignature:  # SignatureExpired is a subclass
        return None
    user = get_user_model().objects.filter(pk=claims.get('user')).first()
    if user is None or (user.email or '').lower() != claims.get('email'):
        return None
    return user
