# -*- coding: utf-8 -*-
"""Account emails that link to the frontend and name the real site.

allauth builds the address confirmation link by reversing its own
``account_confirm_email`` view. This API serves no such view: confirming an
address is a frontend page, which posts the key to ``/api/v1/auth/verify-email/``.
So building the sign-up mail raised ``NoReverseMatch``.

allauth also names the site after the ``django.contrib.sites`` row, which nothing
here maintains, so a mail that did go out would come from "example.com".
"""
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

from allauth.account import app_settings
from allauth.account.adapter import DefaultAccountAdapter
from allauth.core import context as allauth_context
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.utils.encoding import force_str

DEFAULT_EMAIL_CONFIRM_PATH = '/auth/verify-email'


def frontend_base_url(request):
    """The frontend a request came from when it is an allowed one, else ``FRONTEND_URL``.

    ``Origin`` only counts when it is in ``CORS_ALLOWED_ORIGINS``; otherwise anyone
    could have a confirmation link point at a host of their choosing. Without a
    request there is only ``FRONTEND_URL``, which may be blank.
    """
    if request is None:
        return (getattr(settings, 'FRONTEND_URL', '') or '').strip().rstrip('/')

    from config.social_auth import _get_frontend_base_url

    origin_host = urlsplit(request.headers.get('Origin') or '').hostname
    return _get_frontend_base_url(request, requested_host=origin_host)


class AccountAdapter(DefaultAccountAdapter):
    """Confirmation links go to the frontend's page; mails are named after ``SITE_NAME``."""

    def get_email_confirmation_url(self, request, emailconfirmation):
        base = frontend_base_url(request)
        if not base:
            return super().get_email_confirmation_url(request, emailconfirmation)
        path = getattr(settings, 'FRONTEND_EMAIL_CONFIRM_PATH', '') or DEFAULT_EMAIL_CONFIRM_PATH
        return f'{base}{path}?{urlencode({"key": emailconfirmation.key})}'

    def format_email_subject(self, subject):
        if app_settings.EMAIL_SUBJECT_PREFIX is not None:
            return super().format_email_subject(subject)
        return f'[{self._site_name()}] {force_str(subject)}'

    def send_mail(self, template_prefix, email, context):
        # The templates greet with current_site.name and quote current_site.domain.
        request = allauth_context.request
        site = SimpleNamespace(
            name=self._site_name(),
            domain=urlsplit(frontend_base_url(request)).hostname or get_current_site(request).domain,
        )
        super().send_mail(template_prefix, email, {'current_site': site, **context})

    @staticmethod
    def _site_name():
        return getattr(settings, 'SITE_NAME', '') or get_current_site(allauth_context.request).name
