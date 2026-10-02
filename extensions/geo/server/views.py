# -*- coding: utf-8 -*-
"""
Address lookup endpoints, mounted at ``/api/v1/geo/``.

::

    GET  address/config/                        what this workspace has turned on
    GET  address/suggest/?q=&session=           typeahead over real addresses
    GET  address/resolve/?place_id=&session=    a suggestion → form fields
    GET  address/reverse/?lat=&lng=             a GPS fix → form fields

**None of them requires a signed-in caller.** The shopper filling in a delivery
address at checkout has no account — that is most of what these endpoints exist
for — and demanding one would only push the storefront back to calling Google
from the browser, with a key anyone can read out of the page and no way to bill
the workspace for what it spends.

What every call does require is a *workspace*. ``WorkspaceMiddleware`` resolves
one from the request's host or its ``X-Workspace-ID`` header, and a request that
cannot be placed is refused rather than served against some default tenant — see
:func:`_no_workspace_response`.

The cost of opening this up is worth stating plainly: **anyone who knows a shop's
storefront hostname can spend that shop's address-lookup allowance.** Being
signed out is not what makes that possible, and sign-in was never what prevented
it — an account at a storefront is free to open, so a script that wanted this
allowance could always have had one. Two gates bound it instead, and they answer
different questions:

* the **throttles** below bound how fast one caller can spend — per IP for a
  guest, per user for a signed-in shopper, and always within one workspace. They
  stop a crawler and a client that forgot to debounce. They are a speed bump, not
  a security boundary: behind a proxy an IP is whatever the forwarded header
  says, and anyone with a handful of addresses has a handful of buckets;
* the **monthly usage cap** bounds how much can be spent at all. It is per
  workspace, it is the operator's own number, and it is the one that actually
  limits the bill — past it every call is refused with 402, guest and signed-in
  alike.

So the throttle is against abuse and the cap is against a surprise invoice. A
shop unwilling to fund strangers' lookups sets a cap it can afford; a shop that
wants none of this switches the extension off, and all four endpoints go back to
answering 404.

What the workspace is charged for those calls is asked before each one and
recorded after it, never the other way round, so nothing is billed that was not
delivered and nothing is spent that the workspace has no budget left for.
Autocomplete is the exception that shapes the rest: Google prices it by the
session, so its requests are counted rather than metered until the session either
ends in a chosen address or is abandoned — see ``services.billing``.

Every response is shaped the same whether it came from Places or from Geocoding, so
a client fills its form from one code path.
"""

from __future__ import annotations

import logging
import os
import re

from django.conf import settings as django_settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from apps.geo.extension import METER_AUTOCOMPLETE, METER_GEOCODE, METER_PLACE_DETAILS
from apps.geo.services import billing
from apps.geo.services.config import get_address_lookup_config
from apps.geo.services.google_maps import GeoProviderError, resolve, reverse, suggest
from bfg.common.middleware import MISSING_WORKSPACE_RESPONSE
from bfg.platform import metering

logger = logging.getLogger(__name__)

# Latitude/longitude bounds. Anything outside is a bug or a probe, not a place.
LAT_RANGE = (-90.0, 90.0)
LNG_RANGE = (-180.0, 180.0)

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 200

# Place ids are opaque tokens; cap the length so a huge string never reaches a URL.
MAX_PLACE_ID_LENGTH = 512
MAX_SESSION_TOKEN_LENGTH = 64

# ─── Rates ────────────────────────────────────────────────────────────
# Defaults, each overridable under the same name in the deployment's settings or
# its environment (``GEO_GUEST_TYPEAHEAD_RATE=20/min``); see :func:`_rate`.
#
# Sized from what filling in one address actually costs. A client starts asking
# at about the third character and debounces the keystrokes between, so one real
# address — "12 Queen Street, Auckland" — is six to twelve suggest requests, and
# the resolve that ends it is one more. A checkout fills a delivery address and
# sometimes a separate billing address, and a shopper who mistypes starts a field
# over: twenty-five suggests and three or four lookups for an entire fumbling
# checkout, spread over the several minutes it takes to read a form and type.
#
# The guest rates are therefore a whole checkout's worth of typing compressed into
# a single minute — more than any real shopper manages, and far below what would
# make scraping an address database out of this worth anyone's while. The
# signed-in rates are the older, looser ones, unchanged: a signed-in caller is a
# named account that can be dealt with individually, and in the admin it is a
# staff member working through many addresses in a row.
DEFAULT_TYPEAHEAD_RATE = '120/min'
DEFAULT_LOOKUP_RATE = '60/min'
DEFAULT_GUEST_TYPEAHEAD_RATE = '30/min'
DEFAULT_GUEST_LOOKUP_RATE = '10/min'

