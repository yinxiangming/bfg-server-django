"""Storefront analytics ingest — a relay so non-browser clients can reach GA4.

A WeChat mini-program cannot run gtag.js, and it cannot call Google directly
either: `wx.request` is restricted to the domains configured in the mini-program
console, and a shopper on a network that cannot reach Google would silently
report nothing. It can already talk to this API, so it posts its events here and
we forward them.

Sending them from here also keeps the Measurement Protocol api_secret on the
server. Shipping that in a mini-program bundle would publish it — bundles are
downloadable and trivially unpacked.

**On trusting the caller:** this endpoint is deliberately unauthenticated,
because most storefront traffic is anonymous, so anyone who finds it can post
events into the workspace's GA4 property. That is the same exposure gtag.js
already has — a measurement id is public by construction, and anyone can post to
Google's own collect endpoint with it. What this must not become is an amplifier
for *our* infrastructure, hence the throttle and the caps below; and it must not
let a caller invent arbitrary GA4 schema, hence the event allowlist.
"""

import logging
import re

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from bfg.common.models import Customer
from bfg.core.analytics import MAX_EVENTS_PER_REQUEST, track_many

logger = logging.getLogger(__name__)

# GA4's own recommended events for a shop, plus the two screen/page events. An
# allowlist rather than a blocklist: an unknown name is far more likely to be
# junk than a new event we forgot, and a typo'd name silently creates a new GA4
# dimension that cannot be deleted afterwards.
ALLOWED_EVENTS = frozenset({
    'screen_view',
    'page_view',
    'view_item',
    'view_item_list',
    'select_item',
    'view_cart',
    'add_to_cart',
    'remove_from_cart',
    'begin_checkout',
    'add_shipping_info',
    'add_payment_info',
    'search',
    'view_promotion',
    'select_promotion',
    'share',
    'login',
    'sign_up',
})

# `purchase` is deliberately absent: revenue is reported from `order.paid` on the
# server, where the amount comes from the order record. Accepting it here would
# let anyone post arbitrary revenue into the property, and would double-count
# every real sale.

# GA4's own limits: parameter names are <=40 chars, string values <=100, and 25
# parameters per event. Enforcing them here means a malformed event is rejected
# visibly instead of being silently truncated by Google.
PARAM_NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
MAX_PARAM_VALUE_CHARS = 100
MAX_PARAMS_PER_EVENT = 25
MAX_ITEMS_PER_EVENT = 200
MAX_CLIENT_ID_CHARS = 64


class StorefrontAnalyticsThrottle(AnonRateThrottle):
    """Rate limit unique to this view, so it cannot become a traffic amplifier."""
    scope = 'storefront_analytics'
    THROTTLE_RATES = {'storefront_analytics': '120/min'}

    def get_rate(self):
        # Self-contained rather than relying on a DEFAULT_THROTTLE_RATES entry:
        # the project sets no throttling anywhere else, and a rate that silently
        # resolves to None would disable the limit entirely.
        return self.THROTTLE_RATES[self.scope]


def _clean_value(value):
    """Coerce one parameter value to something GA4 will accept, or None to drop it."""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_PARAM_VALUE_CHARS]
    return None


def _clean_items(raw):
    """`items` is the one nested structure GA4 takes; everything else is scalar."""
    if not isinstance(raw, list):
        return None
    items = []
    for entry in raw[:MAX_ITEMS_PER_EVENT]:
        if not isinstance(entry, dict):
            continue
        item = {}
        for key, value in entry.items():
            if not isinstance(key, str) or not PARAM_NAME_RE.match(key):
                continue
            cleaned = _clean_value(value)
            if cleaned is not None:
                item[key] = cleaned
        if item:
            items.append(item)
    return items or None


def _clean_params(raw):
    if not isinstance(raw, dict):
        return {}
    params = {}
    for key, value in raw.items():
        if len(params) >= MAX_PARAMS_PER_EVENT:
            break
        if not isinstance(key, str) or not PARAM_NAME_RE.match(key):
            continue
        if key == 'items':
            items = _clean_items(value)
            if items:
                params['items'] = items
            continue
        cleaned = _clean_value(value)
        if cleaned is not None:
            params[key] = cleaned
    return params


class StorefrontEventSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=40)
    params = serializers.DictField(required=False, default=dict)

    def validate_name(self, value):
        if value not in ALLOWED_EVENTS:
            raise serializers.ValidationError(f"Unsupported event name '{value}'.")
        return value


class StorefrontAnalyticsSerializer(serializers.Serializer):
    # Generated and persisted by the client, so one device stays one GA4 user
    # across sessions. The server cannot mint it: it has no cookie to put it in.
    client_id = serializers.CharField(max_length=MAX_CLIENT_ID_CHARS)
    events = serializers.ListField(
        child=StorefrontEventSerializer(),
        min_length=1,
        max_length=MAX_EVENTS_PER_REQUEST,
    )


class StorefrontAnalyticsView(APIView):
    """POST /api/v1/store/analytics/collect/ — relay client events to GA4."""

    permission_classes = [AllowAny]
    # Authentication is left at the project default rather than disabled: a signed-in
    # shopper should get a user_id, and anonymous callers still pass AllowAny.
    throttle_classes = [StorefrontAnalyticsThrottle]

    def post(self, request):
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return Response({'detail': 'No workspace available'}, status=status.HTTP_404_NOT_FOUND)

        serializer = StorefrontAnalyticsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        events = [
            {'name': event['name'], 'params': _clean_params(event.get('params'))}
            for event in data['events']
        ]

        # A signed-in shopper gets a user_id so GA4 can stitch their mini-program
        # activity to the same person's web activity; anonymous callers do not,
        # and a caller cannot supply one — it would let anyone attribute traffic
        # to another customer.
        user_id = None
        if request.user and request.user.is_authenticated:
            customer = Customer.objects.filter(workspace=workspace, user=request.user).first()
            if customer:
                # The customer id, not the user id: it is what `order.paid` reports,
                # so a shopper's browsing and their purchases are one GA4 user.
                user_id = customer.id

        track_many(workspace.id, data['client_id'], events, user_id=user_id)

        # 202: the events are queued, and whether Google accepted them is not
        # something the caller can act on. Never make a storefront wait on, or
        # fail because of, analytics.
        return Response(status=status.HTTP_202_ACCEPTED)
