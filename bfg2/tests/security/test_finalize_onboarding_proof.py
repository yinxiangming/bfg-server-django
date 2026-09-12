"""finalize-onboarding hands out tokens only to a caller who has proven who they are.

Proof is the onboarding token verify-email returns, or a JWT for that user. An
email address on its own proves nothing.
"""

import base64

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from bfg.common.models import StaffMember, StaffRole, Workspace
from config.onboarding_token import make_onboarding_token
from config.serializers import CustomTokenObtainPairSerializer

User = get_user_model()

FINALIZE_URL = '/api/v1/auth/finalize-onboarding/'


@pytest.fixture
def shop_owner(db):
    user = User.objects.create_user(
        username='owner', email='owner@example.com', password='Secret-pass-123', is_active=True,
    )
    workspace = Workspace.objects.create(name='Existing Shop', slug='existing-shop', is_active=True)
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return user


@pytest.fixture
def verified_newcomer(db):
    """An active account with a confirmed address and no workspace yet."""
    user = User.objects.create_user(
        username='newcomer', email='newcomer@example.com', password='Secret-pass-123', is_active=True,
    )
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
    return user


def _finalize(data, bearer=None):
    headers = {} if bearer is None else {'HTTP_AUTHORIZATION': f'Bearer {bearer}'}
    return APIClient().post(FINALIZE_URL, data, format='json', **headers)


def _onboarding_token_for(user):
    return make_onboarding_token(EmailAddress.objects.get(user=user, email=user.email))


def _access_token_for(user):
    return str(CustomTokenObtainPairSerializer.get_token(user).access_token)


def test_email_alone_gets_no_tokens_for_an_existing_shop_owner(shop_owner):
    res = APIClient().post(
        FINALIZE_URL, {'email': shop_owner.email, 'store_name': 'Anything At All'}, format='json',
    )

    assert 'access' not in res.data
    assert 'refresh' not in res.data
    assert res.status_code == 403
    assert not Workspace.objects.filter(slug='anything-at-all').exists()


def test_known_and_unknown_emails_get_the_same_answer(shop_owner, verified_newcomer):
    answers = [
        _finalize({'email': email, 'store_name': 'Some Store'})
        for email in (shop_owner.email, verified_newcomer.email, 'nobody@example.com')
    ]

    assert [res.status_code for res in answers] == [403, 403, 403]
    assert all(res.data == answers[0].data for res in answers)


def test_email_first_signup_finalizes_with_the_token_from_verify_email(db, settings):
    settings.EMAIL_VERIFICATION_REQUIRED = True
    settings.ONBOARDING_PROVISION_ON_REGISTER = False
    settings.SITE_ID = 1
    Site.objects.get_or_create(id=1, defaults={'domain': 'example.com', 'name': 'example.com'})
    client = APIClient()

    registered = client.post('/api/v1/auth/register/', {
        'email': 'jane@example.com',
        'password': 'Strong-pass-123',
        'password_confirm': 'Strong-pass-123',
        'store_name': "Jane's Store",
    }, format='json')
    assert registered.status_code == 201, registered.data
    user = User.objects.get(email='jane@example.com')
    assert not user.is_active

    key = EmailConfirmationHMAC(EmailAddress.objects.get(user=user, email=user.email)).key
    verified = client.post('/api/v1/auth/verify-email/', {'key': key}, format='json')
    assert verified.status_code == 200, verified.data
    onboarding_token = verified.data['onboarding_token']

    replayed_key = client.post('/api/v1/auth/verify-email/', {'key': key}, format='json')
    assert replayed_key.status_code == 400
    assert 'onboarding_token' not in replayed_key.data

    res = client.post(FINALIZE_URL, {
        'onboarding_token': onboarding_token,
        'email': 'jane@example.com',
        'store_name': "Jane's Store",
        'admin_name': 'Jane Example',
    }, format='json')

    assert res.status_code == 200, res.data
    assert res.data['created'] is True
    workspace = Workspace.objects.get(id=res.data['workspace']['id'])
    assert StaffMember.all_objects.filter(user=user, workspace=workspace).exists()
    access = AccessToken(res.data['access'])
    assert str(access['user_id']) == str(user.id)
    assert access['workspace_id'] == workspace.id
    assert res.data['refresh']


