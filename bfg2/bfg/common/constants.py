# -*- coding: utf-8 -*-
"""
Shared constants for default currency and symbols.
Use workspace Settings.default_currency when available; fall back to these in code.
"""

# Code default when no workspace Settings or default_currency is set
DEFAULT_CURRENCY_CODE = 'USD'

# Symbol for display (code -> symbol)
CURRENCY_SYMBOLS = {
    'USD': 'US$',
    'NZD': 'NZ$',
    'CNY': '¥',
    'EUR': '€',
    'GBP': '£',
    'JPY': '¥',
}

# Display name for currency (code -> name), used when creating Currency if missing
CURRENCY_NAMES = {
    'USD': 'US Dollar',
    'NZD': 'New Zealand Dollar',
    'CNY': 'Chinese Yuan',
    'EUR': 'Euro',
    'GBP': 'British Pound',
    'JPY': 'Japanese Yen',
}


def get_default_currency_for_workspace(workspace):
    """
    Return the default currency code for a workspace.
    Uses Settings.default_currency when present, otherwise DEFAULT_CURRENCY_CODE.
    """
    if workspace is None:
        return DEFAULT_CURRENCY_CODE
    try:
        settings = getattr(workspace, 'workspace_settings', None)
        if settings and getattr(settings, 'default_currency', None):
            return settings.default_currency
    except Exception:
        pass
    return DEFAULT_CURRENCY_CODE