# What DRF's ``parse_rate`` accepts, checked before it gets there. Stricter than
# DRF itself, which only ever looks at the first letter of the period.
RATE_RE = re.compile(r'^\d+/(s|sec|m|min|h|hour|d|day)$')


def _rate(name: str, default: str) -> str:
    """The rate configured as ``name``, or ``default``.

    Django settings first, so that a deployment declaring the name in its settings
    module wins and a test can reach for ``override_settings``; then the
    environment, because the settings module belongs to the server rather than to
    this extension, and an operator turning a limit down mid-incident has ``.env``
    to hand and little else.

    A value DRF could not parse is ignored rather than raised. ``SimpleRateThrottle``
    parses its rate while being constructed, which happens inside the request, so a
    typo in an environment variable would otherwise turn every address lookup into
    a 500 until somebody noticed. Falling back to the default keeps a limit in
    place — the dangerous way to read a bad rate is "no limit at all" — and says so
    in the log.
    """
    configured = getattr(django_settings, name, None)
    if configured is None:
        configured = os.environ.get(name)
    configured = (configured or '').strip()
    if not configured:
        return default
    if not RATE_RE.match(configured):
        logger.warning(
            '%s is not a rate this can parse (%r); falling back to %s',
            name, configured, default,
        )
        return default
    return configured


class _PerWorkspaceKey:
    """Mixin: one bucket per workspace, not one shared across every shop.

    Without the workspace in the key, every shop on the deployment shares one
    bucket per address, and a busy shop's shoppers become what a quiet shop's
    shopper is refused for. The two have nothing to do with each other and are
    billed separately. That is ordinary rather than hypothetical: a carrier NAT or
    an office gateway is one IP address for thousands of people.
    """

    def get_cache_key(self, request, view):
        key = super().get_cache_key(request, view)
        if key is None:
            return None
        workspace = getattr(request, 'workspace', None)
        return f'{key}:ws{getattr(workspace, "pk", None)}'


class _GuestThrottle(_PerWorkspaceKey, AnonRateThrottle):
    """The limit a caller who is not signed in is held to.

    ``AnonRateThrottle`` keys on the caller's address and steps aside entirely for
    a signed-in one, which is exactly the split wanted here: a guest is counted
    here, a shopper with an account is counted by :class:`_SignedInThrottle`, and
    nobody is counted twice.
    """


class _SignedInThrottle(_PerWorkspaceKey, UserRateThrottle):
    """The looser limit a signed-in caller is held to.

    ``UserRateThrottle`` falls back to the caller's address when nobody is signed
    in, which would count every guest twice — once here at the loose rate and once
    against the strict guest limit, where they belong. Guests are none of this
    class's business, so it stands aside for them.
    """

    def get_cache_key(self, request, view):
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return None
        return super().get_cache_key(request, view)


class TypeaheadThrottle(_SignedInThrottle):
    """A person types; they do not type six times a second.

    Sized for a real user holding down a keyboard rather than for the client's
    debounce, so a client that forgets to debounce degrades instead of running up
    the bill. Rates are resolved here rather than from ``DEFAULT_THROTTLE_RATES``
    because this app has to work in a deployment that never configured one.
    """

    scope = 'geo_typeahead'

    def get_rate(self):
        return _rate('GEO_TYPEAHEAD_RATE', DEFAULT_TYPEAHEAD_RATE)


class GuestTypeaheadThrottle(_GuestThrottle):
    """Typeahead for a caller with no account: tighter, and per address."""

    scope = 'geo_typeahead_guest'

    def get_rate(self):
        return _rate('GEO_GUEST_TYPEAHEAD_RATE', DEFAULT_GUEST_TYPEAHEAD_RATE)


class LookupThrottle(_SignedInThrottle):
    """Resolve and reverse follow a deliberate action, so they are far rarer."""

    scope = 'geo_lookup'

    def get_rate(self):
        return _rate('GEO_LOOKUP_RATE', DEFAULT_LOOKUP_RATE)


