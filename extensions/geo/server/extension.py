# -*- coding: utf-8 -*-
"""Address lookup, switched on per workspace from the extension marketplace."""

from django.utils.translation import gettext_lazy as _

from bfg.common.extensions import (
    PRICING_ADDON,
    SCOPE_WORKSPACE,
    SURFACE_ACCOUNT,
    SURFACE_ADMIN,
    SURFACE_MINIPROGRAM,
    SURFACE_STOREFRONT,
    ExtensionManifest,
    setting_present,
)

# What Google bills for, and what a workspace is billed for in turn. They are
# defined here, beside the manifest that declares them, and imported by the code
# that spends them: the platform maps a meter back to the extension that owns it
# by matching these strings against ``meters``, so a name that drifted from this
# list would quietly stop being gated on the extension rather than fail loudly.
METER_AUTOCOMPLETE = 'maps.autocomplete'
METER_PLACE_DETAILS = 'maps.place_details'
METER_GEOCODE = 'maps.geocode'

EXTENSION = ExtensionManifest(
    key='geo',
    name=_('Address lookup'),
    description=_('Suggest and complete addresses as shoppers type, using Google Maps.'),
    name_zh='地址自动补全',
    description_zh='顾客在店面、顾客中心和小程序里填写地址时，给出匹配的地址建议，减少填写错误。',
    icon='tabler-map-pin',
    # No page of its own: the switch lives on the plugins tab of the general settings.
    admin_url='/admin/settings/general?tab=plugins',
    scope=SCOPE_WORKSPACE,
    pricing=PRICING_ADDON,
    surfaces=(SURFACE_STOREFRONT, SURFACE_ACCOUNT, SURFACE_MINIPROGRAM, SURFACE_ADMIN),
    prerequisites=(setting_present('GOOGLE_MAPS_API_KEY'),),
    meters=(METER_AUTOCOMPLETE, METER_PLACE_DETAILS, METER_GEOCODE),
    # Bookkeeping rather than anything a workspace would miss: one row per address
    # lookup still being typed, kept only until the lookup is paid for one way or
    # the other. Declared so the extension still owns up to the table it writes.
    data_models=('geo.AutocompleteSession',),
)
