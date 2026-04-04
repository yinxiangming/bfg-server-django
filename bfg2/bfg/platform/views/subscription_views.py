# -*- coding: utf-8 -*-
"""
Subscription & Webhook ViewSets.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import logging

logger = logging.getLogger(__name__)


class WebhookViewSet(viewsets.ViewSet):
    """
    Stripe webhook endpoint.

    POST /api/v1/platform/webhooks/stripe/
    """
    permission_classes = [AllowAny]

    @action(detail=False, methods=['post'], url_path='stripe')
    def stripe(self, request):
        """POST /api/v1/platform/webhooks/stripe/"""
        import stripe
        from django.conf import settings
        from bfg.platform.services.subscription_service import SubscriptionService
        from bfg.platform.services.billing_service import handle_invoice_event

        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

        if not webhook_secret:
            logger.error('STRIPE_WEBHOOK_SECRET not configured')
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.warning(f'Stripe webhook verification failed: {e}')
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event_type = event['type']
        obj = event['data']['object']
        svc = SubscriptionService()

        handlers = {
            'checkout.session.completed':      svc.handle_checkout_completed,
            'customer.subscription.updated':   svc.handle_subscription_updated,
            'customer.subscription.deleted':   svc.handle_subscription_deleted,
            'invoice.created':                 handle_invoice_event,
            'invoice.paid':                    handle_invoice_event,
            'invoice.payment_failed':          handle_invoice_event,
        }

        handler = handlers.get(event_type)
        if handler:
            try:
                handler(obj)
                logger.info(f'Stripe webhook handled: {event_type}')
            except Exception as e:
                logger.error(f'Webhook handler error ({event_type}): {e}', exc_info=True)
                return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'status': 'ok'})
