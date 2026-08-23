"""
Bank Transfer Payment Gateway Plugin

Offline payment: the shop's bank details are shown on the checkout page, the customer
places the order and pays by transfer, and an admin marks the payment received. Nothing
is processed online, so there is no intent to confirm and no card to tokenise.

`bank_transfer` has been in PaymentGateway.GATEWAY_TYPE_CHOICES and in the storefront
serializer's display fallback all along, but with no plugin behind it the admin's gateway
dropdown — which is built from discovered plugins, not from the model choices — never
offered it. A shop with no card processor therefore had no way to accept money at all.
"""

from typing import Dict, Any, Optional
from decimal import Decimal

from bfg.common.models import Customer
from bfg.finance.gateways.base import BasePaymentGateway
from bfg.finance.models import Currency, Payment, PaymentMethod


class BankTransferGateway(BasePaymentGateway):
    """Bank transfer: publish account details, take the order, reconcile by hand."""

    gateway_type = 'bank_transfer'
    display_name = 'Bank Transfer'
    supported_methods = ['bank']
    supported_clients = []  # all clients — nothing here needs an SDK

    # Fields the checkout page renders. Kept in one place so the schema, the display
    # params and the tests cannot drift apart.
    DISPLAY_FIELDS = (
        'bank_name',
        'account_name',
        'account_number',
        'routing_number',
        'swift_code',
        'instructions',
    )

    def _validate_config(self):
        """
        Deliberately permissive, matching the other offline gateway.

        Config completeness is enforced by `required` in the schema below, which is what
        the admin form reads. Raising here instead would take down the storefront's
        gateway listing for a half-filled gateway rather than the admin form that caused
        it — the listing builds display info by constructing this plugin.
        """
        pass

    def get_config_schema(self) -> Dict[str, Any]:
        """
        Bank identifiers differ by country: New Zealand and Australia use a single
        account number, the US adds a routing number, and anything cross-border needs a
        SWIFT/BIC. Only the two fields every market has are required.

        Nothing here is `sensitive`: these are the merchant's own details, and the point
        of the gateway is to show them to the customer.
        """
        return {
            'bank_name': {
                'type': 'string',
                'required': False,
                'description': 'Bank name, e.g. as it should appear on the checkout page',
                'sensitive': False,
            },
            'account_name': {
                'type': 'string',
                'required': True,
                'description': 'Name the account is held in',
                'sensitive': False,
            },
            'account_number': {
                'type': 'string',
                'required': True,
                'description': 'Account number, in the format customers are expected to enter it',
                'sensitive': False,
            },
            'routing_number': {
                'type': 'string',
                'required': False,
                'description': 'Routing / sort / BSB number, where the country uses one',
                'sensitive': False,
            },
            'swift_code': {
                'type': 'string',
                'required': False,
                'description': 'SWIFT / BIC, for payments from overseas',
                'sensitive': False,
            },
            'instructions': {
                'type': 'string',
                'required': False,
                'description': 'Shown under the account details — say what reference to use and when the order ships',
                'sensitive': False,
                'multiline': True,
            },
        }

    def get_frontend_config(self) -> Dict[str, Any]:
        """No SDK to configure."""
        return {}

    def get_payment_page_display_params(self) -> Dict[str, Any]:
        """
        The account details the checkout page shows.

        These reach an unauthenticated endpoint, because the customer has to read them
        before they can pay — the same exposure as printing them on an invoice.
        """
        config = self.config or {}
        return {field: config.get(field, '') or '' for field in self.DISPLAY_FIELDS}

    # ------------------------------------------------------------------
    # Payment methods: nothing to store. A bank transfer is not an instrument
    # the shop holds on file; the customer initiates it from their own bank.
    # ------------------------------------------------------------------

    def create_payment_method(
        self,
        customer: Customer,
        payment_method_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {'id': 'bank_transfer', 'status': 'offline'}

    def save_payment_method(
        self,
        customer: Customer,
        gateway_payment_method_id: str,
        payment_method_data: Optional[Dict[str, Any]] = None
    ) -> PaymentMethod:
        raise NotImplementedError("Bank transfer does not support saved payment methods")

    # ------------------------------------------------------------------
    # Payment: the money arrives out of band, so both of these only record
    # that the shop is waiting for it.
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
            'payment_intent_id': 'bank_transfer_pending',
            'status': 'pending',
        }

    def confirm_payment(
        self,
        payment: Payment,
        payment_intent_id: Optional[str] = None,
        payment_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Stays pending. Only a human looking at the bank account can say the money
        arrived, so the admin marks the payment received.
        """
        return {
            'success': True,
            'status': 'pending',
            'transaction_id': payment_intent_id or 'bank_transfer',
        }

    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """No webhooks — a bank does not call us."""
        return {'success': True, 'message': f'Event {event_type} acknowledged'}
