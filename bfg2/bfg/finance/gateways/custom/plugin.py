"""
Custom Payment Gateway Plugin

Generic type for manual/offline payment (e.g. Bank Transfer).
Displays a configurable note/instructions on the checkout page.
No online payment processing; admin marks payment as completed manually.
"""

from typing import Dict, Any, Optional
from decimal import Decimal
from bfg.finance.gateways.base import BasePaymentGateway
from bfg.finance.models import PaymentMethod, Payment, Currency
from bfg.common.models import Customer


class CustomGateway(BasePaymentGateway):
    """
    Custom gateway (e.g. Bank Transfer): note/instructions shown on payment page.
    """

    gateway_type = 'custom'
    display_name = 'Custom Payment'
    supported_methods = ['custom']
    supported_clients = []  # all clients (e.g. bank transfer instructions)

    def _validate_config(self):
        """Config validation; note is optional at load time (required in admin schema)."""
        pass

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            'note': {
                'type': 'string',
                'required': True,
                'description': 'Payment instructions shown on checkout (supports line breaks)',
                'sensitive': False,
                'multiline': True,
            },
        }

    def get_payment_page_display_params(self) -> Dict[str, Any]:
        """Return instructions for the checkout payment page."""
        note = self.config.get('note', '')
        return {
            'instructions': note if note else '',
        }

    def create_payment_method(
        self,
        customer: Customer,
        payment_method_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """No gateway payment method for custom."""
        return {'id': 'custom', 'status': 'offline'}

    def save_payment_method(
        self,
        customer: Customer,
        gateway_payment_method_id: str,
        payment_method_data: Optional[Dict[str, Any]] = None
    ) -> PaymentMethod:
        """Custom gateway does not save payment methods."""
        raise NotImplementedError("Custom gateway does not support saved payment methods")

    def create_payment_intent(
        self,
        customer: Customer,
        amount: Decimal,
        currency: Currency,
        payment_method_id: Optional[str] = None,
        order_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Return pending intent; no client_secret needed."""
        return {
            'payment_intent_id': 'custom_pending',
            'status': 'pending',
        }

    def confirm_payment(
        self,
        payment: Payment,
        payment_intent_id: Optional[str] = None,
        payment_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Payment is confirmed manually by admin."""
        return {
            'success': True,
            'status': 'pending',
            'transaction_id': payment_intent_id or 'custom',
        }

    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """No webhooks for custom gateway."""
        return {'success': True, 'message': f'Event {event_type} acknowledged'}
