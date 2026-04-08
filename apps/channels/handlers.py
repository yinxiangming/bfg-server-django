# -*- coding: utf-8 -*-
"""
Event handlers for channels extension.
Registered in ChannelsConfig.ready() via AppConfig.
"""
from bfg.core.events import global_dispatcher
from apps.channels import tasks


def on_product_created(sender, data, **kwargs):
    product = data["data"]["product"]
    workspace = data["workspace"]

    from apps.channels.models import ExternalChannel

    channels = ExternalChannel.objects.filter(
        workspace=workspace,
        is_active=True,
        config__auto_publish=True,
    )
    for ch in channels:
        tasks.publish_to_channel.delay(product.id, ch.id)


def on_product_updated(sender, data, **kwargs):
    product = data["data"]["product"]
    for listing in product.external_listings.filter(status="active"):
        tasks.sync_listing.delay(listing.id)


def on_stock_depleted(sender, data, **kwargs):
    product = data["data"]["product"]
    for listing in product.external_listings.filter(status="active"):
        tasks.end_listing.delay(listing.id)


global_dispatcher.listen("product.created", on_product_created)
global_dispatcher.listen("product.updated", on_product_updated)
global_dispatcher.listen("product.stock_depleted", on_stock_depleted)
