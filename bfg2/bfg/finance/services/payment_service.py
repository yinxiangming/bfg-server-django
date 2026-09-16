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
        if not gateway.is_active:
            raise PaymentFailed(_("Payment gateway is inactive."))
        amount = Decimal(str(amount))
        if amount <= 0:
            raise PaymentFailed(_("Payment amount must be greater than zero."))

        order = kwargs.get('order')
        if order is not None:
            self.validate_workspace_access(order)
            order = Order.all_objects.select_for_update().get(
                pk=order.pk,
                workspace=self.workspace,
            )
            if order.customer_id != customer.id:
                raise PaymentFailed(_("Payment customer does not own this order."))
            if amount != order.total:
                raise PaymentFailed(_("Payment amount must match the order total."))
            if order.payment_status == 'paid' or Payment.all_objects.filter(
                workspace=self.workspace,
                order=order,
                status='completed',
            ).exists():
                raise PaymentFailed(_("This order has already been paid."))
            if order.status in {'cancelled', 'refunded'}:
                raise PaymentFailed(_("A cancelled or refunded order cannot be paid."))
            if Payment.all_objects.filter(
                workspace=self.workspace,
                order=order,
                status__in=['pending', 'processing'],
            ).exists():
                raise PaymentFailed(_("This order already has an active payment attempt."))

        invoice = kwargs.get('invoice')
        if invoice is None and order is not None:
            invoice = order.invoices.order_by('-created_at').first()
        if invoice is not None:
            self.validate_workspace_access(invoice)
            invoice = invoice.__class__.all_objects.select_for_update().get(
                pk=invoice.pk,
                workspace=self.workspace,
            )
            if invoice.customer_id != customer.id:
                raise PaymentFailed(_("Payment customer does not own this invoice."))
            if amount != invoice.total:
                raise PaymentFailed(_("Payment amount must match the invoice total."))
            if order is not None and invoice.order_id != order.id:
                raise PaymentFailed(_("Payment invoice does not belong to this order."))
            if invoice.status == 'paid' or Payment.all_objects.filter(
                workspace=self.workspace,
                invoice=invoice,
                status='completed',
            ).exists():
                raise PaymentFailed(_("This invoice has already been paid."))
            if Payment.all_objects.filter(
                workspace=self.workspace,
                invoice=invoice,
                status__in=['pending', 'processing'],
            ).exists():
                raise PaymentFailed(_("This invoice already has an active payment attempt."))

        if invoice is not None:
            expected_currency = invoice.currency
        else:
            from bfg.common.constants import get_default_currency_for_workspace
            expected_code = get_default_currency_for_workspace(self.workspace)
            if currency.code != expected_code:
                raise PaymentFailed(_("Payment currency does not match the workspace order currency."))
            expected_currency = currency
        if currency.id != expected_currency.id:
            raise PaymentFailed(_("Payment currency does not match the invoice currency."))

        payment_method = kwargs.get('payment_method')
        if payment_method is not None:
            self.validate_workspace_access(payment_method)
            if payment_method.customer_id != customer.id or payment_method.gateway_id != gateway.id:
                raise PaymentFailed(_("Payment method does not belong to this customer and gateway."))
            if not payment_method.is_active:
                raise PaymentFailed(_("Payment method is inactive."))
        
        # Generate payment number
        payment_number = self._generate_payment_number()
        
        payment = Payment.objects.create(
            workspace=self.workspace,
            customer=customer,
            payment_number=payment_number,
            gateway=gateway,
            gateway_display_name=gateway.name,
            gateway_type=gateway.gateway_type or "",
            payment_method=payment_method,
            amount=amount,
            currency=currency,
            status='pending',
            invoice=invoice,
            order=order,
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
    
    def process_payment(
        self,
        payment: Payment,
        payment_details: Optional[Dict[str, Any]] = None,
        *,
        manual_confirmation: bool = False,
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
        payment_details = payment_details or {}

        with transaction.atomic():
            payment = Payment.all_objects.select_for_update().select_related(
                'gateway', 'order', 'invoice', 'currency', 'payment_method',
            ).get(pk=payment.pk, workspace=self.workspace)
            if payment.status == 'completed':
                return payment
            if self._gateway_response_succeeded(payment.gateway_response):
                stored_success = True
                old_status = payment.status
            else:
                stored_success = False
                if payment.status == 'processing' and not manual_confirmation:
                    raise PaymentFailed(
                        _("Payment processing is already in progress; reconcile it before retrying.")
                    )
                if not payment.gateway:
                    raise PaymentFailed(
                        _("Payment gateway was removed; cannot process this payment via gateway.")
                    )
                if payment.amount <= 0:
                    raise PaymentFailed(_("Payment amount must be greater than zero."))
                if payment.order and payment.amount != payment.order.total:
                    raise PaymentFailed(_("Payment amount does not match the order total."))
                if payment.invoice and payment.amount != payment.invoice.total:
                    raise PaymentFailed(_("Payment amount does not match the invoice total."))

                old_status = payment.status
                payment.status = 'processing'
                payment.save(update_fields=['status'])

        if stored_success:
            return self._finalize_confirmed_payment(payment.pk, old_status)

        try:
            if manual_confirmation:
                if payment.gateway.gateway_type not in {'bank_transfer', 'pay_in_store', 'custom'}:
                    raise PaymentFailed(_("This gateway cannot be completed manually."))
                gateway_response = {
                    'success': True,
                    'status': 'completed',
                    'transaction_id': payment_details.get('reference', ''),
                    'manual_confirmation': True,
                }
            else:
                gateway_response = self._call_payment_gateway(
                    payment.gateway,
                    payment,
                    payment_details,
                )
        except Exception as exc:
            with transaction.atomic():
                failed_payment = Payment.all_objects.select_for_update().get(
                    pk=payment.pk,
                    workspace=self.workspace,
                )
                failed_payment.status = 'failed' if manual_confirmation else 'processing'
                failed_payment.gateway_response = {
                    'error': str(exc),
                    'outcome_unknown': not manual_confirmation,
                }
                failed_payment.save(update_fields=['status', 'gateway_response'])
            raise PaymentFailed(f"Payment processing failed: {str(exc)}") from exc

        gateway_status = str(gateway_response.get('status') or '').lower()
        succeeded = self._gateway_response_succeeded(gateway_response)
        with transaction.atomic():
            persisted_payment = Payment.all_objects.select_for_update().get(
                pk=payment.pk,
                workspace=self.workspace,
            )
            persisted_payment.gateway_transaction_id = gateway_response.get('transaction_id', '')
            persisted_payment.gateway_response = gateway_response
            if succeeded:
                # Persist gateway success before local bookkeeping. A retry can safely
                # finish locally without charging the customer a second time.
                persisted_payment.status = 'processing'
            elif gateway_status in {'pending', 'processing', 'requires_action'}:
                persisted_payment.status = 'pending' if gateway_status == 'pending' else 'processing'
            else:
                persisted_payment.status = 'failed'
            persisted_payment.save(update_fields=[
                'gateway_transaction_id', 'gateway_response', 'status',
            ])

        if succeeded:
            return self._finalize_confirmed_payment(payment.pk, old_status)
        if gateway_status in {'pending', 'processing', 'requires_action'}:
            return persisted_payment
        raise PaymentFailed(
            gateway_response.get('error')
            or gateway_response.get('message')
            or _("Payment gateway did not confirm payment."),
        )

    @staticmethod
    def _gateway_response_succeeded(response: Dict[str, Any]) -> bool:
        status = str((response or {}).get('status') or '').lower()
        return (response or {}).get('success') is True and status in {
            'succeeded', 'completed', 'paid',
        }

    @transaction.atomic
    def _finalize_confirmed_payment(self, payment_id: int, old_status: str) -> Payment:
        payment = Payment.all_objects.select_for_update().select_related(
            'gateway', 'order', 'invoice', 'currency', 'payment_method',
        ).get(pk=payment_id, workspace=self.workspace)
        if payment.status == 'completed':
            return payment
        if not self._gateway_response_succeeded(payment.gateway_response):
            raise PaymentFailed(_("Payment has no persisted successful gateway response."))

        payment.status = 'completed'
        payment.completed_at = timezone.now()
        payment.save(update_fields=['status', 'completed_at'])

        self._create_transaction(
            payment,
            'payment',
            payment.amount,
            f"Payment {payment.payment_number}",
        )

        if payment.order:
            from bfg.shop.services.order_service import OrderService
            OrderService(workspace=self.workspace, user=self.user).mark_as_paid(payment.order)

        if payment.invoice:
            payment.invoice.status = 'paid'
            payment.invoice.paid_date = timezone.now().date()
            payment.invoice.save(update_fields=['status', 'paid_date', 'updated_at'])
            self._update_consignment_status(payment.invoice, FreightState.PAID.value)

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
        transaction.on_commit(
            lambda: self.emit_event('payment.completed', {'payment': payment})
        )
        return payment
    
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
            raise PaymentFailed(_("Payment gateway is not available."))
        
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
    
    def create_refund(
        self,
        payment: Payment,
        amount: Decimal,
        reason: str = '',
        *,
        idempotency_key: str,
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
        from bfg.core.exceptions import ValidationError
        from django.db import models

        self.validate_workspace_access(payment)
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError(_("Refund amount must be greater than zero."))
        idempotency_key = str(idempotency_key or '').strip()
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValidationError(_("A valid Idempotency-Key is required for refunds."))

        with transaction.atomic():
            payment = Payment.all_objects.select_for_update().select_related('gateway').get(
                pk=payment.pk,
                workspace=self.workspace,
            )
            existing_attempt = payment.refunds.select_for_update().filter(
                idempotency_key=idempotency_key,
            ).first()
            if existing_attempt and (
                existing_attempt.amount != amount or existing_attempt.reason != reason
            ):
                raise ValidationError(
                    _("This Idempotency-Key was already used with different refund details.")
                )
            if existing_attempt and existing_attempt.status in ['completed', 'pending', 'failed']:
                existing_attempt._idempotent_replay = True
                return existing_attempt

            if payment.status != 'completed':
                raise ValidationError(_("Only completed payments can be refunded."))
            if not payment.gateway:
                raise ValidationError(
                    _("Payment gateway was removed. Refund via gateway is not available for this payment.")
                )

            if existing_attempt:
                if existing_attempt.gateway_refund_id:
                    refund = existing_attempt
                    stored_success = True
                else:
                    refund = existing_attempt
                    stored_success = False
                reused_attempt = True
                refund._idempotent_replay = True
            else:
                stored_success = False
                reused_attempt = False

            total_reserved = payment.refunds.filter(
                status__in=['pending', 'processing', 'completed'],
            ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
            if not reused_attempt and total_reserved + amount > payment.amount:
                raise ValidationError(
                    f"Refund amount exceeds available amount. "
                    f"Payment: {payment.amount}, Already refunded: {total_reserved}"
                )

            if not reused_attempt:
                refund = Refund.objects.create(
                    payment=payment,
                    amount=amount,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    status='processing',
                    created_by=self.user,
                )
                refund._idempotent_replay = False

        if stored_success:
            return self._finalize_confirmed_refund(
                refund.pk,
                refund.gateway_refund_id,
            )

        try:
            gateway_response = self._call_refund_gateway(
                payment.gateway,
                payment,
                refund,
            )
        except Exception as exc:
            with transaction.atomic():
                failed_refund = Refund.objects.select_for_update().get(pk=refund.pk)
                # A transport exception does not prove the gateway rejected the
                # refund. Keep the stable idempotency attempt reserved until a
                # webhook or an operator reconciles it.
                failed_refund.status = 'processing'
                failed_refund.save(update_fields=['status'])
            raise PaymentFailed(f"Refund processing failed: {str(exc)}") from exc

        gateway_status = str(gateway_response.get('status') or '').lower()
        succeeded = gateway_response.get('success') is True and gateway_status in {
            'succeeded', 'completed', 'refunded',
        }
        if succeeded:
            gateway_refund_id = (
                gateway_response.get('refund_id')
                or f'confirmed-{refund.pk}'
            )
            with transaction.atomic():
                persisted_refund = Refund.objects.select_for_update().get(pk=refund.pk)
                persisted_refund.gateway_refund_id = gateway_refund_id
                persisted_refund.status = 'processing'
                persisted_refund.save(update_fields=['gateway_refund_id', 'status'])
            return self._finalize_confirmed_refund(
                refund.pk,
                gateway_refund_id,
            )

        with transaction.atomic():
            persisted_refund = Refund.objects.select_for_update().get(pk=refund.pk)
            persisted_refund.gateway_refund_id = gateway_response.get('refund_id', '')
            persisted_refund.status = (
                'pending'
                if gateway_response.get('success') is True and gateway_status == 'pending'
                else 'failed'
            )
            persisted_refund.save(update_fields=['gateway_refund_id', 'status'])
        if persisted_refund.status == 'pending':
            return persisted_refund
        raise PaymentFailed(
            gateway_response.get('error')
            or gateway_response.get('message')
            or _("Payment gateway did not confirm the refund."),
        )

    @transaction.atomic
    def _finalize_confirmed_refund(self, refund_id: int, gateway_refund_id: str) -> Refund:
        from django.db import models

        refund = Refund.objects.select_for_update().select_related(
            'payment__currency', 'payment__customer', 'payment__invoice',
        ).get(pk=refund_id, payment__workspace=self.workspace)
        if refund.status == 'completed':
            return refund

        payment = Payment.all_objects.select_for_update().get(pk=refund.payment_id)
        refund.gateway_refund_id = gateway_refund_id
        refund.status = 'completed'
        refund.completed_at = timezone.now()
        refund.save(update_fields=['gateway_refund_id', 'status', 'completed_at'])

        self._create_transaction(
            payment,
            'refund',
            -refund.amount,
            f"Refund #{refund.pk} for {payment.payment_number}: {refund.reason}",
        )

        completed_total = payment.refunds.filter(status='completed').aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')
        if completed_total >= payment.amount:
            payment.status = 'refunded'
            payment.save(update_fields=['status'])

        transaction.on_commit(lambda: self.emit_event('payment.refunded', {
            'payment': payment,
            'refund': refund,
        }))
        return refund
    
    def _call_refund_gateway(
        self,
        gateway: PaymentGateway,
        payment: Payment,
        refund: Refund,
    ) -> Dict[str, Any]:
        """
        Call gateway refund API using plugin system
        
        Args:
            gateway: PaymentGateway instance
            payment: Payment instance
            refund: Persisted refund attempt
            
        Returns:
            dict: Gateway response
        """
        # Load gateway plugin
        from bfg.finance.gateways.loader import get_gateway_plugin
        
        plugin = get_gateway_plugin(gateway)
        if not plugin:
            raise PaymentFailed(_("Payment gateway is not available."))
        
        # Use plugin to create refund
        result = plugin.create_refund(
            payment,
            refund.amount,
            reason=refund.reason,
            idempotency_key=f'bfg-refund-{refund.pk}',
        )
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
            # Without a plugin nothing can verify the webhook, so its body proves nothing.
            return
        
        # Use plugin to handle webhook
        result = plugin.handle_webhook(event_type, payload)
        
        # Process common events based on plugin response
        if result.get('success'):
            # Only an id the plugin read out of the verified event counts; the raw body could
            # name any payment.
            payment_intent_id = result.get('payment_intent_id')
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Webhook: Looking for payment with gateway_transaction_id={payment_intent_id}")
            
            if payment_intent_id:
                # A signature vouches for this gateway alone, so only its payments are in reach.
                payment = Payment.all_objects.filter(
                    gateway=gateway,
                    gateway_transaction_id=payment_intent_id,
                ).first()
                
                logger.info(f"Webhook: Found payment={payment}")
                
                if payment:
                    if payment.amount <= 0:
                        return
                    if payment.order and payment.amount != payment.order.total:
                        return
                    if payment.invoice and payment.amount != payment.invoice.total:
                        return
                    result_amount = result.get('amount_minor')
                    result_currency = str(result.get('currency') or '').upper()
                    if gateway.gateway_type == 'stripe' and (
                        result_amount is None or not result_currency
                    ):
                        return
                    if result_amount is not None:
                        from bfg.finance.gateways.stripe.plugin import to_minor_units
                        if int(result_amount) != to_minor_units(payment.amount, payment.currency):
                            return
                    if result_currency and result_currency != payment.currency.code.upper():
                        return

                    # Update payment based on event type
                    if 'succeeded' in event_type.lower():
                        if payment.status in ['pending', 'processing']:
                            old_status = payment.status
                            with transaction.atomic():
                                locked = Payment.all_objects.select_for_update().get(pk=payment.pk)
                                if locked.status == 'completed':
                                    return
                                locked.status = 'processing'
                                locked.gateway_response = {
                                    'success': True,
                                    'status': 'succeeded',
                                    'webhook': result,
                                }
                                locked.save(update_fields=['status', 'gateway_response'])
                            self._finalize_confirmed_payment(payment.pk, old_status)
                    
                    elif 'failed' in event_type.lower() and payment.status in ['pending', 'processing']:
                        with transaction.atomic():
                            locked = Payment.all_objects.select_for_update().get(pk=payment.pk)
                            if locked.status not in ['pending', 'processing']:
                                return
                            locked.status = 'failed'
                            locked.gateway_response = {'webhook': result, 'status': 'failed'}
                            locked.save(update_fields=['status', 'gateway_response'])
                            transaction.on_commit(
                                lambda: self.emit_event('payment.failed', {'payment': locked})
                            )