class GuestLookupThrottle(_GuestThrottle):
    """Resolve and reverse for a caller with no account.

    The tightest of the four: one of these is a whole address, a shopper needs a
    couple per checkout, and every one of them is billed the moment Google answers.
    """

    scope = 'geo_lookup_guest'

    def get_rate(self):
        return _rate('GEO_GUEST_LOOKUP_RATE', DEFAULT_GUEST_LOOKUP_RATE)


def _workspace(request):
    """The shop this request belongs to, or ``None``.

    Bound by ``WorkspaceMiddleware`` from the request's host or its
    ``X-Workspace-ID`` header. Read with ``getattr`` rather than assumed: a
    request can reach a view with no workspace attribute at all.
    """
    return getattr(request, 'workspace', None)


def _no_workspace_response() -> Response:
    """Refuse a request that belongs to no shop in particular.

    There is deliberately no fallback to a default workspace here. These endpoints
    answer callers who are not signed in, so a fallback would mean anyone who can
    reach the API at all — no hostname needed, no shop in mind — could spend
    whichever tenant that default happened to be.

    The middleware already answers this way for the requests it inspects. The same
    answer is repeated here because it is not asked on every path: a request
    carrying an ``X-API-Key`` header is let through unresolved, with the workspace
    left to the view layer. Its payload is reused rather than reworded so that a
    client has one ``workspace_required`` code to key on instead of two spellings
    of the same refusal.
    """
    return Response(MISSING_WORKSPACE_RESPONSE, status=status.HTTP_400_BAD_REQUEST)


def _disabled_response():
    return Response({'detail': 'address lookup is not enabled for this workspace'}, status=status.HTTP_404_NOT_FOUND)


