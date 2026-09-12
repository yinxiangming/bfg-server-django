"""Setting a new password retires every refresh token the account already had.

Anyone can register an account under somebody else's address and keep its
refresh token rotating for as long as they like. Resetting the password is how
the address's owner takes the account back, and changing it is how a signed-in
user shuts out a session they no longer trust, so after either no refresh token
issued before it works, the caller's own included. Access tokens cannot be
revoked and run out their lifetime.
"""

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from bfg.common.models import Workspace
from bfg.common.services import UserService
from bfg.common.views import MeViewSet
from config.serializers import CustomTokenObtainPairSerializer

User = get_user_model()

BLACKLIST_APP = 'rest_framework_simplejwt.token_blacklist'
OLD_PASSWORD = 'Secret-pass-123'
NEW_PASSWORD = 'Other-pass-456'

TOKEN_URL = '/api/v1/auth/token/'
REFRESH_URL = '/api/v1/auth/token/refresh/'
RESET_URL = '/api/v1/auth/reset-password-confirm/'
CHANGE_URL = '/api/v1/me/change-password/'
VERIFY_URL = '/api/v1/auth/verify-email/'


@pytest.fixture(autouse=True)
def _deployed_authentication(production_authentication):
    production_authentication(MeViewSet)


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Acme', slug='acme', is_active=True)


@pytest.fixture
def account(db):
    return User.objects.create_user(
        username='owner', email='owner@example.com', password=OLD_PASSWORD, is_active=True,
    )


def _sign_in(user):
    """The refresh token of a new session, as sign-in and register hand it out."""
    return CustomTokenObtainPairSerializer.get_token(user)


def _refresh(refresh):
    return APIClient().post(REFRESH_URL, {'refresh': str(refresh)}, format='json')


def _reset_password(user):
    """What the link in the password reset mail submits."""
    return APIClient().post(RESET_URL, {
        'uid': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
        'new_password': NEW_PASSWORD,
        'new_password_confirm': NEW_PASSWORD,
    }, format='json')


def _change_password(session, workspace):
    """Change the password while signed in as ``session``."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {session.access_token}', HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client.post(CHANGE_URL, {
        'old_password': OLD_PASSWORD,
        'new_password': NEW_PASSWORD,
        'confirm_password': NEW_PASSWORD,
    }, format='json')


def test_resetting_the_password_retires_refresh_tokens_issued_before(account):
    sessions = [_sign_in(account), _sign_in(account)]

    res = _reset_password(account)

    assert res.status_code == 200, res.data
    assert [_refresh(session).status_code for session in sessions] == [401, 401]


def test_changing_the_password_retires_refresh_tokens_issued_before_the_callers_too(account, workspace):
    elsewhere = _sign_in(account)
    caller = _sign_in(account)

    res = _change_password(caller, workspace)

    assert res.status_code == 200, res.data
    assert res.data == {'detail': 'Password changed successfully'}
    assert _refresh(elsewhere).status_code == 401
    assert _refresh(caller).status_code == 401


@pytest.mark.parametrize('how', ['reset', 'change'])
def test_a_refresh_token_issued_after_the_new_password_works(account, workspace, how):
    res = _reset_password(account) if how == 'reset' else _change_password(_sign_in(account), workspace)
    assert res.status_code == 200, res.data

    signed_in = APIClient().post(TOKEN_URL, {'username': account.username, 'password': NEW_PASSWORD}, format='json')

    assert signed_in.status_code == 200, signed_in.data
    assert _refresh(signed_in.data['refresh']).status_code == 200


def test_confirming_the_address_still_retires_every_refresh_token_issued_before(db):
    user = User.objects.create_user(
        username='waiting', email='waiting@example.com', password=OLD_PASSWORD, is_active=False,
    )
    address = EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=False)
    sessions = [_sign_in(user), _sign_in(user)]
    _sign_in(user).blacklist()

    res = APIClient().post(VERIFY_URL, {'key': EmailConfirmationHMAC(address).key}, format='json')

    assert res.status_code == 200, res.data
    assert [_refresh(session).status_code for session in sessions] == [401, 401]
    assert BlacklistedToken.objects.filter(token__user=user).count() == 3


def test_revoking_does_nothing_without_the_blacklist_app(account, monkeypatch):
    _sign_in(account)
    is_installed = apps.is_installed
    monkeypatch.setattr(apps, 'is_installed', lambda name: name != BLACKLIST_APP and is_installed(name))

    UserService.revoke_refresh_tokens(account)

    assert not BlacklistedToken.objects.exists()
