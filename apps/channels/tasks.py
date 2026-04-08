# -*- coding: utf-8 -*-
from datetime import timedelta

from celery import shared_task
from django.utils.timezone import now


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def publish_to_channel(self, product_id: int, channel_id: int):
    """Publish a product to a specific channel asynchronously."""
    try:
        from apps.channels.models import ExternalChannel
        from apps.channels.services import ChannelListingService

        channel = ExternalChannel.objects.get(id=channel_id)
        # Import Product dynamically to avoid circular imports
        from django.apps import apps
        Product = apps.get_model("shop", "Product")
        product = Product.objects.get(id=product_id)

        service = ChannelListingService(
            workspace=channel.workspace,
            user=None,
            channel=channel,
        )
        service.publish_product(product)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_listing(self, listing_id: int):
    """Sync a listing's product data with the channel."""
    try:
        from apps.channels.models import ExternalListing
        from apps.channels.services import ChannelListingService

        listing = ExternalListing.objects.select_related("channel", "product").get(id=listing_id)
        service = ChannelListingService(
            workspace=listing.channel.workspace,
            user=None,
            channel=listing.channel,
        )
        service.sync_product(listing)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def end_listing(listing_id: int):
    """End/withdraw a listing from the channel."""
    from apps.channels.models import ExternalListing
    from apps.channels.services import ChannelListingService

    listing = ExternalListing.objects.select_related("channel", "product").get(id=listing_id)
    service = ChannelListingService(
        workspace=listing.channel.workspace,
        user=None,
        channel=listing.channel,
    )
    service.handle_out_of_stock(listing)


@shared_task
def relist_listing(listing_id: int):
    """Relist an expired/ended listing."""
    from apps.channels.models import ExternalListing
    from apps.channels.adapters import get_adapter

    listing = ExternalListing.objects.select_related("channel", "product").get(id=listing_id)
    adapter = get_adapter(listing.channel)
    new_external_id = adapter.relist(listing)
    listing.external_id = new_external_id
    listing.status = "active"
    listing.last_synced = now()
    listing.save(update_fields=["external_id", "status", "last_synced", "updated_at"])


@shared_task
def fetch_listing_feedback(listing_id: int):
    """Fetch feedback for a single listing."""
    from apps.channels.models import ExternalListing
    from apps.channels.services import ChannelListingService

    listing = ExternalListing.objects.select_related("channel", "product").get(id=listing_id)
    service = ChannelListingService(
        workspace=listing.channel.workspace,
        user=None,
        channel=listing.channel,
    )
    service.fetch_feedback(listing)


@shared_task
def fetch_and_answer_questions(listing_id: int):
    """Fetch questions for a listing and auto-answer if rules match."""
    from apps.channels.models import ExternalListing, ExternalQuestion
    from apps.channels.adapters import get_adapter
    from apps.channels.services import AutoAnswerEngine
    from django.utils.timezone import now as _now

    listing = ExternalListing.objects.select_related("channel", "product").get(id=listing_id)
    adapter = get_adapter(listing.channel)
    engine = AutoAnswerEngine(listing.channel)

    for item in adapter.fetch_questions(listing):
        question, created = ExternalQuestion.objects.get_or_create(
            external_id=item["id"],
            defaults={
                "listing": listing,
                "question_text": item.get("question", ""),
                "asker": item.get("asker", ""),
                "asked_at": item.get("date") or _now(),
                "answer_status": "pending",
            },
        )
        if not created or question.answer_status != "pending":
            continue

        answer = engine.get_answer(question)
        if answer:
            delay = listing.channel.config.get("answer_delay_minutes", 0)
            if delay:
                answer_question_delayed.apply_async(
                    args=[question.id, answer],
                    countdown=delay * 60,
                )
            else:
                _post_answer(question, answer, adapter)


def _post_answer(question, answer: str, adapter) -> None:
    from django.utils.timezone import now as _now

    adapter.post_answer(question, answer)
    question.answer_text = answer
    question.answer_status = "answered"
    question.answered_at = _now()
    question.is_auto_answered = True
    question.save(update_fields=["answer_text", "answer_status", "answered_at", "is_auto_answered"])


@shared_task
def answer_question_delayed(question_id: int, answer: str):
    """Post a delayed auto-answer to avoid looking like a bot."""
    from apps.channels.models import ExternalQuestion
    from apps.channels.adapters import get_adapter

    question = ExternalQuestion.objects.select_related("listing__channel").get(id=question_id)
    adapter = get_adapter(question.listing.channel)
    _post_answer(question, answer, adapter)


@shared_task
def periodic_fetch_feedback():
    """Hourly: pull feedback for all active listings."""
    from apps.channels.models import ExternalListing

    for listing in ExternalListing.objects.filter(status="active"):
        fetch_listing_feedback.delay(listing.id)


@shared_task
def periodic_fetch_questions():
    """Every 15 minutes: pull buyer questions and trigger auto-answer."""
    from apps.channels.models import ExternalListing

    for listing in ExternalListing.objects.filter(status="active"):
        fetch_and_answer_questions.delay(listing.id)


@shared_task
def periodic_relist_check():
    """Daily at 2 AM: relist listings expiring within 24 hours."""
    from apps.channels.models import ExternalListing

    expiring = ExternalListing.objects.filter(
        status="active",
        expires_at__lt=now() + timedelta(hours=24),
        channel__config__auto_relist=True,
    )
    for listing in expiring:
        relist_listing.delay(listing.id)
