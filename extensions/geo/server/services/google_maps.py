# -*- coding: utf-8 -*-
"""
The Google half of address lookup.

Three calls, wrapped so the rest of the app never sees Google's shapes:

* :func:`suggest` — what a shopper is typing becomes a short list of real
  addresses (Places Autocomplete).
* :func:`resolve` — one of those choices becomes filled-in form fields
  (Place Details). Autocomplete returns ids and display text only, so the
  structured fields are necessarily a second call.
* :func:`reverse` — a GPS fix becomes an address a person recognises
  (Geocoding).

Why this runs on the server at all: the mini-program cannot load Google's
JavaScript SDK the way the web storefront does, and a key shipped inside a
mini-program bundle is a key anyone can extract and spend. The key stays here,
and the client sees only addresses.

Country restriction is applied twice, on purpose. Autocomplete takes
``includedRegionCodes`` and honours it. Reverse geocoding has no equivalent —
``components=country:`` is silently ignored on a ``latlng`` request — so results
are filtered here against the country component instead. A shopper standing
across a border gets nothing rather than an out-of-market address that would
fail at checkout.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import requests
from django.core.cache import cache

from apps.geo.services.config import AddressLookupConfig

logger = logging.getLogger(__name__)

AUTOCOMPLETE_URL = 'https://places.googleapis.com/v1/places:autocomplete'
PLACE_DETAILS_URL = 'https://places.googleapis.com/v1/places/{place_id}'
GEOCODE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'

# Google is a dependency of a keystroke here. A slow answer is worse than no
# answer: the shopper has already typed the next character.
TIMEOUT_SECONDS = 6

# Only the fields we actually map. The Places API bills by field mask, so asking
# for everything would cost more for data we throw away.
PLACE_DETAILS_FIELD_MASK = 'id,formattedAddress,addressComponents,location,displayName'

# A place's address does not change; a coordinate's does not either, beyond the
# precision we round to. Cache both — a shopper editing one address reverse-geocodes
# the same spot several times over. The details call that ends an autocomplete
# session is the exception and always goes to Google; see ``resolve``.
RESOLVE_CACHE_SECONDS = 7 * 24 * 3600
REVERSE_CACHE_SECONDS = 24 * 3600

# ~1 metre. Finer than this and the cache never hits, because a phone's GPS jitters
# in the last decimal places while standing still.
REVERSE_CACHE_PRECISION = 5

MAX_SUGGESTIONS = 8


class GeoProviderError(Exception):
    """Google could not be reached, or refused the request.

    Carries a stable ``code`` so the view can answer without leaking Google's
    wording (which can quote the API key back) to the client.
    """

    def __init__(self, code: str, detail: str = ''):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Suggestion:
    """One row in the typeahead."""

    place_id: str
    description: str
    main_text: str
    secondary_text: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedAddress:
    """An address broken into the fields an address form actually has.

    ``display_name`` is the human label — what the mini-program shows once a
    shopper has picked a point on the map. ``formatted_address`` is Google's own
    one-line rendering, kept because it reads better than anything reassembled
    from parts.
    """

    place_id: str
    display_name: str
    formatted_address: str
    address_line1: str
    address_line2: str
    district: str
    city: str
    state: str
    postal_code: str
    country: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _Component:
    """One address component, normalised across Google's two spellings."""

    long_text: str
    short_text: str
    types: Sequence[str] = field(default_factory=tuple)


def _components_from_places(raw: Any) -> List[_Component]:
    """Places API (New): ``longText`` / ``shortText`` / ``types``."""
    if not isinstance(raw, list):
        return []
    return [
        _Component(
            long_text=(c.get('longText') or '').strip(),
            short_text=(c.get('shortText') or '').strip(),
            types=tuple(c.get('types') or ()),
        )
        for c in raw
        if isinstance(c, dict)
    ]


def _components_from_geocoding(raw: Any) -> List[_Component]:
    """Geocoding API: ``long_name`` / ``short_name`` / ``types``."""
    if not isinstance(raw, list):
        return []
    return [
        _Component(
            long_text=(c.get('long_name') or '').strip(),
            short_text=(c.get('short_name') or '').strip(),
            types=tuple(c.get('types') or ()),
        )
        for c in raw
        if isinstance(c, dict)
    ]


def _country_of(components: Sequence[_Component]) -> str:
    for c in components:
        if 'country' in c.types:
            return (c.short_text or c.long_text).upper()
    return ''