def test_the_token_mints_no_tokens_once_the_account_has_a_workspace(verified_newcomer):
    token = _onboarding_token_for(verified_newcomer)
    first = _finalize({'onboarding_token': token, 'store_name': 'First Store'})
    assert first.status_code == 200, first.data

    replay = _finalize({'onboarding_token': token, 'store_name': 'Second Store'})

    assert replay.status_code == 409
    assert 'access' not in replay.data
    assert not Workspace.objects.filter(slug='second-store').exists()


def test_a_valid_token_does_not_unlock_an_existing_shop_owner(shop_owner):
    EmailAddress.objects.create(user=shop_owner, email=shop_owner.email, primary=True, verified=True)

    res = _finalize({'onboarding_token': _onboarding_token_for(shop_owner), 'store_name': 'Another Store'})

    assert res.status_code == 409
    assert 'access' not in res.data
    assert not Workspace.objects.filter(slug='another-store').exists()


def test_signed_in_owner_gets_their_existing_workspace(shop_owner):
    EmailAddress.objects.create(user=shop_owner, email=shop_owner.email, primary=True, verified=True)

    res = _finalize({'store_name': 'Another Store'}, bearer=_access_token_for(shop_owner))

    assert res.status_code == 200, res.data
    assert res.data['created'] is False
    assert res.data['workspace']['slug'] == 'existing-shop'
    assert res.data['access']


def test_signed_in_newcomer_needs_no_onboarding_token(verified_newcomer):
    res = _finalize({'store_name': 'Fresh Store'}, bearer=_access_token_for(verified_newcomer))

    assert res.status_code == 200, res.data
    assert res.data['created'] is True


@pytest.mark.parametrize('verification_required, expected_status', [(True, 403), (False, 200)])
def test_signed_in_account_without_a_confirmed_address(db, settings, verification_required, expected_status):
    settings.EMAIL_VERIFICATION_REQUIRED = verification_required
    user = User.objects.create_user(
        username='unconfirmed', email='unconfirmed@example.com', password='Secret-pass-123', is_active=True,
    )

    res = _finalize({'store_name': 'Fresh Store'}, bearer=_access_token_for(user))

    assert res.status_code == expected_status, res.data


def test_an_onboarding_token_always_needs_a_confirmed_address(verified_newcomer, settings):
    settings.EMAIL_VERIFICATION_REQUIRED = False
    address = EmailAddress.objects.get(user=verified_newcomer)
    token = make_onboarding_token(address)
    address.verified = False
    address.save()

    res = _finalize({'onboarding_token': token, 'store_name': 'Fresh Store'})

    assert res.status_code == 403
    assert 'access' not in res.data


def test_a_session_or_password_is_not_a_sign_in_here(verified_newcomer):
    session = APIClient()
    session.force_login(verified_newcomer)
    basic = base64.b64encode(b'newcomer:Secret-pass-123').decode()

    answers = [
        session.post(FINALIZE_URL, {'store_name': 'Fresh Store'}, format='json'),
        APIClient().post(
            FINALIZE_URL, {'store_name': 'Fresh Store'}, format='json', HTTP_AUTHORIZATION=f'Basic {basic}',
        ),
    ]

    assert [res.status_code for res in answers] == [403, 403]
    assert not Workspace.objects.filter(slug='fresh-store').exists()


@pytest.mark.parametrize('broken', [
    'address_unverified', 'address_missing', 'user_inactive', 'email_changed',
    'token_expired', 'token_tampered', 'body_email_differs',
])
def test_token_is_refused_when_the_proof_does_not_hold(verified_newcomer, shop_owner, settings, broken):
    address = EmailAddress.objects.get(user=verified_newcomer)
    body = {'onboarding_token': make_onboarding_token(address), 'store_name': 'Fresh Store'}
    if broken == 'address_unverified':
        address.verified = False
        address.save()
    elif broken == 'address_missing':
        address.delete()
    elif broken == 'user_inactive':
        verified_newcomer.is_active = False
        verified_newcomer.save()
    elif broken == 'email_changed':
        verified_newcomer.email = 'someone-else@example.com'
        verified_newcomer.save()
    elif broken == 'token_expired':
        settings.ONBOARDING_TOKEN_MAX_AGE = -1
    elif broken == 'token_tampered':
        body['onboarding_token'] += 'x'
    elif broken == 'body_email_differs':
        body['email'] = shop_owner.email

    res = _finalize(body)

    assert res.status_code == 403
    assert 'access' not in res.data
    assert not Workspace.objects.filter(slug='fresh-store').exists()
