"""Versioned global reference catalogs for reusable form options."""
import json
from functools import lru_cache
from importlib.resources import files
from zoneinfo import available_timezones

from bfg.common.constants import CURRENCY_SYMBOLS


@lru_cache(maxsize=1)
def currency_catalog():
    source = files('bfg.common').joinpath('data/iso4217-current.json')
    return json.loads(source.read_text(encoding='utf-8'))


def currency_profile(code):
    """Return a fresh profile so callers cannot mutate the reference cache."""
    code = str(code).strip().upper()
    item = next((item for item in currency_catalog()['currencies'] if item['code'] == code), None)
    if item is None:
        return None
    return {**item, 'symbol': CURRENCY_SYMBOLS.get(code, code)}


@lru_cache(maxsize=1)
def timezone_codes():
    return tuple(sorted(available_timezones() - {'localtime', 'Factory', 'posixrules'}))


def timezone_options():
    return [{'value': code, 'label': code.replace('_', ' ')} for code in timezone_codes()]


def currency_options():
    """Merge configured values without persisting or replacing currency rows."""
    from bfg.finance.models import Currency

    entries = {item['code']: {**item, 'symbol': CURRENCY_SYMBOLS.get(item['code'], item['code']),
                             'is_active': True, 'id': None}
               for item in currency_catalog()['currencies']}
    configured = Currency.objects.values('id', 'code', 'name', 'symbol', 'decimal_places', 'is_active')
    for item in configured:
        entries[item['code']] = {**entries.get(item['code'], {'numeric_code': ''}), **item}
    return [
        {**item, 'value': code, 'label': f"{code} — {item['name']}",
         'disabled': not item['is_active'] or item['decimal_places'] is None}
        for code, item in sorted(entries.items())
    ]
