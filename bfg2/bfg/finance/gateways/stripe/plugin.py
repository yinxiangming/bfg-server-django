"""
Stripe Payment Gateway Plugin

Stripe integration plugin implementing BasePaymentGateway interface
"""

import os
import logging
import stripe
from typing import Dict, Any, Optional
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from bfg.finance.gateways.base import BasePaymentGateway
from bfg.finance.models import PaymentMethod, Payment, Currency
from bfg.finance.exceptions import PaymentMethodInvalid
from bfg.common.models import Customer

logger = logging.getLogger(__name__)


class StripeGateway(BasePaymentGateway):
    """
    Stripe payment gateway plugin
    """
    
    gateway_type = 'stripe'
    display_name = 'Stripe'
    supported_methods = ['card']
    # Stripe Elements/card not typically used in WeChat mini-program; use wechat gateway for mp
    supported_clients = ['web', 'android', 'ios']
    
    # Class-level flag to track if SSL config has been applied
    _ssl_configured = False
    
    @classmethod
    def _ensure_ssl_config(cls):
        """Ensure SSL configuration is applied for Stripe API calls."""
        if cls._ssl_configured:
            return
        
        verify_ssl = os.getenv('STRIPE_VERIFY_SSL', '').lower()
        if verify_ssl == 'false':
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            try:
                from stripe._http_client import RequestsClient
                http_client = RequestsClient(verify_ssl_certs=False, timeout=80)
                stripe.default_http_client = http_client
            except (ImportError, AttributeError):
                pass
        
        cls._ssl_configured = True
    
    def _validate_config(self):
        """Validate Stripe configuration"""
        # Ensure SSL config is applied
        self._ensure_ssl_config()
        
        api_key = self.config.get('secret_key') or self.config.get('api_key')
        if not api_key:
            raise ValueError("Stripe secret_key not configured in gateway.config")
        
        # Validate API key format
        if not (api_key.startswith('sk_test_') or api_key.startswith('sk_live_')):
            raise ValueError(
                f"Invalid Stripe API key format. Expected 'sk_test_...' or 'sk_live_...', "
                f"got: {api_key[:10]}..."
            )
        
        # Set Stripe API key
        stripe.api_key = api_key
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Get Stripe configuration schema"""
        return {
            'secret_key': {
                'type': 'string',
                'required': True,
                'description': 'Stripe Secret Key (sk_test_... or sk_live_...)',
                'sensitive': True,
            },
            'publishable_key': {
                'type': 'string',
                'required': True,
                'description': 'Stripe Publishable Key (pk_test_... or pk_live_...)',
                'sensitive': False,
            },
            'webhook_secret': {
                'type': 'string',
                'required': True,
                'description': 'Stripe Webhook Secret (whsec_...)',
                'sensitive': True,
            },
        }
    
    def get_frontend_config(self) -> Dict[str, Any]:
        """Get frontend configuration"""
        return {
            'publishable_key': self.config.get('publishable_key'),
        }

    def get_payment_page_display_params(self) -> Dict[str, Any]:
        """Params for checkout payment page (publishable_key, supports_saved_cards)."""
        return {
            'publishable_key': self.config.get('publishable_key', ''),
            'supports_saved_cards': True,
        }

    # ========================================================================
    # Payment Method Management
    # ========================================================================
    
    def create_payment_method(
        self,
        customer: Customer,
        payment_method_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create or attach Stripe PaymentMethod"""
        stripe_customer_id = self._get_or_create_stripe_customer(customer)
        
        # If payment_method_id is provided, retrieve and attach it
        payment_method_id = None
        stripe_payment_method = None
        
        if 'payment_method_id' in payment_method_data:
            payment_method_id = payment_method_data['payment_method_id']
            try:
                stripe_payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
            except (stripe.error.APIConnectionError, stripe.error.APIError) as e:
                logger.warning(f"Failed to retrieve PaymentMethod {payment_method_id}: {e}")
                raise
        else:
            # Create PaymentMethod in Stripe
            try:
                stripe_payment_method = stripe.PaymentMethod.create(**payment_method_data)
                payment_method_id = stripe_payment_method.id
            except (stripe.error.APIConnectionError, stripe.error.APIError) as e:
                logger.error(f"Failed to create PaymentMethod: {e}")
                raise
        
        # Check if PaymentMethod is already attached to this customer
        if stripe_payment_method.customer == stripe_customer_id:
            # Already attached to this customer, no need to attach again
            pass
        elif stripe_payment_method.customer is None:
            # Not attached to any customer, try to attach
            try:
                stripe.PaymentMethod.attach(
                    stripe_payment_method.id,
                    customer=stripe_customer_id
                )
            except stripe.error.InvalidRequestError as e:
                # PaymentMethod may have been used in a payment without being attached first
                # or already attached by setup_future_usage
                error_msg = str(e)
                if 'already been attached' in error_msg:
                    # Already attached (likely by setup_future_usage), re-fetch to verify
                    stripe_payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                    if stripe_payment_method.customer == stripe_customer_id:
                        logger.info(f"PaymentMethod {payment_method_id} was already attached to customer {stripe_customer_id}")
                    else:
                        logger.warning(f"PaymentMethod {payment_method_id} attached to different customer: {stripe_payment_method.customer}")
                else:
                    logger.warning(f"Cannot attach PaymentMethod {payment_method_id}: {e}")
            except (stripe.error.APIConnectionError, stripe.error.APIError) as e:
                logger.warning(f"Failed to attach PaymentMethod {payment_method_id}: {e}")
        else:
            # Attached to a different customer - check if it's actually the same customer
            # (Stripe may return customer ID in different formats)
            # Re-fetch to get latest state
            try:
                stripe_payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                if stripe_payment_method.customer == stripe_customer_id:
                    # Actually the same customer, no need to attach
                    logger.info(f"PaymentMethod {payment_method_id} already attached to customer {stripe_customer_id}")
                else:
                    # Try to attach anyway, but don't raise on "already attached" error
                    try:
                        stripe.PaymentMethod.attach(
                            stripe_payment_method.id,
                            customer=stripe_customer_id
                        )
                    except stripe.error.InvalidRequestError as e:
                        error_msg = str(e)
                        if 'already been attached' in error_msg:
                            # Re-fetch and verify
                            stripe_payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                            if stripe_payment_method.customer != stripe_customer_id:
                                logger.error(f"PaymentMethod {payment_method_id} attached to different customer: {stripe_payment_method.customer}")
                                raise PaymentMethodInvalid(
                                    message="This payment method belongs to a different customer.",
                                    code="payment_method_customer_mismatch"
                                )
                        else:
                            logger.error(f"Cannot attach PaymentMethod {payment_method_id}: {e}")
                            raise
            except stripe.error.InvalidRequestError as e:
                logger.error(f"Failed to verify PaymentMethod {payment_method_id}: {e}")
                raise
            except (stripe.error.APIConnectionError, stripe.error.APIError) as e:
                logger.warning(f"Failed to attach PaymentMethod {payment_method_id}: {e}")
        
        # Set as default if needed
        if payment_method_data.get('set_as_default', False):
            stripe.Customer.modify(
                stripe_customer_id,
                invoice_settings={'default_payment_method': stripe_payment_method.id}
            )
        
        return stripe_payment_method
    
    def save_payment_method(
        self,
        customer: Customer,
        gateway_payment_method_id: str,
        payment_method_data: Optional[Dict[str, Any]] = None
    ) -> PaymentMethod:
        """Save Stripe PaymentMethod to BFG PaymentMethod model"""
        # Ensure SSL config is applied
        self._ensure_ssl_config()
        
        # Get or create Stripe customer
        stripe_customer_id = self._get_or_create_stripe_customer(customer)
        
        # Retrieve PaymentMethod from Stripe
        stripe_pm = stripe.PaymentMethod.retrieve(gateway_payment_method_id)
        
        # Attach PaymentMethod to customer if not already attached
        if stripe_pm.customer is None:
            try:
                stripe.PaymentMethod.attach(
                    gateway_payment_method_id,
                    customer=stripe_customer_id
                )
                logger.info(f"Attached PaymentMethod {gateway_payment_method_id} to customer {stripe_customer_id}")
            except stripe.error.InvalidRequestError as e:
                logger.warning(f"Cannot attach PaymentMethod {gateway_payment_method_id}: {e}")
        elif stripe_pm.customer != stripe_customer_id:
            logger.warning(f"PaymentMethod {gateway_payment_method_id} is attached to different customer")
        
        # Extract card information
        card = stripe_pm.card if hasattr(stripe_pm, 'card') else None
        if not card:
            raise ValueError("PaymentMethod is not a card")
        
        # Map Stripe card brand to our choices
        brand_mapping = {
            'visa': 'visa',
            'mastercard': 'mastercard',
            'amex': 'amex',
            'discover': 'discover',
            'jcb': 'jcb',
            'diners': 'diners',
            'unionpay': 'unionpay',
        }
        card_brand = brand_mapping.get(card.brand.lower(), 'unknown')
        
        # Create PaymentMethod in BFG
        # Handle null cardholder_name - use empty string as default
        cardholder_name = stripe_pm.billing_details.get('name') or ''
        
        payment_method = PaymentMethod.objects.create(
            workspace=customer.workspace,
            customer=customer,
            gateway=self.gateway,
            method_type='card',
            gateway_token=gateway_payment_method_id,
            cardholder_name=cardholder_name,
            card_brand=card_brand,
            card_last4=card.last4,
            card_exp_month=card.exp_month,
            card_exp_year=card.exp_year,
            display_info=f"{card.brand.upper()} •••• {card.last4}",
            is_default=payment_method_data.get('set_as_default', False) if payment_method_data else False,
            is_active=True
        )
        
        # Unset other default payment methods if this is default
        if payment_method.is_default:
            PaymentMethod.objects.filter(
                customer=customer,
                is_default=True
            ).exclude(id=payment_method.id).update(is_default=False)
        
        return payment_method
    
    def delete_payment_method(
        self,
        payment_method: PaymentMethod
    ) -> bool:
        """Delete payment method from Stripe"""
        self._ensure_ssl_config()
        try:
            stripe.PaymentMethod.detach(payment_method.gateway_token)
            return True
        except stripe.error.StripeError:
            # PaymentMethod may already be deleted in Stripe
            return True
    
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
        metadata: Optional[Dict[str, Any]] = None,
        save_card: bool = False
    ) -> Dict[str, Any]:
        """Create Stripe PaymentIntent"""
        stripe_customer_id = self._get_or_create_stripe_customer(customer)
        
        # Prepare metadata
        intent_metadata = metadata or {}
        if order_id:
            intent_metadata['order_id'] = str(order_id)
        intent_metadata['customer_id'] = str(customer.id)
        intent_metadata['workspace_id'] = str(customer.workspace.id)
        
        # Create PaymentIntent
        intent_params = {
            'amount': int(amount * 100),  # Convert to cents
            'currency': currency.code.lower(),
            'customer': stripe_customer_id,
            'metadata': intent_metadata,
            'payment_method_types': ['card'],
        }
        
        # If user wants to save the card, set setup_future_usage
        # This tells Stripe to attach the PaymentMethod to the customer after payment
        if save_card:
            intent_params['setup_future_usage'] = 'off_session'
        
        # Attach payment method if provided
        if payment_method_id:
            if not payment_method_id.startswith('pm_'):
                raise ValueError(f"Invalid PaymentMethod ID format: {payment_method_id}")
            
            # Check if PaymentMethod is still valid (attached to this Stripe customer)
            try:
                pm = stripe.PaymentMethod.retrieve(payment_method_id)
                if pm.customer != stripe_customer_id:
                    raise PaymentMethodInvalid(
                        message="This payment method is no longer valid. Please use a new card.",
                        code="payment_method_customer_mismatch"
                    )
                intent_params['payment_method'] = payment_method_id
                intent_params['confirmation_method'] = 'automatic'
                intent_params['confirm'] = False
            except stripe.error.InvalidRequestError:
                raise PaymentMethodInvalid()
        
        payment_intent = stripe.PaymentIntent.create(**intent_params)
        
        return {
            'payment_intent_id': payment_intent.id,
            'client_secret': payment_intent.client_secret,
            'status': payment_intent.status,
        }
    
    def confirm_payment(
        self,
        payment: Payment,
        payment_intent_id: Optional[str] = None,
        payment_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Confirm/process Stripe payment"""
        self._ensure_ssl_config()
        if payment_intent_id:
            # Confirm existing PaymentIntent
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            if payment_intent.status == 'succeeded':
                return {
                    'success': True,
                    'transaction_id': payment_intent.id,
                    'status': payment_intent.status,
                }
            elif payment_intent.status == 'requires_action':
                return {
                    'success': False,
                    'requires_action': True,
                    'client_secret': payment_intent.client_secret,
                    'status': payment_intent.status,
                }
            else:
                # Confirm the payment intent
                confirm_params = {}
                if payment_details and 'payment_method' in payment_details:
                    confirm_params['payment_method'] = payment_details['payment_method']
                if payment_details and 'return_url' in payment_details:
                    confirm_params['return_url'] = payment_details['return_url']
                
                payment_intent = stripe.PaymentIntent.confirm(
                    payment_intent_id,
                    **confirm_params
                )
        else:
            # Create and confirm new PaymentIntent
            stripe_customer_id = self._get_or_create_stripe_customer(payment.customer)
            
            payment_method_id = None
            if payment.payment_method:
                payment_method_id = payment.payment_method.gateway_token
            
            payment_intent = stripe.PaymentIntent.create(
                amount=int(payment.amount * 100),
                currency=payment.currency.code.lower(),
                customer=stripe_customer_id,
                payment_method=payment_method_id,
                confirm=True,
                metadata={
                    'payment_id': str(payment.id),
                    'payment_number': payment.payment_number,
                    'order_id': str(payment.order.id) if payment.order else '',
                }
            )
        
        # Check status
        if payment_intent.status == 'succeeded':
            return {
                'success': True,
                'transaction_id': payment_intent.id,
                'status': payment_intent.status,
            }
        elif payment_intent.status == 'requires_action':
            return {
                'success': False,
                'requires_action': True,
                'client_secret': payment_intent.client_secret,
                'status': payment_intent.status,
            }
        else:
            return {
                'success': False,
                'transaction_id': payment_intent.id,
                'status': payment_intent.status,
                'error': payment_intent.get('last_payment_error', {}).get('message', 'Payment failed'),
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
        """Create Stripe refund"""
        self._ensure_ssl_config()
        if not payment.gateway_transaction_id:
            return {
                'success': False,
                'error': 'Payment has no Stripe transaction ID'
            }
        
        try:
            refund = stripe.Refund.create(
                payment_intent=payment.gateway_transaction_id,
                amount=int(amount * 100),  # Convert to cents
                metadata={
                    'payment_id': str(payment.id),
                    'payment_number': payment.payment_number,
                    'reason': reason or '',
                }
            )
            
            return {
                'success': True,
                'refund_id': refund.id,
                'status': refund.status,
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e),
            }
    
    # ========================================================================
    # Webhook Handling
    # ========================================================================
    
    def verify_webhook(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Stripe webhook signature"""
        webhook_secret = self.config.get('webhook_secret')
        if not webhook_secret:
            return False
        
        try:
            stripe.Webhook.construct_event(
                payload, signature, webhook_secret
            )
            return True
        except (ValueError, stripe.error.SignatureVerificationError):
            return False
    
    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle Stripe webhook events"""
        event_data = payload.get('data', {}).get('object', {})
        
        if event_type == 'payment_intent.succeeded':
            return {
                'success': True,
                'message': 'Payment succeeded event processed',
                'payment_intent_id': event_data.get('id'),
            }
        elif event_type == 'payment_intent.payment_failed':
            return {
                'success': True,
                'message': 'Payment failed event processed',
                'payment_intent_id': event_data.get('id'),
            }
        elif event_type == 'payment_method.attached':
            return {
                'success': True,
                'message': 'Payment method attached event processed',
            }
        else:
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
        """Get or create Stripe Customer"""
        return self._get_or_create_stripe_customer(customer)
    
    def _get_or_create_stripe_customer(self, customer: Customer) -> str:
        """Get or create Stripe Customer ID for BFG Customer"""
        self._ensure_ssl_config()
        # Check if customer already has Stripe customer ID in gateway_metadata
        gateway_metadata = getattr(customer, 'gateway_metadata', None) or {}
        stripe_customer_id = gateway_metadata.get('stripe_customer_id')
        
        if stripe_customer_id:
            # Verify customer exists in Stripe
            try:
                stripe.Customer.retrieve(stripe_customer_id)
                return stripe_customer_id
            except stripe.error.StripeError:
                # Customer doesn't exist in Stripe, create new one
                pass
        
        # Try to find Stripe Customer ID from existing PaymentMethods
        if not stripe_customer_id:
            existing_pm = PaymentMethod.objects.filter(
                customer=customer,
                gateway=self.gateway,
                gateway_token__startswith='pm_'
            ).first()
            
            if existing_pm and existing_pm.gateway_token:
                try:
                    # Get the Stripe PaymentMethod to find its customer
                    stripe_pm = stripe.PaymentMethod.retrieve(existing_pm.gateway_token)
                    if stripe_pm.customer:
                        stripe_customer_id = stripe_pm.customer
                        # Save it to gateway_metadata
                        if not gateway_metadata:
                            gateway_metadata = {}
                        gateway_metadata['stripe_customer_id'] = stripe_customer_id
                        customer.gateway_metadata = gateway_metadata
                        customer.save(update_fields=['gateway_metadata'])
                        return stripe_customer_id
                except stripe.error.StripeError:
                    pass
        
        # Create new Stripe customer with error handling
        try:
            stripe_customer = stripe.Customer.create(
                email=customer.user.email if customer.user else None,
                name=customer.get_full_name() if hasattr(customer, 'get_full_name') else None,
                metadata={
                    'customer_id': str(customer.id),
                    'workspace_id': str(customer.workspace.id),
                }
            )
        except stripe.error.APIConnectionError as e:
            # Handle SSL/network errors with more helpful message
            error_msg = str(e)
            if 'SSL' in error_msg or 'certificate' in error_msg.lower():
                # Check if SSL verification is disabled
                verify_ssl = os.getenv('STRIPE_VERIFY_SSL', '').lower()
                suggestions = []
                
                if verify_ssl != 'false':
                    suggestions.append(
                        "For local development, you can temporarily disable SSL verification:\n"
                        "  Set environment variable: STRIPE_VERIFY_SSL=false\n"
                        "  ⚠️  WARNING: Only use this in local development, never in production!"
                    )
                
                suggestions.extend([
                    "1. Update Python SSL certificates:",
                    "   macOS: /Applications/Python\\ 3.x/Install\\ Certificates.command",
                    "   Or: pip install --upgrade certifi",
                    "",
                    "2. Check network connection:",
                    "   curl -I https://api.stripe.com",
                    "",
                    "3. Check for proxy/firewall issues",
                    "",
                    f"Original error: {error_msg}"
                ])
                
                raise ConnectionError(
                    "Cannot connect to Stripe API due to SSL certificate verification failure.\n\n"
                    + "\n".join(suggestions)
                ) from e
            raise
        except stripe.error.StripeError as e:
            # Re-raise other Stripe errors as-is
            raise
        
        # Store Stripe customer ID in gateway_metadata
        if not gateway_metadata:
            gateway_metadata = {}
        gateway_metadata['stripe_customer_id'] = stripe_customer.id
        customer.gateway_metadata = gateway_metadata
        customer.save(update_fields=['gateway_metadata'])
        
        return stripe_customer.id

