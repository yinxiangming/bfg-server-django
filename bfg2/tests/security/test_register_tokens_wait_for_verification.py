"""An account that waits on its confirmation mail holds no live tokens.

Anyone can register any address. Tokens handed to the still-inactive account
would start working once the address's owner clicked the link, in the hands of
whoever registered. register hands out none until then, and confirming the
address retires any refresh token the account already had.
"""

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from rest_framework.test import APIClient
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from config.serializers import CustomTokenObtainPairSerializer

User = get_user_model()

REGISTER_URL = '/api/v1/auth/register/'
VERIFY_URL = '/api/v1/auth/verify-email/'


def _register(email):
    return APIClient().post(REGISTER_URL, {
        'email': email,
        'password': 'Strong-pass-123',
        'password_confirm': 'Strong-pass-123',
    }, format='json')


def _account_with_unconfirmed_address(username, is_active):
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password='Secret-pass-123', is_active=is_active,
    )
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=False)
    return user


def _confirm(user):
    key = EmailConfirmationHMAC(EmailAddress.objects.get(user=user, email=user.email)).key
    return APIClient().post(VERIFY_URL, {'key': key}, format='json')


def test_register_hands_out_no_tokens_before_the_address_is_confirmed(db, settings):
    settings.EMAIL_VERIFICATION_REQUIRED = True
    settings.ONBOARDING_PROVISION_ON_REGISTER = False
    settings.SITE_ID = 1
    Site.objects.get_or_create(id=1, defaults={'domain': 'example.com', 'name': 'example.com'})

    res = _register('owner@victim.example')

    assert res.status_code == 201, res.data
    assert 'access' not in res.data
    assert 'refresh' not in res.data
    assert res.data['email_verification_required'] is True
    assert res.data['user']['email'] == 'owner@victim.example'
    assert not User.objects.get(email='owner@victim.example').is_active


def test_register_signs_in_at_once_without_email_verification(db, settings):
    settings.EMAIL_VERIFICATION_REQUIRED = False

    res = _register('jane@example.com')

    assert res.status_code == 201, res.data
    assert res.data['email_verification_required'] is False
    assert str(AccessToken(res.data['access'])['user_id']) == str(res.data['user']['id'])
    assert res.data['refresh']


def test_confirming_the_address_retires_refresh_tokens_issued_before(db):
    user = _account_with_unconfirmed_address('waiting', is_active=False)
    refresh = str(CustomTokenObtainPairSerializer.get_token(user))

    res = _confirm(user)

    assert res.status_code == 200, res.data
    with pytest.raises(TokenError):
        RefreshToken(refresh)


def test_confirming_an_address_leaves_an_active_accounts_tokens_alone(db):
    user = _account_with_unconfirmed_address('active', is_active=True)
    refresh = str(CustomTokenObtainPairSerializer.get_token(user))

    res = _confirm(user)

    assert res.status_code == 200, res.data
    RefreshToken(refresh)  # raises TokenError once blacklisted