def _usage_cap_response() -> Response:
    """Refuse a call the workspace has no budget left for this month.

    This is the gate that bounds the bill, as against the throttles, which only
    bound the rate; it applies to every caller, signed in or not.

    402 rather than 429: nothing is being asked too fast, and waiting will not
    help — the workspace has spent what it agreed to spend, and only its operator
    raising the cap changes that. The client keys its "you have reached this
    month's limit" message off ``code``, which is why the code is stable and the
    wording is not.
    """
    return Response(
        {'detail': 'this workspace has used up its address lookups for the month', 'code': 'usage_cap_reached'},
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _budget_refusal(workspace, meter_name: str):
    """``None`` when ``workspace`` may make a ``meter_name`` call, or the refusal to return.

    Abandoned autocomplete sessions are settled on the way past, because no
    environment runs a scheduler to settle them anywhere else. That happens before
    the cap is checked rather than after, so a workspace cannot keep spending
    against points it already owes for lookups it walked away from. Settlement
    never raises — it is bookkeeping, and one shopper's lock timeout must not fail
    another shopper's lookup — so the cap is then read from whatever has been
    recorded by the time it is asked.
    """
    billing.settle_abandoned(workspace)
    if metering.allowed(workspace, meter_name):
        return None
    return _usage_cap_response()


def _provider_error_response(exc: GeoProviderError) -> Response:
    """Map a provider failure onto a status the client can act on.

    A timeout or an unreachable Google is 503 — worth retrying. Anything else is
    502: the request reached Google and came back wrong, and retrying it will not
    help. The provider's own message never crosses this line; it can contain the
    API key.
    """
    retryable = exc.code in ('provider_timeout', 'provider_unreachable')
    return Response(
        {'detail': 'address provider unavailable', 'code': exc.code},
        status=status.HTTP_503_SERVICE_UNAVAILABLE if retryable else status.HTTP_502_BAD_GATEWAY,
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def address_config(request):
    """Tell the client whether to offer the feature at all.

    A client that asks first can hide the map button and the typeahead entirely
    rather than showing controls that answer 404. Never includes the API key, and
    spends nothing at Google, which is why it is the one endpoint here with no
    throttle of its own.
    """
    workspace = _workspace(request)
    if workspace is None:
        return _no_workspace_response()

    config = get_address_lookup_config(workspace)
    return Response({
        'enabled': config.usable,
        'country_code': config.country_code,
        'language': config.language,
        'provider': 'google',
    })


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([TypeaheadThrottle, GuestTypeaheadThrottle])
def address_suggest(request):
    """Addresses in the workspace's country matching ``q``."""
    workspace = _workspace(request)
    if workspace is None:
        return _no_workspace_response()

    config = get_address_lookup_config(workspace)
    if not config.usable:
        return _disabled_response()

    query = (request.query_params.get('q') or '').strip()
    if len(query) < MIN_QUERY_LENGTH:
        # Not an error: the field is simply too empty to search on yet, and a 400
        # on every first character would fill the client's console with noise.
        return Response({'results': []})

    session_token = (request.query_params.get('session') or '').strip()[:MAX_SESSION_TOKEN_LENGTH]

    refusal = _budget_refusal(workspace, METER_AUTOCOMPLETE)
    if refusal is not None:
        return refusal

    try:
        results = suggest(query[:MAX_QUERY_LENGTH], config, session_token)
    except GeoProviderError as exc:
        return _provider_error_response(exc)

    if session_token:
        # Counted, not metered: Google charges for this request only if the session
        # is abandoned, and charges for the details call instead if it is not.
        billing.note_autocomplete(workspace, session_token)
    else:
        # A client that sent no session token gets no session pricing either —
        # Google bills this request on its own and nothing later can make it free,
        # so it is metered here like any other one-off call.
        metering.meter(workspace, METER_AUTOCOMPLETE)

    return Response({'results': [s.as_dict() for s in results]})


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([LookupThrottle, GuestLookupThrottle])
def address_resolve(request):
    """Expand a suggestion into the fields of an address form."""
    workspace = _workspace(request)
    if workspace is None:
        return _no_workspace_response()

    config = get_address_lookup_config(workspace)
    if not config.usable:
        return _disabled_response()

    place_id = (request.query_params.get('place_id') or '').strip()
    if not place_id or len(place_id) > MAX_PLACE_ID_LENGTH:
        return Response({'detail': 'place_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    session_token = (request.query_params.get('session') or '').strip()[:MAX_SESSION_TOKEN_LENGTH]

    refusal = _budget_refusal(workspace, METER_PLACE_DETAILS)
    if refusal is not None:
        return refusal

    try:
        resolved = resolve(place_id, config, session_token)
    except GeoProviderError as exc:
        return _provider_error_response(exc)

    # Metered whatever the place turns out to be: Google charged for the details
    # call the moment it answered, and refusing the address because it sits over a
    # border does not get that back.
    metering.meter(workspace, METER_PLACE_DETAILS)
    # This one call is what the whole session cost, so the autocomplete requests
    # counted against the token are dropped without ever being billed.
    billing.close_session(workspace, session_token)

    if resolved is None:
        return Response(
            {'detail': 'no address in this workspace\'s country for that place'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(resolved.as_dict())


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([LookupThrottle, GuestLookupThrottle])
def address_reverse(request):
    """Name the address a GPS fix landed on."""
    workspace = _workspace(request)
    if workspace is None:
        return _no_workspace_response()

    config = get_address_lookup_config(workspace)
    if not config.usable:
        return _disabled_response()

    latitude = _coordinate(request.query_params.get('lat'), LAT_RANGE)
    longitude = _coordinate(request.query_params.get('lng'), LNG_RANGE)
    if latitude is None or longitude is None:
        return Response(
            {'detail': 'lat and lng are required and must be valid coordinates'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    refusal = _budget_refusal(workspace, METER_GEOCODE)
    if refusal is not None:
        return refusal

    try:
        resolved = reverse(latitude, longitude, config)
    except GeoProviderError as exc:
        return _provider_error_response(exc)

    # A geocode has no session to belong to, so it is metered as soon as it
    # answers — including when it answers with nothing, which Google charges for
    # just the same.
    metering.meter(workspace, METER_GEOCODE)

    if resolved is None:
        # Out of market or genuinely nowhere. Either way the shopper keeps typing,
        # so this is a 404 with an empty hand rather than an error.
        return Response(
            {'detail': 'no address in this workspace\'s country at that location'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(resolved.as_dict())


def _coordinate(raw, bounds):
    """A finite coordinate inside ``bounds``, or ``None``.

    ``float()`` accepts ``nan`` and ``inf``, which would sail through a naive range
    check (every comparison against NaN is False) and reach Google as garbage.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    low, high = bounds
    return value if low <= value <= high else None
