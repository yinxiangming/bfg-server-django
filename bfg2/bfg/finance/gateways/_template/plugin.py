"""
Payment Gateway Plugin Template

Copy this file to create a new payment gateway plugin.
Replace all occurrences of 'Template' with your gateway name.
"""

from bfg.finance.gateways.base import BasePaymentGateway
from typing import Dict, Any, Optional
from decimal import Decimal
from bfg.finance.models import PaymentMethod, Payment, Currency
from bfg.common.models import Customer


class TemplateGateway(BasePaymentGateway):
    """
    Template payment gateway plugin
    
    Replace 'Template' with your gateway name (e.g., PayPal, Alipay)
    """
    
    gateway_type = 'template'  # Change to your gateway type
    display_name = 'Template Gateway'  # Change to your gateway display name
    supported_methods = ['card']  # List supported payment methods
    supported_clients = []  # e.g. ['web','android','ios','mp']; empty = all
    
    def _validate_config(self):
        """
        Validate gateway configuration
        
        Raise ValueError if required config is missing
        """
        # Example: Check for required config
        # required_key = self.config.get('api_key')
        # if not required_key:
        #     raise ValueError("api_key is required in gateway.config")
        pass
    
    def get_config_schema(self) -> Dict[str, Any]:
        """
        Get configuration schema for this gateway
        
        Returns:
            dict: Configuration schema with field definitions
        """
        return {
            'api_key': {
                'type': 'string',
                'required': True,
                'description': 'API Key for gateway',
                'sensitive': True,
            },
            # Add more config fields as needed
        }
    
    def get_frontend_config(self) -> Dict[str, Any]:
        """
        Get frontend configuration (safe to expose)
        
        Returns:
            dict: Frontend config (e.g., publishable_key, client_id)
        """
        return {
            # 'publishable_key': self.config.get('publishable_key'),
        }
    
    # ========================================================================
    # Payment Method Management
    # ========================================================================
    
    def create_payment_method(
        self,
        customer: Customer,
        payment_method_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a payment method in the gateway
        
        Args:
            customer: BFG Customer instance
            payment_method_data: Payment method data from frontend
        
        Returns:
            dict: Gateway payment method object
        """
        # TODO: Implement gateway-specific payment method creation
        # Example:
        # gateway_pm = gateway_api.create_payment_method(...)
        # return {'id': gateway_pm.id, ...}
        
        raise NotImplementedError("create_payment_method must be implemented")
    
    def save_payment_method(
        self,
        customer: Customer,
        gateway_payment_method_id: str,
        payment_method_data: Optional[Dict[str, Any]] = None
    ) -> PaymentMethod:
        """
        Save gateway payment method to BFG PaymentMethod model
        
        Args:
            customer: BFG Customer instance
            gateway_payment_method_id: Payment method ID from gateway
            payment_method_data: Optional additional data from gateway
        
        Returns:
            PaymentMethod: Saved PaymentMethod instance
        """
        # TODO: Retrieve payment method from gateway
        # TODO: Extract card/payment method information
        # TODO: Create PaymentMethod in BFG
        
        # Example:
        # gateway_pm = gateway_api.get_payment_method(gateway_payment_method_id)
        # payment_method = PaymentMethod.objects.create(
        #     workspace=customer.workspace,
        #     customer=customer,
        #     gateway=self.gateway,
        #     method_type='card',
        #     gateway_token=gateway_payment_method_id,
        #     card_brand=gateway_pm.brand,
        #     card_last4=gateway_pm.last4,
        #     ...
        # )
        # return payment_method
        
        raise NotImplementedError("save_payment_method must be implemented")
    
    # ========================================================================
    # Payment Processing
    # ========================================================================
    
    def create_payment_intent(
        self,
        customer: Customer,
        amount: Decimal,
        currency: Currency,
        payment_method_id: Optional[str] = None,
        order_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create payment intent/request in gateway
        
        Args:
            customer: BFG Customer instance
            amount: Payment amount
            currency: Currency instance
            payment_method_id: Optional PaymentMethod ID
            order_id: Optional order ID
            metadata: Optional additional metadata
        
        Returns:
            dict: Payment intent data with client_secret or similar
        """
        # TODO: Create payment intent in gateway
        # Example:
        # intent = gateway_api.create_payment_intent(
        #     amount=int(amount * 100),
        #     currency=currency.code,
        #     customer=customer_id,
        #     ...
        # )
        # return {
        #     'payment_intent_id': intent.id,
        #     'client_secret': intent.client_secret,
        #     'status': intent.status,
        # }
        
        raise NotImplementedError("create_payment_intent must be implemented")
    
    def confirm_payment(
        self,
        payment: Payment,
        payment_intent_id: Optional[str] = None,
        payment_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Confirm/process payment
        
        Args:
            payment: BFG Payment instance
            payment_intent_id: Optional payment intent ID
            payment_details: Optional additional payment details
        
        Returns:
            dict: Payment result
        """
        # TODO: Confirm payment in gateway
        # Example:
        # result = gateway_api.confirm_payment(payment_intent_id, ...)
        # return {
        #     'success': result.status == 'succeeded',
        #     'transaction_id': result.id,
        #     'status': result.status,
        # }
        
        raise NotImplementedError("confirm_payment must be implemented")
    
    # ========================================================================
    # Refunds
    # ========================================================================
    
    def create_refund(
        self,
        payment: Payment,
        amount: Decimal,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create refund
        
        Args:
            payment: BFG Payment instance
            amount: Refund amount
            reason: Optional refund reason
        
        Returns:
            dict: Refund result
        """
        # TODO: Implement refund if supported
        # Example:
        # refund = gateway_api.create_refund(
        #     payment_id=payment.gateway_transaction_id,
        #     amount=int(amount * 100),
        #     reason=reason
        # )
        # return {
        #     'success': True,
        #     'refund_id': refund.id,
        # }
        
        # Default: not supported
        return {
            'success': False,
            'error': 'Refunds not supported by this gateway'
        }
    
    # ========================================================================
    # Webhook Handling
    # ========================================================================
    
    def verify_webhook(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """
        Verify webhook signature
        
        Args:
            payload: Raw webhook payload
            signature: Signature from webhook header
        
        Returns:
            bool: True if signature is valid
        """
        # TODO: Implement webhook signature verification
        # Example:
        # return gateway_api.verify_webhook_signature(payload, signature)
        
        # Default: no verification
        return True
    
    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle webhook event from gateway
        
        Args:
            event_type: Event type (e.g., 'payment.succeeded')
            payload: Webhook payload data
        
        Returns:
            dict: Processing result
        """
        # TODO: Handle gateway-specific webhook events
        # Example:
        # if event_type == 'payment.succeeded':
        #     # Process successful payment
        #     return {'success': True, 'message': 'Payment succeeded'}
        # elif event_type == 'payment.failed':
        #     # Process failed payment
        #     return {'success': True, 'message': 'Payment failed'}
        
        return {
            'success': True,
            'message': f'Event {event_type} processed',
        }
    
    # ========================================================================
    # Customer Management
    # ========================================================================
    
    def get_or_create_customer(
        self,
        customer: Customer
    ) -> str:
        """
        Get or create customer in gateway
        
        Args:
            customer: BFG Customer instance
        
        Returns:
            str: Gateway customer ID
        """
        # TODO: Implement customer creation/retrieval if needed
        # Example:
        # gateway_customer = gateway_api.get_or_create_customer(
        #     email=customer.user.email,
        #     name=customer.get_full_name(),
        #     metadata={'customer_id': str(customer.id)}
        # )
        # return gateway_customer.id
        
        # Default: return customer ID as-is
        return str(customer.id)

