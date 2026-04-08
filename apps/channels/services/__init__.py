# -*- coding: utf-8 -*-
from django.db import transaction
from django.utils.timezone import now

from bfg.core.services import BaseService
from apps.channels.adapters import get_adapter
from apps.channels.models import ExternalChannel, ExternalListing, ExternalFeedback


class ChannelListingService(BaseService):
    def __init__(self, workspace, user, channel: ExternalChannel):
        super().__init__(workspace, user)
        self.channel = channel
        self.adapter = get_adapter(channel)

    def publish_product(self, product) -> ExternalListing:
        listing, _ = ExternalListing.objects.get_or_create(
            product=product,
            channel=self.channel,
            defaults={"status": "pending"},
        )
        if listing.status == "active":
            return listing

        try:
            with transaction.atomic():
                mapped = self.adapter.map_product(product)
                external_id = self.adapter.publish(product)
                listing.external_id = external_id
                listing.status = "active"
                listing.mapped_data = mapped
                listing.last_synced = now()
                listing.error_detail = ""
                listing.save(update_fields=["external_id", "status", "mapped_data", "last_synced", "error_detail", "updated_at"])
                self.emit_event("channel.listing.published", {
                    "listing_id": listing.id,
                    "channel": self.channel.channel_type,
                })
        except Exception as exc:
            # Save error status outside the rolled-back transaction
            listing.status = "error"
            listing.error_detail = str(exc)
            listing.save(update_fields=["status", "error_detail", "updated_at"])
            raise

        return listing

    def sync_product(self, listing: ExternalListing) -> None:
        """Sync product changes to channel; skip if nothing changed."""
        new_mapped = self.adapter.map_product(listing.product)
        if new_mapped == listing.mapped_data:
            return
        self.adapter.update(listing)
        listing.mapped_data = new_mapped
        listing.last_synced = now()
        listing.save(update_fields=["mapped_data", "last_synced", "updated_at"])

    def handle_out_of_stock(self, listing: ExternalListing) -> None:
        if listing.status == "active":
            self.adapter.end(listing)
            listing.status = "ended"
            listing.save(update_fields=["status", "updated_at"])

    def fetch_feedback(self, listing: ExternalListing) -> None:
        for item in self.adapter.fetch_feedback(listing):
            ExternalFeedback.objects.update_or_create(
                external_id=item["id"],
                defaults={
                    "listing": listing,
                    "author": item.get("author", ""),
                    "feedback_type": item.get("type", "positive"),
                    "comment": item.get("comment", ""),
                    "received_at": item.get("date") or now(),
                },
            )


class AutoAnswerEngine:
    def __init__(self, channel: ExternalChannel):
        self.channel = channel

    def get_answer(self, question) -> str | None:
        from apps.channels.models import ChannelFAQRule

        text = question.question_text.lower()
        rules = ChannelFAQRule.objects.filter(
            channel=self.channel, is_active=True
        ).order_by("-priority")

        for rule in rules:
            keywords = rule.keywords if isinstance(rule.keywords, list) else []
            if any(kw.lower() in text for kw in keywords):
                return rule.answer.format(
                    product_name=question.listing.product.name
                )

        if self.channel.config.get("ai_auto_answer"):
            return self._ai_answer(question)

        return None

    def _ai_answer(self, question) -> str | None:
        try:
            from bfg.core.agent import AgentService
        except ImportError:
            return None

        product = question.listing.product
        import re
        description = re.sub(r"<[^>]+>", "", product.description or "")
        context = (
            f"Product: {product.name}\n"
            f"Description: {description}\n"
            f"Price: {product.price}\n"
        )
        agent = AgentService(workspace=self.channel.workspace)
        return agent.ask(
            system="You are a helpful shop assistant. Answer buyer questions concisely and professionally.",
            user=f"Buyer question: {question.question_text}\n\nProduct info:\n{context}",
        )
