# -*- coding: utf-8 -*-
"""
Celery tasks for core module.
Currently just the Google Analytics 4 Measurement Protocol delivery task;
the payloads it sends are built in bfg.core.analytics.
"""

import logging

import requests
from celery import shared_task

logger = logging.getLogger(__name__)

# Short on purpose. This runs off the request path, but a worker blocked on
# Google's endpoint is a worker not sending anyone's order confirmation.
GA4_TIMEOUT_SECONDS = 5


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def deliver_ga4_events(self, workspace_id: int, payload: dict):
    """
    POST an already-built Measurement Protocol payload to GA4.

    Args:
        workspace_id: Workspace the events belong to; used to resolve which GA4
            property they go to, so the credentials are never queued through the
            broker alongside the payload.
        payload: ``{'client_id': ..., 'events': [...], 'user_id': ...}``

    The measurement id and secret are resolved here rather than passed in for two
    reasons: the api_secret would otherwise sit in plain text in Redis for the life
    of the queue, and a task retried after a workspace was reconfigured should use
    the current property, not the one that applied when it was queued.
    """
    from bfg.core.analytics import GA4_COLLECT_URL, get_api_secret, get_measurement_id

    measurement_id = get_measurement_id(workspace_id)
    api_secret = get_api_secret(measurement_id)
    if not measurement_id or not api_secret:
        # Reconfigured out from under the queued task; nothing to retry towards.
        logger.info('GA4: dropping queued events for workspace %s — no longer configured', workspace_id)
        return

    try:
        response = requests.post(
            GA4_COLLECT_URL,
            params={'measurement_id': measurement_id, 'api_secret': api_secret},
            json=payload,
            timeout=GA4_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # Network blips are worth another go; the payload carries its own
        # timestamps so a delayed retry still lands on the right events.
        raise self.retry(exc=exc)

    # The collect endpoint answers 2xx for anything it accepted and does not report
    # per-event validation problems here at all — use GA4's DebugView, or the
    # /debug/mp/collect endpoint, when an event does not show up.
    if response.status_code >= 500:
        raise self.retry(exc=Exception(f'GA4 returned {response.status_code}'))
    if response.status_code >= 400:
        logger.warning(
            'GA4: rejected events for workspace %s with %s: %s',
            workspace_id, response.status_code, response.text[:200],
        )
