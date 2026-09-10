# -*- coding: utf-8 -*-
"""
Turn a (country, industry) pick into the concrete rows a workspace needs.

The output is a plain dict — a *plan*. Nothing here touches the database, which
is what lets ``POST /onboarding/preview/`` show the user exactly what
``POST /onboarding/apply/`` will do.
"""

import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from .catalog import (
    DEFAULT_COUNTRY,
    DEFAULT_INDUSTRY,
    SUPPORTED_LANGUAGES,
    get_country_profile,
    get_currency_profile,
    get_industry,
)

DATA_DIR = Path(__file__).resolve().parent / 'data'

#: What a placeholder renders as when the workspace has not supplied the real
#: value yet. Deliberately conspicuous: a shopper-visible "[email address]" gets
#: noticed and fixed, whereas a plausible-looking fake address does not.
MISSING_MARKERS = {
    'en': {
        'contact_email': '[email address]',
        'contact_phone': '[phone number]',
        'address': '[postal address]',
    },
    'zh-hans': {
        'contact_email': '[邮箱地址]',
        'contact_phone': '[联系电话]',
        'address': '[通信地址]',
    },
}

_PLACEHOLDER_RE = re.compile(r'\{\{\s*([a-z_]+)\s*\}\}')


@lru_cache(maxsize=None)
def _load(path: str) -> Dict[str, Any]:
    with open(DATA_DIR / path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _render(text: str, context: Dict[str, str]) -> str:
    """Substitute ``{{ name }}``; an unknown name is left alone rather than blanked.

    Leaving it visible means a typo in a template shows up in review instead of
    silently deleting a sentence's subject.
    """
    return _PLACEHOLDER_RE.sub(lambda m: context.get(m.group(1), m.group(0)), text)


def build_context(
    *,
    site_name: str,
    country_code: str,
    currency: str,
    language: str,
    contact_email: str = '',
    contact_phone: str = '',
    address: str = '',
    year: Optional[int] = None,
) -> Dict[str, str]:
    """Placeholder values for one language's copy."""
    profile = get_country_profile(country_code) or get_country_profile(DEFAULT_COUNTRY)
    markers = MISSING_MARKERS.get(language, MISSING_MARKERS['en'])
    tax = profile['tax']
    return {
        'site_name': site_name or 'this shop',
        'contact_email': contact_email or markers['contact_email'],
        'contact_phone': contact_phone or markers['contact_phone'],
        'address': address or markers['address'],
        'country_name': profile['name'],
        'country_name_zh': profile['name_zh'],
        'jurisdiction': profile['jurisdiction'],
        'currency': currency or profile['currency'],
        'tax_name': tax['name'],
        'tax_rate': str(tax['rate']),
        'year': str(year) if year else '',
    }


def _localised(item: Dict[str, Any], field: str, language: str) -> str:
    """``name`` for en, ``name_zh`` for zh-hans, falling back to the base field."""
    if language == 'zh-hans':
        return item.get(f'{field}_zh') or item.get(field, '')
    return item.get(field, '')


def resolve_industry_data(industry_key: str) -> Dict[str, Any]:
    industry = get_industry(industry_key) or get_industry(DEFAULT_INDUSTRY)
    try:
        return deepcopy(_load(f'industry/{industry["key"]}.json'))
    except FileNotFoundError:
        return deepcopy(_load(f'industry/{DEFAULT_INDUSTRY}.json'))


def build_plan(
    *,
    country_code: str,
    industry_key: str,
    site_name: str,
    languages: Optional[List[str]] = None,
    default_language: str = '',
    currency: str = '',
    timezone: str = '',
    contact_email: str = '',
    contact_phone: str = '',
    address: str = '',
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """The full set of rows a (country, industry) pick implies, fully rendered.

    ``languages`` is intersected with what the client ships translations for:
    a Site advertising a language the storefront cannot render returns an empty
    catalogue rather than an error.
    """
    profile = get_country_profile(country_code) or get_country_profile(DEFAULT_COUNTRY)
    country_code = (country_code or DEFAULT_COUNTRY).strip().upper()[:2]
    industry = get_industry(industry_key) or get_industry(DEFAULT_INDUSTRY)
    industry_data = resolve_industry_data(industry['key'])

    default_language = (default_language or profile['default_language']).strip()
    if default_language not in SUPPORTED_LANGUAGES:
        default_language = 'en'
    resolved_languages = [
        lang for lang in (languages or profile['languages']) if lang in SUPPORTED_LANGUAGES
    ]
    if default_language not in resolved_languages:
        resolved_languages.insert(0, default_language)

    currency = (currency or profile['currency']).strip().upper()[:3]
    timezone = timezone or profile['timezone']

    base = deepcopy(_load('base.json'))
    pages_drop = set(industry_data.get('pages_drop') or [])

    shop_settings = {
        **(base.get('shop_settings') or {}),
        **(industry_data.get('shop_settings') or {}),
    }

    categories: List[Dict[str, Any]] = []
    pages: List[Dict[str, Any]] = []
    menus: List[Dict[str, Any]] = []

    for language in resolved_languages:
        context = build_context(
            site_name=site_name,
            country_code=country_code,
            currency=currency,
            language=language,
            contact_email=contact_email,
            contact_phone=contact_phone,
            address=address,
            year=year,
        )

        # Categories are stored per language (unique on workspace+slug+language)
        # and the storefront filters by the Site's language, so a shop offering
        # two languages needs both rows or half its catalogue disappears.
        for item in industry_data.get('categories', []):
            categories.append({
                'slug': item['slug'],
                'name': _localised(item, 'name', language),
                'language': language,
                'order': item.get('order', 100),
                'icon': item.get('icon', ''),
                'description': _localised(item, 'description', language),
            })

        for item in base.get('pages', []):
            if item['slug'] in pages_drop:
                continue
            pages.append({
                'slug': item['slug'],
                'language': language,
                'status': 'published',
                'order': item.get('order', 100),
                'title': _render(_localised(item, 'title', language), context),
                'meta_title': _render(_localised(item, 'meta_title', language), context),
                'meta_description': _render(_localised(item, 'meta_description', language), context),
                # _upsert_page turns content/content_zh into one text_block_v1
                # holding both languages, so each row carries the pair.
                'content': _render(item.get('content', ''), context),
                'content_zh': _render(
                    item.get('content_zh') or item.get('content', ''),
                    build_context(
                        site_name=site_name, country_code=country_code, currency=currency,
                        language='zh-hans', contact_email=contact_email,
                        contact_phone=contact_phone, address=address, year=year,
                    ),
                ),
            })

        for item in base.get('menus', []):
            menu_items = [
                {
                    'title': _localised(entry, 'title', language),
                    'order': entry.get('order', 100),
                    **({'page_slug': entry['page_slug']} if entry.get('page_slug') else {}),
                    **({'url': entry['url']} if entry.get('url') else {}),
                }
                for entry in item.get('items', [])
                if entry.get('page_slug') not in pages_drop
            ]
            menus.append({
                'slug': item['slug'],
                'name': _localised(item, 'name', language),
                'location': item.get('location', 'header'),
                'language': language,
                'items': menu_items,
            })

    delivery = base.get('delivery') or {}
    plan = {
        'country': {'code': country_code, 'name': profile['name'], 'name_zh': profile['name_zh']},
        'industry': {'key': industry['key'], 'name': industry['name'], 'name_zh': industry['name_zh']},
        'settings': {
            'country': country_code,
            'default_currency': currency,
            'default_language': default_language,
            'supported_languages': resolved_languages,
            'default_timezone': timezone,
            'site_name': site_name,
            # Persisted, not just interpolated: these are real Settings fields,
            # and the generated privacy/terms/returns pages quote them. Rendering
            # someone's address into a published page while leaving
            # Settings.contact_email empty left the checklist red right after
            # they had supplied it.
            'contact_email': contact_email,
            'contact_phone': contact_phone,
        },
        'currency': get_currency_profile(currency),
        'tax': {
            'name': profile['tax']['name'],
            'rate': profile['tax']['rate'],
            'country': country_code,
            'note': profile['tax']['note'],
            'note_zh': profile['tax']['note_zh'],
        },
        'shop_settings': shop_settings,
        'store': {'name': site_name or 'Main', 'code': 'main'},
        'delivery': {
            'zone_code': delivery.get('zone_code', 'domestic'),
            'zone_name': _localised(delivery, 'zone_name', default_language) or 'Domestic',
            'zone_countries': [country_code],
            'warehouse_code': delivery.get('warehouse_code', 'main'),
            'warehouse_name': _localised(delivery, 'warehouse_name', default_language) or 'Main warehouse',
        },
        'categories': categories,
        'pages': pages,
        'menus': menus,
        'checklist_skip': industry_data.get('checklist_skip') or [],
    }
    return _apply_fragments(plan, country_code, industry['key'], resolved_languages)


def _apply_fragments(plan, country_code, industry_key, languages):
    """Fold in what the installed apps contribute to this pick.

    Lists append and are de-duplicated on the key the storage layer is unique
    on — an app adding a ``womens`` category to a fashion template must not
    create a second row that ``update_or_create`` would then fight over.
    Scalars and dicts override, because a contributing app is more specific
    than the library default.
    """
    from .extensions import template_fragments

    fragments = template_fragments(country_code, industry_key, plan)
    if not fragments:
        return plan

    dedupe_keys = {
        'categories': ('slug', 'language'),
        'pages': ('slug', 'language'),
        'menus': ('slug', 'language'),
    }
    for fragment in fragments:
        for key, value in fragment.items():
            if key in dedupe_keys and isinstance(value, list):
                seen = {tuple(row.get(field) for field in dedupe_keys[key]) for row in plan[key]}
                plan[key] = plan[key] + [
                    row for row in value
                    # An app may emit every language it knows; keep only the
                    # ones this workspace actually renders.
                    if row.get('language') in languages
                    and tuple(row.get(field) for field in dedupe_keys[key]) not in seen
                ]
            elif key == 'checklist_skip' and isinstance(value, list):
                plan[key] = sorted(set(plan[key]) | set(value))
            elif key == 'shop_settings' and isinstance(value, dict):
                plan[key] = {**plan[key], **value}
            elif key in plan:
                plan[key] = value
    return plan
