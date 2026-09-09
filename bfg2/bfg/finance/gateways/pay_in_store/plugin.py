"""
Pay in Store Payment Gateway Plugin

Offline payment settled face to face: the customer orders online, collects the order
at a pickup point, and pays the counter there — cash, EFTPOS, a QR code, whatever the
shop takes. Nothing is processed online, so there is no intent to confirm and no
instrument to tokenise; staff mark the payment received once the money is in hand.

Deliberately its own gateway type rather than a `custom` gateway with a note in it.
`custom` cannot say *when* it applies — and this one only applies to an order the
customer physically comes to collect, which is exactly what
`supported_fulfillment_methods` exists to express. Splitting it out also keeps payment
reporting able to tell counter takings from bank transfers.
"""

from typing import Dict, Any, Optional
from decimal import Decimal

from bfg.common.models import Customer
from bfg.finance.gateways.base import BasePaymentGateway
from bfg.finance.models import Currency, Payment, PaymentMethod


class PayInStoreGateway(BasePaymentGateway):
    """Pay in store: take the order, hold it, collect the money over the counter."""

    gateway_type = 'pay_in_store'
    display_name = 'Pay in Store'
    supported_methods = ['offline']
    supported_clients = []  # all clients — nothing here needs an SDK

    # Only offerable on an order the customer collects. Enforced server-side when the
    # payment intent is created; the storefront filter is display only.
    supported_fulfillment_methods = ['pickup']

    # Fields the checkout page renders. One place, so the schema, the display params
    # and the tests cannot drift apart.
    DISPLAY_FIELDS = (
        'accepted_methods',
        'instructions',
    )

    def _validate_config(self):
        """
        Deliberately permissive, matching the other offline gateways.

        Config completeness is enforced by `required` in the schema below, which is what
        the admin form reads. Raising here would take down the storefront's gateway
        listing — which builds display info by constructing this plugin — rather than
        the admin form that left the config half-filled.
        """
        pass

    def get_config_schema(self) -> Dict[str, Any]:
        """
        Both fields optional: a shop that takes anything at the till has nothing to
        narrow, and the pickup point's own `instructions` already tell the customer
        where to go. Nothing here is `sensitive` — it is all written to be read by the
        customer.
        """
        return {
            'accepted_methods': {
                'type': 'string',
                'required': False,
                'description': 'What the counter takes, e.g. "Cash, EFTPOS, WeChat Pay"',
                'sensitive': False,
            },
            'instructions': {
                'type': 'string',
                'required': False,
                'description': 'Shown at checkout — say to pay on collection and what to bring',
                'sensitive': False,
                'multiline': True,
            },
        }

    def get_frontend_config(self) -> Dict[str, Any]:
        """No SDK to configure."""
        return {}

    def get_payment_page_display_params(self) -> Dict[str, Any]:
        """What the checkout page shows under this option."""
        config = self.config or {}
        return {field: config.get(field, '') or '' for field in self.DISPLAY_FIELDS}

    # ------------------------------------------------------------------
    # Payment methods: nothing to store. Cash handed over a counter is not an
    # instrument the shop can keep on file.
    # ------------------------------------------------------------------

    def create_payment_method(
        self,
        customer: Customer,
        payment_method_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {'id': 'pay_in_store', 'status': 'offline'}

    def save_payment_method(
        self,
        customer: Customer,
        gateway_payment_method_id: str,
        payment_method_data: Optional[Dict[str, Any]] = None
    ) -> PaymentMethod:
        raise NotImplementedError("Pay in store does not support saved payment methods")

    # ------------------------------------------------------------------
    # Payment: the money changes hands at the counter, so both of these only
    # record that the shop is waiting for the customer to turn up.
    # ------------------------------------------------------------------

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
        return {
            'payment_intent_id': 'pay_in_store_pending',
            'status': 'pending',
        }

    def confirm_payment(
        self,
        payment: Payment,
        payment_intent_id: Optional[str] = None,
        payment_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Stays pending. Only the person at the till can say the money arrived, so staff
        complete it — `POST /api/v1/finance/payments/{id}/process/`, same as a bank
        transfer that has cleared.
        """
        return {
            'success': True,
            'status': 'pending',
            'transaction_id': payment_intent_id or 'pay_in_store',
        }

    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """No webhooks — a cash drawer does not call us."""
        return {'success': True, 'message': f'Event {event_type} acknowledged'}
