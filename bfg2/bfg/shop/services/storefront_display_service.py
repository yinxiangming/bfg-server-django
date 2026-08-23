# -*- coding: utf-8 -*-
"""
Workspace-level storefront display policy.

Three questions a shop answers once, in settings, and every product page obeys:

* how much of the internal SKU a visitor is allowed to see,
* how much of the stock level a visitor is allowed to see,
* what happens to a product that has run out.

All three are presentation and commercial policy, not product data, so they live on
the workspace (``Settings.custom_settings['shop']['storefront_display']``) rather than
on each product. Resolution happens on the server so that every theme, every skin and
every future client answer them identically — a stock figure the shop chose to hide
must not be one API field away from being scraped.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# How much of the stored SKU reaches the storefront.
#   hidden — no SKU line at all.
#   plain  — the SKU with the workspace's configured `sku_prefix` removed. The prefix is
#            an internal grouping token ("SKU-", "ACME-"); customers quoting a code back
#            to support do not need it, and it makes every code on the page look alike.
#   full   — the SKU exactly as stored.
SKU_DISPLAY_CHOICES = ('hidden', 'plain', 'full')
SKU_DISPLAY_DEFAULT = 'plain'

# How much of the stock level reaches the storefront.
#   hidden   — nothing, not even in/out of stock.
#   status   — "In stock" / "Out of stock" and nothing more.
#   low_only — a figure only once it drops to the product's low-stock threshold
#              ("Only 3 left"); plain "In stock" above it.
#   exact    — the running count.
# Anything other than `exact` also withholds the number from the API payload: an exact
# stock level is competitive intelligence, and hiding it in the template alone would
# leave it in plain sight one request away.
STOCK_DISPLAY_CHOICES = ('hidden', 'status', 'low_only', 'exact')
STOCK_DISPLAY_DEFAULT = 'status'

# What a sold-out product does.
#   hide      — drop out of listings and 404 on the detail page.
#   show      — stay visible, marked sold out, cannot be bought.
#   notify    — stay visible, cannot be bought, but a visitor can leave an email to be
#               told when it returns.
#   backorder — stay visible and remain buyable; the order is accepted against stock the
#               shop does not yet hold.
OUT_OF_STOCK_POLICY_CHOICES = ('hide', 'show', 'notify', 'backorder')
OUT_OF_STOCK_POLICY_DEFAULT = 'show'

SETTINGS_PATH = ('shop', 'storefront_display')

DEFAULTS: Dict[str, str] = {
    'sku_display': SKU_DISPLAY_DEFAULT,
    'stock_display': STOCK_DISPLAY_DEFAULT,
    'out_of_stock_policy': OUT_OF_STOCK_POLICY_DEFAULT,
}

_CHOICES: Dict[str, tuple] = {
    'sku_display': SKU_DISPLAY_CHOICES,
    'stock_display': STOCK_DISPLAY_CHOICES,
    'out_of_stock_policy': OUT_OF_STOCK_POLICY_CHOICES,
}


def _custom_settings(workspace) -> Dict[str, Any]:
    ws_settings = getattr(workspace, 'workspace_settings', None)
    custom = getattr(ws_settings, 'custom_settings', None)
    return custom if isinstance(custom, dict) else {}


def get_storefront_display_settings(workspace) -> Dict[str, str]:
    """
    Resolve the workspace's storefront display policy, filling in defaults.

    Unrecognised values fall back to the default rather than propagating: these arrive
    from a JSON blob that predates the setting and can hold anything, and a typo must
    not decide whether a product is purchasable.
    """
    resolved = dict(DEFAULTS)
    if workspace is None:
        return resolved

    node: Any = _custom_settings(workspace)
    for key in SETTINGS_PATH:
        if not isinstance(node, dict):
            return resolved
        node = node.get(key, {})
    if not isinstance(node, dict):
        return resolved

    for key, choices in _CHOICES.items():
        value = node.get(key)
        if isinstance(value, str) and value in choices:
            resolved[key] = value
    return resolved


def strip_sku_prefix(sku: Optional[str], prefix: Optional[str]) -> str:
    """
    Remove the workspace's SKU prefix from a code for display.

    Only a leading, case-insensitive match is removed, and never the whole code: a SKU
    that is nothing but its prefix stays as-is, because an empty reference is worse than
    a redundant one.
    """
    code = (sku or '').strip()
    token = (prefix or '').strip()
    if not code or not token:
        return code
    if len(code) > len(token) and code[:len(token)].upper() == token.upper():
        return code[len(token):]
    return code


def product_stock_level(product) -> Optional[int]:
    """
    Units of ``product`` a visitor could buy right now, or ``None`` when untracked.

    Deliberately mirrors ``CartService.add_to_cart``: the same raw ``stock_quantity``
    figures, with no reservation arithmetic. The badge on the page and the check that
    refuses the add-to-cart have to agree, and the cheapest way to guarantee that is to
    read the same numbers.

    Reads ``variants`` through the prefetch the storefront viewset already sets up, so
    filtering happens in Python rather than as a query per product.
    """
    if not getattr(product, 'track_inventory', True):
        return None

    active_variants = [v for v in product.variants.all() if v.is_active]
    if active_variants:
        return sum(max(0, v.stock_quantity or 0) for v in active_variants)
    return max(0, product.stock_quantity or 0)


def resolve_product_stock(product, display_settings: Dict[str, str]) -> Dict[str, Any]:
    """
    Turn a product's stock level into what the storefront is allowed to know about it.

    Returns ``in_stock``, ``low_stock``, ``purchasable`` and ``stock_quantity`` — the
    last being ``None`` whenever the policy withholds the figure.
    """
    level = product_stock_level(product)
    untracked = level is None
    in_stock = untracked or level > 0

    policy = display_settings.get('out_of_stock_policy', OUT_OF_STOCK_POLICY_DEFAULT)
    purchasable = in_stock or policy == 'backorder'

    threshold = getattr(product, 'low_stock_threshold', 0) or 0
    low_stock = (not untracked) and 0 < level <= threshold

    stock_display = display_settings.get('stock_display', STOCK_DISPLAY_DEFAULT)
    if untracked:
        # Nothing to disclose — the shop is not counting these.
        quantity = None
    elif stock_display == 'exact':
        quantity = level
    elif stock_display == 'low_only' and low_stock:
        quantity = level
    else:
        quantity = None

    return {
        'in_stock': in_stock,
        'low_stock': low_stock,
        'purchasable': purchasable,
        'stock_quantity': quantity,
    }
