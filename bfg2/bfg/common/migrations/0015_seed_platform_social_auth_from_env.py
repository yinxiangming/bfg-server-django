# -*- coding: utf-8 -*-
"""Turn the old process-wide OAuth credentials into the platform default row.

Before this release every workspace shared one set of credentials from the
environment. Credentials now come from :class:`SocialAuthConfig` only, so
without this step social login would go dark everywhere the moment the new code
ships.

One row per provider, with no workspace, is the faithful translation: a platform
default is inherited by every workspace, which is exactly what a process-wide
env var was. Copying the same client into a row per workspace would say the same
thing far more loudly and leave N places to rotate a secret in.

Deliberately reads ``os.environ`` rather than ``settings.SOCIALACCOUNT_PROVIDERS``:
the same release removes the ``APP`` blocks from settings, and on a real deploy
the new code is already loaded by the time ``migrate`` runs. The env vars are
still set on the host, so they are the only surviving copy.
"""
import os

from django.db import migrations


# provider -> (client_id env var, secret env var, key env var, certificate env var)
ENV_BY_PROVIDER = {
    'google': ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', None, None),
    'facebook': ('FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET', None, None),
    'apple': ('APPLE_CLIENT_ID', 'APPLE_SECRET', 'APPLE_KEY_ID', 'APPLE_PRIVATE_KEY'),
}


def _credentials_from_env():
    """Return ``{provider: {...field values...}}`` for providers env still has."""
    found = {}
    for provider, (id_var, secret_var, key_var, cert_var) in ENV_BY_PROVIDER.items():
        client_id = (os.environ.get(id_var) or '').strip()
        secret = (os.environ.get(secret_var) or '').strip()
        if not client_id or not secret:
            continue
        entry = {'client_id': client_id, 'secret': secret, 'key': '', 'settings': {}}
        if key_var:
            entry['key'] = (os.environ.get(key_var) or '').strip()
        if cert_var:
            certificate_key = (os.environ.get(cert_var) or '').strip()
            if certificate_key:
                entry['settings'] = {'certificate_key': certificate_key}
        found[provider] = entry
    return found


def seed(apps, schema_editor):
    SocialAuthConfig = apps.get_model('common', 'SocialAuthConfig')
    for provider, entry in _credentials_from_env().items():
        SocialAuthConfig.objects.get_or_create(
            workspace=None,
            provider=provider,
            defaults=dict(entry, is_active=True),
        )


def unseed(apps, schema_editor):
    """Drop only the rows this migration would have written.

    A default an operator has since repointed at their own OAuth client no
    longer matches the environment, and surviving a rollback is the right
    outcome for it.
    """
    SocialAuthConfig = apps.get_model('common', 'SocialAuthConfig')
    for provider, entry in _credentials_from_env().items():
        SocialAuthConfig.objects.filter(
            workspace__isnull=True,
            provider=provider,
            client_id=entry['client_id'],
            secret=entry['secret'],
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0014_socialauthconfig'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
