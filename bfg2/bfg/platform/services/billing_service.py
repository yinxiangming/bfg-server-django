# -*- coding: utf-8 -*-
"""
Billing Service
Handles invoice management and Stripe invoice webhook processing.
"""
from django.apps import apps
from django.utils import timezone


def handle_invoice_event(stripe_invoice: dict) -> None:
    """
    Stripe Webhook handler for invoice.* events.
    Upserts finance.Invoice with Stripe data.
    """
    Invoice = apps.get_model("finance", "Invoice")
    Subscription = apps.get_model("shop", "Subscription")

    stripe_sub_id = stripe_invoice.get("subscription")
    if not stripe_sub_id:
        return

    sub = Subscription.objects.filter(
        stripe_subscription_id=stripe_sub_id,
        is_platform_billing=True,
    ).select_related("workspace", "customer").first()
    if not sub:
        return

    status_map = {
        "draft": "draft",
        "open": "sent",
        "paid": "paid",
        "uncollectible": "void",
        "void": "void",
    }

    Invoice.objects.update_or_create(
        stripe_invoice_id=stripe_invoice["id"],
        defaults={
            "workspace": sub.workspace,
            "customer": sub.customer,
            "subscription": sub,
            "status": status_map.get(stripe_invoice.get("status"), "draft"),
            "total": stripe_invoice.get("amount_due", 0) / 100,
            "currency": stripe_invoice.get("currency", "usd").upper(),
            "hosted_invoice_url": stripe_invoice.get("hosted_invoice_url", ""),
            "external_pdf_url": stripe_invoice.get("invoice_pdf", ""),
            "issue_date": timezone.now(),
            "paid_date": timezone.now() if stripe_invoice.get("status") == "paid" else None,
        },
    )