def _parse_components(components: Sequence[_Component]) -> Dict[str, str]:
    """
    Map Google's components onto the fields on an address form.

    Two mappings are worth spelling out because the obvious reading is wrong:

    * ``sublocality`` is the *suburb*, not the city. In New Zealand, Google returns
      "Grey Lynn" as a sublocality and "Auckland" as the locality; folding the
      former into ``city`` produces addresses that look right and post wrong.
    * ``subpremise`` (the flat or unit number) leads the street line rather than
      trailing it — "3/12 Queen Street", the order a courier expects.
    """
    parts: Dict[str, str] = {
        'address_line1': '',
        'address_line2': '',
        'district': '',
        'city': '',
        'state': '',
        'postal_code': '',
        'country': '',
    }

    subpremise = ''
    street_number = ''
    route = ''

    for c in components:
        types = c.types
        if 'subpremise' in types:
            subpremise = subpremise or c.long_text
        elif 'street_number' in types:
            street_number = street_number or c.long_text
        elif 'route' in types:
            route = route or c.long_text
        elif 'postal_code' in types:
            parts['postal_code'] = parts['postal_code'] or c.long_text
        elif 'country' in types:
            parts['country'] = parts['country'] or (c.short_text or c.long_text).upper()
        elif 'administrative_area_level_1' in types:
            parts['state'] = parts['state'] or (c.short_text or c.long_text)
        elif 'locality' in types or 'postal_town' in types:
            parts['city'] = parts['city'] or c.long_text
        elif any(t in types for t in ('sublocality', 'sublocality_level_1', 'neighborhood')):
            parts['district'] = parts['district'] or c.long_text

    # A shop in a mall, or a rural address, can come back with no locality at all.
    # Promoting the suburb keeps the city field from being blank on an address the
    # shopper is about to be asked to confirm.
    if not parts['city'] and parts['district']:
        parts['city'] = parts['district']
        parts['district'] = ''

    street = ' '.join(p for p in (street_number, route) if p)
    parts['address_line1'] = f'{subpremise}/{street}' if subpremise and street else (street or subpremise)
    return parts


def _request(method: str, url: str, *, headers=None, params=None, json=None) -> Dict[str, Any]:
    """One HTTP call to Google, with its failure modes collapsed into one exception."""
    try:
        response = requests.request(
            method, url, headers=headers, params=params, json=json, timeout=TIMEOUT_SECONDS
        )
    except requests.Timeout as exc:
        raise GeoProviderError('provider_timeout', str(exc)) from exc
    except requests.RequestException as exc:
        raise GeoProviderError('provider_unreachable', str(exc)) from exc

    if response.status_code >= 400:
        # Logged, not returned: Google's error bodies quote the rejected key back.
        logger.warning('google maps %s %s -> %s', method, url, response.status_code)
        raise GeoProviderError('provider_error', f'HTTP {response.status_code}')

    try:
        payload = response.json()
    except ValueError as exc:
        raise GeoProviderError('provider_error', 'non-JSON response') from exc

    return payload if isinstance(payload, dict) else {}


def suggest(query: str, config: AddressLookupConfig, session_token: str = '') -> List[Suggestion]:
    """Addresses in the workspace's country that match what has been typed so far."""
    payload: Dict[str, Any] = {
        'input': query,
        # CLDR region codes are lower-case in this API even though ISO 3166-1 is upper.
        'includedRegionCodes': [config.country_code.lower()],
        'languageCode': config.language,
        'regionCode': config.country_code.lower(),
    }
    if session_token:
        # Ties the keystrokes and the follow-up details call into one billed session
        # instead of one charge per character.
        payload['sessionToken'] = session_token

    data = _request(
        'POST',
        AUTOCOMPLETE_URL,
        headers={'X-Goog-Api-Key': config.api_key, 'Content-Type': 'application/json'},
        json=payload,
    )

    out: List[Suggestion] = []
    for item in data.get('suggestions') or []:
        prediction = (item or {}).get('placePrediction') or {}
        place_id = (prediction.get('placeId') or '').strip()
        if not place_id:
            continue
        structured = prediction.get('structuredFormat') or {}
        out.append(
            Suggestion(
                place_id=place_id,
                description=((prediction.get('text') or {}).get('text') or '').strip(),
                main_text=((structured.get('mainText') or {}).get('text') or '').strip(),
                secondary_text=((structured.get('secondaryText') or {}).get('text') or '').strip(),
            )
        )
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


