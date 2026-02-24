"""
BFG Finance Module Services

Payment processing service
"""

from typing import Any, Optional, Dict
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from bfg.core.services import BaseService
from bfg.finance.exceptions import PaymentFailed, InsufficientFunds
from bfg.finance.models import (
    Payment, PaymentGateway, PaymentMethod, Refund, Transaction, Currency
)
from bfg.common.models import Customer
from bfg.common.services import AuditService
from bfg.shop.models import Order
from bfg.delivery.models import FreightState


class PaymentService(BaseService):
    """
    Payment processing service
    
    Handles payment creation, processing, and webhook events
    """
    
    @transaction.atomic
    def create_payment(
        self,
        customer: Customer,
        amount: Decimal,
        currency: Currency,
        gateway: PaymentGateway,
        **kwargs: Any
    ) -> Payment:
        """
        Create payment record
        
        Args:
            customer: Customer instance
            amount: Payment amount
            currency: Currency instance  
            gateway: PaymentGateway instance
            **kwargs: Additional payment fields
            
        Returns:
            Payment: Created payment instance
        """
        self.validate_workspace_access(customer)
        self.validate_workspace_access(gateway)
        
        # Generate payment number
        payment_number = self._generate_payment_number()
        
        payment = Payment.objects.create(
            workspace=self.workspace,
            customer=customer,
            payment_number=payment_number,
            gateway=gateway,
            gateway_display_name=gateway.name,
            gateway_type=gateway.gateway_type or "",
            payment_method=kwargs.get('payment_method'),
            amount=amount,
            currency=currency,
            status='pending',
            invoice=kwargs.get('invoice'),
            order=kwargs.get('order'),
        )
        return payment
    
    def _generate_payment_number(self) -> str:
        """
        Generate unique payment number
        
        Returns:
            str: Payment number
        """
        import random
        import string
        
        # Format: PAY-YYYYMMDD-XXXXX
        date_str = timezone.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.digits, k=5))
        
        payment_number = f"PAY-{date_str}-{random_str}"
        
        # Ensure uniqueness
        while Payment.objects.filter(payment_number=payment_number).exists():
            random_str = ''.join(random.choices(string.digits, k=5))
            payment_number = f"PAY-{date_str}-{random_str}"
        
        return payment_number
    
    @transaction.atomic
    def process_payment(
        self,
        payment: Payment,
        payment_details: Optional[Dict[str, Any]] = None
    ) -> Payment:
        """
        Process payment through gateway
        
        Args:
            payment: Payment instance
            payment_details: Payment details (card info, etc.)
            
        Returns:
            Payment: Updated payment instance
            
        Raises:
            PaymentFailed: If payment processing fails
        """
        self.validate_workspace_access(payment)
        if not payment.gateway:
            raise PaymentFailed(
                _("Payment gateway was removed; cannot process this payment via gateway.")
            )

        old_status = payment.status
        payment.status = 'processing'
        payment.save()

        try:
            gateway_response = self._call_payment_gateway(
                payment.gateway,
                payment,
                payment_details or {}
            )
            
            # Update payment with gateway response
            payment.gateway_transaction_id = gateway_response.get('transaction_id', '')
            payment.gateway_response = gateway_response
            payment.status = 'completed'
            payment.completed_at = timezone.now()
            payment.save()
            
            # Create transaction record
            self._create_transaction(
                payment,
                'payment',
                payment.amount,
                f"Payment {payment.payment_number}"
            )
            
            # Update related order if exists and mark as paid
            if payment.order:
                from bfg.shop.services.order_service import OrderService
                order_service = OrderService(
                    workspace=self.workspace,
                    user=self.user
                )
                order_service.mark_as_paid(payment.order)
            
            # Update related invoice if exists
            if payment.invoice:
                payment.invoice.status = 'paid'
                payment.invoice.paid_date = timezone.now().date()
                payment.invoice.save()
                
                # Update related consignment status to PAID
                self._update_consignment_status(payment.invoice, FreightState.PAID.value)
            
            # Create audit log for payment completion
            audit = AuditService(workspace=self.workspace, user=self.user)
            description = f"Payment {payment.payment_number} completed - {payment.amount} {payment.currency.code}"
            if payment.order:
                description += f" for Order #{payment.order.order_number}"
            if payment.invoice:
                description += f" for Invoice #{payment.invoice.invoice_number}"
            
            audit.log_update(
                payment,
                changes={'status': {'old': old_status, 'new': 'completed'}},
                description=description,
            )
            
            # Emit event
            self.emit_event('payment.completed', {'payment': payment})
            
            return payment
            
        except Exception as e:
            payment.status = 'failed'
            payment.gateway_response = {'error': str(e)}
            payment.save()
            
            raise PaymentFailed(f"Payment processing failed: {str(e)}")
    
    def _call_payment_gateway(
        self,
        gateway: PaymentGateway,
        payment: Payment,
        payment_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call payment gateway API using plugin system
        
        Args:
            gateway: PaymentGateway instance
            payment: Payment instance
            payment_details: Payment details (payment_intent_id, etc.)
            
        Returns:
            dict: Gateway response
        """
        # Load gateway plugin
        from bfg.finance.gateways.loader import get_gateway_plugin
        
        plugin = get_gateway_plugin(gateway)
        if not plugin:
            # Fallback for gateways without plugin implementation
            return {
                'success': True,
                'transaction_id': f"txn_{payment.id}_{timezone.now().timestamp()}",
                'message': 'Payment successful (no plugin)',
            }
        
        # Use plugin to confirm payment
        payment_intent_id = payment_details.get('payment_intent_id') or payment.gateway_transaction_id
        result = plugin.confirm_payment(
            payment,
            payment_intent_id=payment_intent_id,
            payment_details=payment_details
        )
        
        return result
    
    def _create_transaction(
        self,
        payment: Payment,
        transaction_type: str,
        amount: Decimal,
        description: str
    ) -> Transaction:
        """
        Create transaction record
        
        Args:
            payment: Payment instance
            transaction_type: Transaction type
            amount: Transaction amount
            description: Transaction description
            
        Returns:
            Transaction: Created transaction instance
        """
        transaction = Transaction.objects.create(
            workspace=self.workspace,
            customer=payment.customer,
            transaction_type=transaction_type,
            amount=amount,
            currency=payment.currency,
            payment=payment,
            invoice=payment.invoice,
            description=description,
            created_by=self.user,
        )
        
        return transaction
    
    def _update_consignment_status(self, invoice, new_state: str) -> None:
        """
        Update consignment status when invoice is paid.
        
        Args:
            invoice: Invoice instance
            new_state: New state code (PAID, PROCESSING, READY, etc.)
        """
        from bfg.delivery.models import Consignment, FreightStatus
        
        # Find consignments linked to this invoice via Order
        # Invoice -> Order -> Consignments (ManyToMany)
        consignments = []
        
        if invoice.order:
            consignments = list(invoice.order.consignments.all())
        
        if not consignments:
            return
        
        # Get the FreightStatus - should already exist from initialization
        try:
            status = FreightStatus.objects.get(
                workspace=self.workspace,
                code=new_state,
                type='consignment'
            )
        except FreightStatus.DoesNotExist:
            raise ValueError(f"FreightStatus '{new_state}' not found. Please ensure it's created during workspace initialization.")
        
        # Update all related consignments
        for consignment in consignments:
            consignment.status = status
            consignment.state = new_state
            consignment.save(update_fields=['status', 'state', 'updated_at'])
    
    @transaction.atomic
    def create_refund(
        self,
        payment: Payment,
        amount: Decimal,
        reason: str = ''
    ) -> Refund:
        """
        Create and process refund
        
        Args:
            payment: Payment instance to refund
            amount: Refund amount
            reason: Refund reason
            
        Returns:
            Refund: Created refund instance
            
        Raises:
            ValidationError: If refund amount exceeds payment amount
        """
        self.validate_workspace_access(payment)
        if not payment.gateway:
            from bfg.core.exceptions import ValidationError
            raise ValidationError(
                _("Payment gateway was removed. Refund via gateway is not available for this payment.")
            )

        # Validate refund amount
        from django.db import models
        total_refunded = payment.refunds.filter(
            status='completed'
        ).aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')
        
        if total_refunded + amount > payment.amount:
            from bfg.core.exceptions import ValidationError
            raise ValidationError(
                f"Refund amount exceeds available amount. "
                f"Payment: {payment.amount}, Already refunded: {total_refunded}"
            )
        
        # Create refund
        refund = Refund.objects.create(
            payment=payment,
            amount=amount,
            reason=reason,
            status='processing',
            created_by=self.user,
        )
        
        try:
            # Process refund through gateway
            gateway_response = self._call_refund_gateway(payment.gateway, payment, amount)
            
            refund.gateway_refund_id = gateway_response.get('refund_id', '')
            refund.status = 'completed'
            refund.completed_at = timezone.now()
            refund.save()
            
            # Create transaction record
            self._create_transaction(
                payment,
                'refund',
                -amount,  # Negative for refund
                f"Refund for {payment.payment_number}: {reason}"
            )
            
            # Update payment status if fully refunded
            if total_refunded + amount >= payment.amount:
                payment.status = 'refunded'
                payment.save()
            
            # Emit event
            self.emit_event('payment.refunded', {
                'payment': payment,
                'refund': refund
            })
            
            return refund
            
        except Exception as e:
            refund.status = 'failed'
            refund.save()
            raise PaymentFailed(f"Refund processing failed: {str(e)}")
    
    def _call_refund_gateway(
        self,
        gateway: PaymentGateway,
        payment: Payment,
        amount: Decimal
    ) -> Dict[str, Any]:
        """
        Call gateway refund API using plugin system
        
        Args:
            gateway: PaymentGateway instance
            payment: Payment instance
            amount: Refund amount
            
        Returns:
            dict: Gateway response
        """
        # Load gateway plugin
        from bfg.finance.gateways.loader import get_gateway_plugin
        
        plugin = get_gateway_plugin(gateway)
        if not plugin:
            # Fallback for gateways without plugin implementation
            return {
                'success': True,
                'refund_id': f"rfnd_{payment.id}_{timezone.now().timestamp()}",
                'message': 'Refund successful (no plugin)',
            }
        
        # Use plugin to create refund
        result = plugin.create_refund(payment, amount)
        return result
    
    def handle_webhook(
        self,
        gateway: PaymentGateway,
        event_type: str,
        payload: Dict[str, Any]
    ) -> None:
        """
        Handle webhook event from payment gateway using plugin system
        
        Args:
            gateway: PaymentGateway instance
            event_type: Event type (e.g., 'payment.succeeded', 'payment_intent.succeeded')
            payload: Webhook payload
        """
        # Load gateway plugin
        from bfg.finance.gateways.loader import get_gateway_plugin
        
        plugin = get_gateway_plugin(gateway)
        if not plugin:
            # Fallback handling for gateways without plugin
            if event_type == 'payment.succeeded':
                transaction_id = payload.get('transaction_id')
                payment = Payment.objects.filter(
                    gateway_transaction_id=transaction_id
                ).first()
                
                if payment and payment.status == 'processing':
                    old_status = payment.status
                    payment.status = 'completed'
                    payment.completed_at = timezone.now()
                    payment.save()
                    
                    # Update related order and mark as paid
                    if payment.order:
                        from bfg.shop.services.order_service import OrderService
                        order_service = OrderService(
                            workspace=self.workspace,
                            user=None  # Webhook has no user
                        )
                        order_service.mark_as_paid(payment.order)
                    
                    # Create audit log for payment completion via webhook
                    audit = AuditService(workspace=self.workspace, user=None)  # Webhook has no user
                    description = f"Payment {payment.payment_number} completed via webhook - {payment.amount} {payment.currency.code}"
                    if payment.order:
                        description += f" for Order #{payment.order.order_number}"
                    if payment.invoice:
                        description += f" for Invoice #{payment.invoice.invoice_number}"
                    
                    audit.log_update(
                        payment,
                        changes={'status': {'old': old_status, 'new': 'completed'}},
                        description=description,
                    )
                    
                    self.emit_event('payment.completed', {'payment': payment})
            return
        
        # Use plugin to handle webhook
        result = plugin.handle_webhook(event_type, payload)
        
        # Process common events based on plugin response
        if result.get('success'):
            # Extract payment intent ID from result or payload
            payment_intent_id = result.get('payment_intent_id') or payload.get('data', {}).get('object', {}).get('id')
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Webhook: Looking for payment with gateway_transaction_id={payment_intent_id}")
            
            if payment_intent_id:
                # First try with workspace filter, then without (for webhook without workspace context)
                payment = Payment.objects.filter(
                    gateway_transaction_id=payment_intent_id,
                ).first()
                
                logger.info(f"Webhook: Found payment={payment}")
                
                if payment:
                    # Update payment based on event type
                    if 'succeeded' in event_type.lower():
                        if payment.status in ['pending', 'processing']:
                            old_status = payment.status
                            payment.status = 'completed'
                            payment.completed_at = timezone.now()
                            payment.gateway_response = payload
                            payment.save()
                            
                            # Update related order and mark as paid
                            if payment.order:
                                from bfg.shop.services.order_service import OrderService
                                order_service = OrderService(
                                    workspace=self.workspace,
                                    user=None  # Webhook has no user
                                )
                                order_service.mark_as_paid(payment.order)
                            
                            # Update related invoice
                            if payment.invoice:
                                payment.invoice.status = 'paid'
                                payment.invoice.paid_date = timezone.now().date()
                                payment.invoice.save()
                            
                            # Create audit log for payment completion via webhook
                            audit = AuditService(workspace=self.workspace, user=None)  # Webhook has no user
                            description = f"Payment {payment.payment_number} completed via webhook - {payment.amount} {payment.currency.code}"
                            if payment.order:
                                description += f" for Order #{payment.order.order_number}"
                            if payment.invoice:
                                description += f" for Invoice #{payment.invoice.invoice_number}"
                            
                            audit.log_update(
                                payment,
                                changes={'status': {'old': old_status, 'new': 'completed'}},
                                description=description,
                            )
                            
                            self.emit_event('payment.completed', {'payment': payment})
                    
                    elif 'failed' in event_type.lower():
                        payment.status = 'failed'
                        payment.gateway_response = payload
                        payment.save()
                        self.emit_event('payment.failed', {'payment': payment})
