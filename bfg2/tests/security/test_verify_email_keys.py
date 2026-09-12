"""verify-email confirms an address only for a key allauth accepts.

finalize-onboarding trusts the onboarding token verify-email returns in place of
a sign-in, so a declined, expired or used key gets a 400, no token, and leaves
the account inactive.
"""

from datetime import timedelta

import pytest
from allauth.account import app_settings as account_settings
from allauth.account.models import EmailAddress, EmailConfirmation, EmailConfirmationHMAC
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

User = get_user_model()

VERIFY_URL = '/api/v1/auth/verify-email/'


@pytest.fixture
def waiting_account(db):
    """An account that registered and has not confirmed its address yet."""
    user = User.objects.create_user(
        username='waiting', email='waiting@example.com', password='Secret-pass-123', is_active=False,
    )
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=False)
    return user


def _verify(key):
    return APIClient().post(VERIFY_URL, {'key': key}, format='json')


def _db_backed_key(user, sent):
    """A key from an EmailConfirmation row, as older confirmation mails carry."""
    address = EmailAddress.objects.get(user=user, email=user.email)
    return EmailConfirmation.objects.create(email_address=address, key='k' * 64, sent=sent).key


def test_an_address_verified_on_another_account_is_declined(waiting_account):
    holder = User.objects.create_user(
        username='holder', email=waiting_account.email, password='Secret-pass-123', is_active=True,
    )
    EmailAddress.objects.create(user=holder, email=holder.email, primary=True, verified=True)

    res = _verify(EmailConfirmationHMAC(EmailAddress.objects.get(user=waiting_account)).key)

    assert res.status_code == 400
    assert 'onboarding_token' not in res.data
    waiting_account.refresh_from_db()
    assert not waiting_account.is_active
    assert not EmailAddress.objects.get(user=waiting_account).verified


def test_an_expired_db_backed_key_is_refused(waiting_account):
    sent = timezone.now() - timedelta(days=account_settings.EMAIL_CONFIRMATION_EXPIRE_DAYS, hours=1)

    res = _verify(_db_backed_key(waiting_account, sent))

    assert res.status_code == 400
    assert 'onboarding_token' not in res.data
    waiting_account.refresh_from_db()
    assert not waiting_account.is_active


def test_a_db_backed_key_confirms_once(waiting_account):
    key = _db_backed_key(waiting_account, timezone.now())

    first = _verify(key)
    replay = _verify(key)

    assert first.status_code == 200, first.data
    assert first.data['onboarding_token']
    assert replay.status_code == 400
    assert 'onboarding_token' not in replay.data
