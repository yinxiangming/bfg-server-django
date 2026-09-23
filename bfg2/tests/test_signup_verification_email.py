"""
The mail merchant sign-up sends to confirm the new account's address.

allauth builds its link by reversing ``account_confirm_email``, a view this API does
not serve, and names the site after the ``django.contrib.sites`` row. So building the
mail raised ``NoReverseMatch``; the error was logged and swallowed, sign-up answered
201, and the account, inactive until confirmed, could never be used.
"""

import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory
from rest_framework.test import APIClient

from config.account_adapter import frontend_base_url

User = get_user_model()

REGISTER_URL = '/api/v1/auth/register/'
VERIFY_URL = '/api/v1/auth/verify-email/'


@pytest.fixture
def signup(db, settings):
    settings.EMAIL_VERIFICATION_REQUIRED = True
    settings.ONBOARDING_PROVISION_ON_REGISTER = False
    settings.SITE_ID = 1  # the placeholder "example.com" row
    settings.SITE_NAME = 'Acme Commerce'
    settings.FRONTEND_URL = 'https://app.acme.test'
    settings.FRONTEND_EMAIL_CONFIRM_PATH = '/auth/verify-email'
    settings.CORS_ALLOWED_ORIGINS = ['https://shop.acme.test']

    def register(email, origin='https://shop.acme.test'):
        return APIClient().post(REGISTER_URL, {
            'email': email,
            'password': 'Strong-pass-123',
            'password_confirm': 'Strong-pass-123',
            'store_name': 'Acme Shop',
        }, format='json', HTTP_ORIGIN=origin)

    return register


def mailed_link(message):
    match = re.search(r'https?://\S+', message.body)
    assert match, message.body
    return urlsplit(match.group(0))


def test_signup_mails_a_link_to_the_frontend_it_came_from(signup):
    res = signup('jane@acme.test')

    assert res.status_code == 201, res.data
    assert res.data['email_verification_required'] is True
    [message] = mail.outbox
    assert message.to == ['jane@acme.test']
    link = mailed_link(message)
    assert (link.scheme, link.netloc, link.path) == ('https', 'shop.acme.test', '/auth/verify-email')
    assert parse_qs(link.query)['key']


def test_the_mail_names_the_site_rather_than_the_placeholder_site_row(signup):
    signup('named@acme.test')

    [message] = mail.outbox
    assert message.subject.startswith('[Acme Commerce] ')
    assert 'Hello from Acme Commerce!' in message.body
    assert 'register an account on shop.acme.test' in message.body
    assert 'example.com' not in message.subject + message.body


def test_the_mail_uses_the_cluster_brand_when_configured(signup, settings):
    settings.CLUSTER_NAME = 'Community Cluster'
    settings.SITE_NAME = 'Surlex'

    signup('cluster-branded@acme.test')

    [message] = mail.outbox
    assert message.subject.startswith('[Community Cluster] ')
    assert 'Hello from Community Cluster!' in message.body
    assert 'Surlex' not in message.subject + message.body


def test_an_origin_outside_the_allowlist_gets_the_configured_frontend(signup):
    signup('elsewhere@acme.test', origin='https://attacker.test')

    [message] = mail.outbox
    link = mailed_link(message)
    assert (link.netloc, link.path) == ('app.acme.test', '/auth/verify-email')


def test_server_attested_frontend_origin_does_not_require_cors_allowlisting(settings):
    settings.FRONTEND_URL = 'https://app.acme.test'
    settings.CORS_ALLOWED_ORIGINS = []
    request = RequestFactory().post('/register', HTTP_ORIGIN='https://attacker.test')
    request._trusted_frontend_origin = 'https://idlevo.test'

    assert frontend_base_url(request) == 'https://idlevo.test'


@pytest.mark.parametrize(
    'value',
    [
        'http://idlevo.test',
        'https://user:pass@idlevo.test',
        'https://idlevo.test/path',
        'https://idlevo.test?next=attacker',
        '//idlevo.test',
    ],
)
def test_invalid_server_attested_origin_falls_back_to_configured_frontend(settings, value):
    settings.FRONTEND_URL = 'https://app.acme.test'
    settings.CORS_ALLOWED_ORIGINS = []
    request = RequestFactory().post('/register')
    request._trusted_frontend_origin = value

    assert frontend_base_url(request) == 'https://app.acme.test'


def test_server_attested_localhost_may_use_http(settings):
    settings.FRONTEND_URL = 'https://app.acme.test'
    request = RequestFactory().post('/register')
    request._trusted_frontend_origin = 'http://localhost:3011'

    assert frontend_base_url(request) == 'http://localhost:3011'


def test_the_mailed_key_activates_the_account(signup):
    signup('verify@acme.test')
    [key] = parse_qs(mailed_link(mail.outbox[0]).query)['key']

    res = APIClient().post(VERIFY_URL, {'key': key}, format='json')

    assert res.status_code == 200, res.data
    assert res.data['onboarding_token']
    user = User.objects.get(email='verify@acme.test')
    assert user.is_active
    assert EmailAddress.objects.get(user=user, email=user.email).verified


def test_a_mail_that_cannot_be_sent_fails_the_signup_and_keeps_nothing(signup):
    with patch('django.core.mail.EmailMessage.send', side_effect=ConnectionError('mail server down')):
        res = signup('lost@acme.test')

    assert res.status_code == 503, res.data
    assert not User.objects.filter(email='lost@acme.test').exists()
    # So the same address can sign up again once mail goes out.
    assert signup('lost@acme.test').status_code == 201
    assert len(mail.outbox) == 1