def resolve(place_id: str, config: AddressLookupConfig, session_token: str = '') -> Optional[ResolvedAddress]:
    """Turn a suggestion the shopper picked into filled-in address fields.

    Returns ``None`` when the place turns out to sit outside the workspace's
    country. Autocomplete already restricted the list, so this only fires on a
    hand-crafted place id — but it is the same check either way.

    **A lookup carrying a session token never comes from the cache.** That call is
    what ends the session at Google, and a session that is never ended is priced as
    an abandoned one: Google charges for each of its autocomplete requests instead
    of for these details. Serving it from here would save one request and turn a
    whole session's keystrokes into a bill nobody asked for — and the cache is
    keyed on place and language, so the hit would come from whatever another
    workspace happened to look up. The answer is still written to the cache for the
    callers that have no session to end.
    """
    cache_key = f'geo:place:{config.language}:{place_id}'
    cached = cache.get(cache_key) if not session_token else None
    if cached is not None:
        resolved = ResolvedAddress(**cached)
        return resolved if resolved.country == config.country_code else None

    params = {'languageCode': config.language, 'regionCode': config.country_code.lower()}
    if session_token:
        params['sessionToken'] = session_token

    data = _request(
        'GET',
        PLACE_DETAILS_URL.format(place_id=place_id),
        headers={'X-Goog-Api-Key': config.api_key, 'X-Goog-FieldMask': PLACE_DETAILS_FIELD_MASK},
        params=params,
    )

    components = _components_from_places(data.get('addressComponents'))
    if not components:
        return None

    location = data.get('location') or {}
    formatted = (data.get('formattedAddress') or '').strip()
    display = ((data.get('displayName') or {}).get('text') or '').strip()

    resolved = ResolvedAddress(
        place_id=(data.get('id') or place_id).strip(),
        display_name=display or formatted,
        formatted_address=formatted,
        latitude=_as_float(location.get('latitude')),
        longitude=_as_float(location.get('longitude')),
        **_parse_components(components),
    )

    cache.set(cache_key, resolved.as_dict(), RESOLVE_CACHE_SECONDS)
    return resolved if resolved.country == config.country_code else None


def reverse(latitude: float, longitude: float, config: AddressLookupConfig) -> Optional[ResolvedAddress]:
    """Name the place a GPS fix landed on, or ``None`` if it is out of market."""
    lat = round(latitude, REVERSE_CACHE_PRECISION)
    lng = round(longitude, REVERSE_CACHE_PRECISION)
    cache_key = f'geo:reverse:{config.language}:{lat},{lng}'

    cached = cache.get(cache_key)
    if cached is not None:
        resolved = ResolvedAddress(**cached)
        return resolved if resolved.country == config.country_code else None

    data = _request(
        'GET',
        GEOCODE_URL,
        params={
            'latlng': f'{lat},{lng}',
            'key': config.api_key,
            'language': config.language,
            'region': config.country_code.lower(),
        },
    )

    status = data.get('status')
    if status == 'ZERO_RESULTS':
        return None
    if status != 'OK':
        logger.warning('google geocode reverse status=%s', status)
        raise GeoProviderError('provider_error', str(status))

    results = data.get('results') or []
    chosen = _best_reverse_result(results, config.country_code)
    if chosen is None:
        return None

    components = _components_from_geocoding(chosen.get('address_components'))
    location = ((chosen.get('geometry') or {}).get('location')) or {}
    formatted = (chosen.get('formatted_address') or '').strip()
    parts = _parse_components(components)

    resolved = ResolvedAddress(
        place_id=(chosen.get('place_id') or '').strip(),
        # A reverse geocode has no name of its own, so the street line is the label —
        # "12 Queen Street" reads better on a confirm screen than the full postal string.
        display_name=parts['address_line1'] or formatted,
        formatted_address=formatted,
        latitude=_as_float(location.get('lat'), default=lat),
        longitude=_as_float(location.get('lng'), default=lng),
        **parts,
    )

    cache.set(cache_key, resolved.as_dict(), REVERSE_CACHE_SECONDS)
    return resolved


def _best_reverse_result(results: Sequence[Dict[str, Any]], country_code: str) -> Optional[Dict[str, Any]]:
    """
    The most specific in-country result.

    Google returns a ladder from street address up to country, most precise first.
    Walking it in order and taking the first in-country entry gives the finest
    address that is actually in the workspace's market; a fix just over a border
    yields nothing at all.
    """
    for result in results:
        if not isinstance(result, dict):
            continue
        components = _components_from_geocoding(result.get('address_components'))
        if _country_of(components) == country_code:
            return result
    return None


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
