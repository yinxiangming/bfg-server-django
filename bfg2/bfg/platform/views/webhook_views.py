# -*- coding: utf-8 -*-
"""
Stripe Webhook views for platform billing events.
"""
import logging
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from bfg.platform.services.subscription_service import SubscriptionService
from bfg.platform.services.billing_service import handle_invoice_event

logger = logging.getLogger(__name__)


class StripeWebhookView(APIView):
    """
    POST /api/platform/webhooks/stripe/
    Handles incoming Stripe webhook events for platform billing.
    Verifies signature, then dispatches to appropriate handler.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        import stripe

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)

        if not webhook_secret:
            logger.error("STRIPE_WEBHOOK_SECRET not configured")
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.warning(f"Stripe webhook verification failed: {e}")
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event_type = event["type"]
        data_object = event["data"]["object"]
        service = SubscriptionService()

        handlers = {
            "checkout.session.completed": service.handle_checkout_completed,
            "customer.subscription.updated": service.handle_subscription_updated,
            "customer.subscription.deleted": service.handle_subscription_deleted,
            "invoice.created": handle_invoice_event,
            "invoice.paid": handle_invoice_event,
            "invoice.payment_failed": handle_invoice_event,
        }

        handler = handlers.get(event_type)
        if handler:
            try:
                handler(data_object)
                logger.info(f"Stripe webhook handled: {event_type}")
            except Exception as e:
                logger.error(f"Stripe webhook handler error ({event_type}): {e}", exc_info=True)
                return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.debug(f"Unhandled Stripe event type: {event_type}")

        return Response({"status": "ok"})
