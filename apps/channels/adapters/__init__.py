# -*- coding: utf-8 -*-
from apps.channels.adapters.base import ChannelAdapter
from apps.channels.adapters.trademe import TradeMeAdapter
from apps.channels.adapters.shopify import ShopifyAdapter

ADAPTERS = {
    "trademe": TradeMeAdapter,
    "shopify": ShopifyAdapter,
}


def get_adapter(channel) -> ChannelAdapter:
    cls = ADAPTERS.get(channel.channel_type)
    if not cls:
        raise ValueError(f"Unknown channel type: {channel.channel_type}")
    return cls(channel)
