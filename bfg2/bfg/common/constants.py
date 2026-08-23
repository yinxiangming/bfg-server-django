# -*- coding: utf-8 -*-
"""
Shared constants for default currency, country and symbols.
Use the workspace Settings value when available; fall back to these in code.
"""

from django.core.exceptions import ObjectDoesNotExist

# Code default when no workspace Settings or default_currency is set
DEFAULT_CURRENCY_CODE = 'USD'

# Code default when no workspace Settings or country is set.
#
# Deliberately empty. Unlike currency there is no neutral country to fall back on: this
# platform is multi-tenant and each workspace ships from its own market, so a guess here
# is not a safe default but a wrong address. Call sites used to hardcode the country the
# first tenant happened to sell in, which quoted every under-configured workspace's
# freight from the wrong hemisphere without ever failing. An empty country surfaces as a
# carrier rejecting the request, which is the honest outcome — the workspace has not said
# where it ships from.
DEFAULT_COUNTRY_CODE = ''

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


def get_default_country_for_workspace(workspace):
    """
    Return the default country code (ISO 3166-1 alpha-2) for a workspace.
    Uses Settings.country when present, otherwise DEFAULT_COUNTRY_CODE.
    """
    if workspace is None:
        return DEFAULT_COUNTRY_CODE
    try:
        workspace_settings = workspace.workspace_settings
    except (ObjectDoesNotExist, AttributeError):
        return DEFAULT_COUNTRY_CODE
    return getattr(workspace_settings, 'country', '') or DEFAULT_COUNTRY_CODE
