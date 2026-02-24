"""
Base Payment Gateway Plugin Interface

All payment gateway plugins must inherit from this base class
and implement the required methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from decimal import Decimal
from django.utils import timezone
from bfg.finance.models import PaymentGateway, PaymentMethod, Payment, Currency
from bfg.common.models import Customer


# Client types for supported_clients. Empty list means all clients supported.
VALID_CLIENT_TYPES = ('web', 'android', 'ios', 'mp')


class BasePaymentGateway(ABC):
    """
    Base class for all payment gateway plugins
    
    Each plugin must implement all abstract methods to provide
    payment gateway functionality.
    """
    
    # Gateway metadata (must be set by subclass)
    gateway_type: str = None  # e.g., 'stripe', 'paypal'
    display_name: str = None  # e.g., 'Stripe', 'PayPal'
    supported_methods: list = []  # e.g., ['card', 'bank']
    # Clients that can use this gateway: 'web', 'android', 'ios', 'mp'. Empty = all.
    supported_clients: list = []
    
    def __init__(self, gateway: PaymentGateway):
        """
        Initialize gateway plugin
        
        Args:
            gateway: PaymentGateway model instance
        """
        if self.gateway_type is None:
            raise ValueError(f"{self.__class__.__name__} must set gateway_type")
        
        if gateway.gateway_type != self.gateway_type:
            raise ValueError(
                f"Gateway type mismatch: expected {self.gateway_type}, "
                f"got {gateway.gateway_type}"
            )
        
        self.gateway = gateway
        self.config = gateway.get_active_config() or {}
        self._validate_config()
    
    def _validate_config(self):
        """
        Validate gateway configuration
        Override in subclass to add custom validation
        """
        pass
    
    # ========================================================================
    # Payment Method Management
    # ========================================================================
    
    @abstractmethod
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
                Format depends on gateway implementation
        
        Returns:
            dict: Gateway payment method object
        """
        pass
    
    @abstractmethod
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
        pass
    
    def delete_payment_method(
        self,
        payment_method: PaymentMethod
    ) -> bool:
        """
        Delete payment method from gateway
        
        Args:
            payment_method: PaymentMethod instance
        
        Returns:
            bool: True if successful
        """
        # Default implementation: just delete from database
        # Override if gateway requires API call to delete
        return True
    
    # ========================================================================
    # Payment Processing
    # ========================================================================
    
    @abstractmethod
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
            payment_method_id: Optional PaymentMethod ID (if using saved method)
            order_id: Optional order ID for metadata
            metadata: Optional additional metadata
        
        Returns:
            dict: Payment intent data with client_secret or similar
                {
                    'payment_intent_id': '...',
                    'client_secret': '...',  # For frontend confirmation
                    'status': '...',
                    ...
                }
        """
        pass
    
    @abstractmethod
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
            payment_intent_id: Optional payment intent ID (if already created)
            payment_details: Optional additional payment details
        
        Returns:
            dict: Payment result
                {
                    'success': bool,
                    'transaction_id': '...',
                    'status': '...',
                    'requires_action': bool,  # For 3D Secure, etc.
                    'client_secret': '...',  # If requires_action is True
                    'error': '...',  # If success is False
                }
        """
        pass
    
    def cancel_payment(
        self,
        payment: Payment
    ) -> Dict[str, Any]:
        """
        Cancel a payment
        
        Args:
            payment: BFG Payment instance
        
        Returns:
            dict: Cancellation result
        """
        # Default: not supported
        return {
            'success': False,
            'error': 'Payment cancellation not supported by this gateway'
        }
    
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
                {
                    'success': bool,
                    'refund_id': '...',
                    'error': '...',  # If success is False
                }
        """
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
        # Default: no verification
        return True
    
    @abstractmethod
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
                {
                    'success': bool,
                    'message': '...',
                }
        """
        pass
    
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
        # Default: return customer ID as-is
        # Override if gateway requires customer creation
        return str(customer.id)
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def get_supported_currencies(self) -> list:
        """
        Get list of supported currency codes
        
        Returns:
            list: List of currency codes (e.g., ['USD', 'EUR', 'CNY'])
        """
        # Default: return common currencies
        return ['USD', 'EUR', 'GBP', 'CNY', 'JPY']
    
    def get_supported_countries(self) -> list:
        """
        Get list of supported country codes
        
        Returns:
            list: List of ISO country codes
        """
        # Default: return all countries
        return []
    
    def get_config_schema(self) -> Dict[str, Any]:
        """
        Get configuration schema for this gateway
        
        Returns:
            dict: Configuration schema
                {
                    'secret_key': {
                        'type': 'string',
                        'required': True,
                        'description': '...'
                    },
                    ...
                }
        """
        return {}
    
    def get_frontend_config(self) -> Dict[str, Any]:
        """
        Get frontend configuration (safe to expose)
        
        Returns:
            dict: Frontend config (e.g., publishable_key)
        """
        return {}

    def get_payment_page_display_params(self) -> Dict[str, Any]:
        """
        Return display parameters for the checkout/payment page.
        Frontend uses this to show gateway-specific info (e.g. bank transfer instructions,
        Stripe publishable key). Override in subclass.
        
        Returns:
            dict: e.g. {'instructions': '...'}, {'publishable_key': '...'}, etc.
        """
        return {}

