# -*- coding: utf-8 -*-
"""
Server-side Google Analytics 4 reporting (Measurement Protocol).

gtag.js only ever sees a browser. The WeChat mini-program talks straight to this
API, so every mini-program order is invisible to the web storefront's tag — and
one deployment serves many workspaces, each with its own GA4 property. Reporting
from here covers every client at once, without a tag per client.

Configuration is split on purpose:

* the **measurement id** is a public client-side tag id and travels with the rest
  of the workspace's storefront config, at
  ``Settings.custom_settings['analytics']['google_analytics_id']`` — the same
  value the browser tag uses, editable by a workspace admin in the back office;
* the **api_secret** is a write credential no admin needs to read, and
  ``SettingsSerializer`` echoes ``custom_settings`` wholesale, so putting it there
  would hand it to every workspace admin through the settings API. It lives in the
  ``GA4_MP_API_SECRETS`` env map instead, keyed by measurement id so the secret
  follows the property rather than a workspace id.

Every entry point is a no-op when the workspace has no measurement id or no
matching secret, mirroring the client-side helper: a workspace without GA4 simply
records nothing, and callers never have to guard.
"""

import hashlib
import logging

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

GA4_COLLECT_URL = 'https://www.google-analytics.com/mp/collect'

# GA4 rejects a payload carrying more than 25 events, and silently drops the
# excess rather than erroring, so cap on our side where it is visible.
MAX_EVENTS_PER_REQUEST = 25


def get_measurement_id(workspace_id):
    """The workspace's GA4 measurement id, or '' when it has none configured."""
    if not workspace_id:
        return ''
    # Imported here rather than at module scope: bfg.common imports bfg.core, so a
    # top-level import would close the cycle.
    from bfg.common.models import Settings

    settings_obj = Settings.objects.filter(workspace_id=workspace_id).only('custom_settings').first()
    if not settings_obj:
        return ''
    analytics = (settings_obj.custom_settings or {}).get('analytics') or {}
    return str(analytics.get('google_analytics_id') or '').strip()


def get_api_secret(measurement_id):
    """The Measurement Protocol secret paired with ``measurement_id``, or ''."""
    if not measurement_id:
        return ''
    secrets = getattr(django_settings, 'GA4_MP_API_SECRETS', None) or {}
    return str(secrets.get(measurement_id) or '').strip()


def client_id_for_customer(customer_id, workspace_id):
    """
    A stable pseudonymous GA4 ``client_id`` for a customer.

    GA4 requires a client_id on every event, but a server has no ``_ga`` cookie to
    read — and the mini-program has no cookies at all. Hashing the pair gives one
    id that is stable across a customer's orders (so repeat purchases collapse into
    one user) and distinct per workspace (so the same person shopping two of our
    storefronts is not merged across properties).

    It is deliberately *not* the customer id in the clear: this value is sent to a
    third party, and a raw primary key would let anyone holding the GA4 export join
    it straight back to our database.

    Note this does not match the ``_ga`` cookie the browser tag uses, so a web
    shopper counts as one user for their page views and another for a server-sent
    purchase. ``user_id`` is set alongside it to make them stitchable — the web tag
    would need to send the same ``user_id`` for that to take effect.
    """
    if not customer_id:
        return ''
    raw = f'{workspace_id}:{customer_id}'.encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    # GA4 expects the `<digits>.<digits>` shape browsers produce. It accepts other
    # strings, but staying in the familiar format keeps the DebugView readable.
    return f'{int(digest[:8], 16)}.{int(digest[8:16], 16)}'


def track(workspace_id, client_id, name, params=None, user_id=None):
    """
    Queue a single GA4 event. Returns True when it was handed to Celery.

    Fire-and-forget by design: analytics must never add latency to, or fail, the
    request that triggered it.
    """
    return track_many(workspace_id, client_id, [{'name': name, 'params': params or {}}], user_id=user_id)


def track_many(workspace_id, client_id, events, user_id=None):
    """Queue several events for one client in a single Measurement Protocol call."""
    if not client_id or not events:
        return False

    measurement_id = get_measurement_id(workspace_id)
    if not measurement_id:
        return False
    if not get_api_secret(measurement_id):
        # Worth a warning rather than silence: the workspace has opted into GA4 by
        # setting a measurement id, so a missing secret is a deployment gap, not a
        # workspace that simply does not use analytics.
        logger.warning(
            'GA4: workspace %s has measurement id %s but no GA4_MP_API_SECRETS entry; '
            'server-side events are being dropped',
            workspace_id, measurement_id,
        )
        return False

    payload = {
        'client_id': client_id,
        'events': events[:MAX_EVENTS_PER_REQUEST],
    }
    if user_id:
        payload['user_id'] = str(user_id)

    from bfg.core.tasks import deliver_ga4_events

    try:
        deliver_ga4_events.delay(workspace_id, payload)
    except Exception:
        # A broker that is down must not take the caller with it — losing an
        # analytics event is always preferable to failing the order that produced it.
        logger.exception('GA4: could not queue events for workspace %s', workspace_id)
        return False
    return True
