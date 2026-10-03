# -*- coding: utf-8 -*-
"""
What this app adds to the workspace setup wizard.

There is no settings patch here on purpose. ``get_address_lookup_config`` already
falls back to ``Settings.country`` when the plugin block names no market, and the
wizard sets that field — writing a second copy of the country into
``plugins.address_lookup`` would just create two values that can disagree.
"""

from bfg.common.onboarding.checklist import Item

# Labels name the thing, not its state — see the note on Item.label.

ONBOARDING_ITEMS = {
    'brand': [
        Item(
            key='geo.address_lookup',
            label='Address autocomplete',
            label_zh='地址自动补全',
            href='/admin/settings/general?tab=plugins',
            check=lambda facts: _address_lookup_usable(facts.workspace),
            required=False,
            hint='Optional — turns address entry at checkout into a short list of real addresses. '
                 'Needs GOOGLE_MAPS_API_KEY on the server, so an operator may have to enable it for you.',
            hint_zh='可选。结算时把手输地址变成可选的真实地址列表。'
                    '需要服务端配置 GOOGLE_MAPS_API_KEY，可能要请运维开通。',
        ),
    ],
}


def _address_lookup_usable(workspace) -> bool:
    """`usable`, not `enabled`: a switch that is on with no API key does nothing."""
    from apps.geo.services.config import get_address_lookup_config

    return get_address_lookup_config(workspace).usable
