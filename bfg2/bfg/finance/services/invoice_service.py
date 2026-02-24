"""
BFG Finance Module Services

Invoice and Tax services
"""

from typing import Any, Optional, List
from decimal import Decimal
from datetime import date, timedelta
from django.db import transaction
from django.utils import timezone
from bfg.core.services import BaseService
from bfg.finance.models import (
    Invoice, InvoiceItem, TaxRate, Currency
)
from bfg.common.models import Customer
from bfg.shop.models import Order


class InvoiceService(BaseService):
    """
    Invoice management service
    
    Handles invoice creation, PDF generation, and status updates
    """
    
    @transaction.atomic
    def create_invoice_from_order(
        self,
        order: Order,
        currency: Currency,
        **kwargs: Any
    ) -> Invoice:
        """
        Create invoice from order
        
        Args:
            order: Order instance
            currency: Currency instance
            **kwargs: Additional invoice fields
            
        Returns:
            Invoice: Created invoice instance
        """
        self.validate_workspace_access(order)
        
        # Generate invoice number
        invoice_number = self._generate_invoice_number()
        
        # Calculate dates
        issue_date = kwargs.get('issue_date', timezone.now().date())
        due_date = kwargs.get('due_date', issue_date + timedelta(days=30))
        
        # Use order's subtotal, tax, and total directly
        # Order already has correct calculation: total = subtotal + shipping_cost + tax - discount
        subtotal = order.subtotal
        tax = order.tax
        total = order.total
        
        # Get or set default brand if not provided
        brand = kwargs.get('brand')
        if not brand:
            # Try to get default brand for workspace
            from bfg.finance.models import Brand
            try:
                brand = Brand.objects.get(workspace=self.workspace, is_default=True)
            except Brand.DoesNotExist:
                # No default brand, leave as None
                brand = None
        
        # Create invoice
        invoice = Invoice.objects.create(
            workspace=self.workspace,
            customer=order.customer,
            invoice_number=invoice_number,
            order=order,
            status='draft',
            subtotal=subtotal,
            tax=tax,
            total=total,
            currency=currency,
            brand=brand,
            issue_date=issue_date,
            due_date=due_date,
            notes=kwargs.get('notes', ''),
        )
        
        # Create invoice items from order items
        for order_item in order.items.all():
            InvoiceItem.objects.create(
                invoice=invoice,
                description=order_item.product.name,
                quantity=order_item.quantity,
                unit_price=order_item.price,
                subtotal=order_item.subtotal,
                product=order_item.product,
            )
        
        return invoice
    
    def _generate_invoice_number(self) -> str:
        """
        Generate unique invoice number for workspace
        
        Format: INV-XXXX (e.g., INV-0001, INV-0002, INV-0003...)
        Auto-incrementing 4-digit number.
        Users can manually change the number later if needed.
        
        Returns:
            str: Invoice number (e.g., "INV-0001")
        """
        # Get the latest invoice for this workspace
        last_invoice = Invoice.objects.filter(
            workspace=self.workspace
        ).order_by('-id').first()
        
        next_number = 1
        if last_invoice and last_invoice.invoice_number:
            # Try to extract number from last invoice_number (e.g., "INV-0001" -> 1)
            try:
                # Handle both "INV-0001" and "0001" formats
                number_part = last_invoice.invoice_number.replace('INV-', '').strip()
                if number_part.isdigit():
                    next_number = int(number_part) + 1
            except (ValueError, AttributeError):
                # If parsing fails, start from 1
                next_number = 1
        
        # Format as INV-XXXX (minimum 4 digits), e.g., INV-0001, INV-0002, ..., INV-9999, INV-10000
        invoice_number = f"INV-{str(next_number).zfill(4)}"
        
        # Ensure uniqueness (in case user manually changed a number)
        while Invoice.objects.filter(
            workspace=self.workspace,
            invoice_number=invoice_number
        ).exists():
            next_number += 1
            invoice_number = f"INV-{str(next_number).zfill(4)}"
        
        return invoice_number
    
    def _calculate_tax(
        self,
        amount: Decimal,
        address: Optional['Address'] = None
    ) -> Decimal:
        """
        Calculate tax for invoice
        
        Args:
            amount: Invoice subtotal
            address: Shipping/billing address
            
        Returns:
            Decimal: Tax amount
        """
        if not address:
            return Decimal('0')
        
        # Find applicable tax rate
        tax_rate = TaxRate.objects.filter(
            workspace=self.workspace,
            country=address.country,
            is_active=True
        ).first()
        
        if not tax_rate:
            return Decimal('0')
        
        # Calculate tax
        tax_amount = (amount * tax_rate.rate) / Decimal('100')
        return tax_amount.quantize(Decimal('0.01'))
    
    def send_invoice(self, invoice: Invoice) -> Invoice:
        """
        Mark invoice as sent
        
        Args:
            invoice: Invoice instance
            
        Returns:
            Invoice: Updated invoice instance
        """
        self.validate_workspace_access(invoice)
        
        invoice.status = 'sent'
        invoice.save()
        
        # Emit event
        self.emit_event('invoice.sent', {'invoice': invoice})
        
        return invoice
    
    def mark_as_paid(self, invoice: Invoice) -> Invoice:
        """
        Mark invoice as paid
        
        Args:
            invoice: Invoice instance
            
        Returns:
            Invoice: Updated invoice instance
        """
        self.validate_workspace_access(invoice)
        
        invoice.status = 'paid'
        invoice.paid_date = timezone.now().date()
        invoice.save()
        
        return invoice
    
    def cancel_invoice(self, invoice: Invoice, reason: str = '') -> Invoice:
        """
        Cancel invoice
        
        Args:
            invoice: Invoice instance
            reason: Cancellation reason
            
        Returns:
            Invoice: Updated invoice instance
        """
        self.validate_workspace_access(invoice)
        
        from bfg.core.exceptions import ValidationError
        if invoice.status == 'paid':
            raise ValidationError("Cannot cancel paid invoice")
        
        invoice.status = 'cancelled'
        invoice.notes = f"{invoice.notes}\n\nCancelled: {reason}"
        invoice.save()
        
        return invoice
    
    def generate_pdf(self, invoice: Invoice) -> bytes:
        """
        Generate PDF for invoice
        
        Args:
            invoice: Invoice instance
            
        Returns:
            bytes: PDF content
        """
        from bfg.core.pdf import InvoicePDFGenerator
        
        generator = InvoicePDFGenerator()
        return generator.generate_invoice(invoice)


class TaxService(BaseService):
    """
    Tax calculation service
    
    Handles tax rate management and calculations
    """
    
    @transaction.atomic
    def create_tax_rate(
        self,
        name: str,
        rate: Decimal,
        **kwargs: Any
    ) -> TaxRate:
        """
        Create tax rate
        
        Args:
            name: Tax rate name
            rate: Tax rate percentage
            **kwargs: Additional fields
            
        Returns:
            TaxRate: Created tax rate instance
        """
        tax_rate = TaxRate.objects.create(
            workspace=self.workspace,
            name=name,
            rate=rate,
            country=kwargs.get('country', ''),
            state=kwargs.get('state', ''),
            is_active=kwargs.get('is_active', True),
        )
        
        return tax_rate
    
    def calculate_tax(
        self,
        amount: Decimal,
        country: str,
        state: str = ''
    ) -> Decimal:
        """
        Calculate tax for given amount and location
        
        Args:
            amount: Amount to calculate tax for
            country: Country code
            state: State/province code
            
        Returns:
            Decimal: Tax amount
        """
        # Find most specific tax rate
        tax_rate = TaxRate.objects.filter(
            workspace=self.workspace,
            country=country,
            state=state,
            is_active=True
        ).first()
        
        if not tax_rate:
            # Try country-level rate
            tax_rate = TaxRate.objects.filter(
                workspace=self.workspace,
                country=country,
                state='',
                is_active=True
            ).first()
        
        if not tax_rate:
            return Decimal('0')
        
        tax_amount = (amount * tax_rate.rate) / Decimal('100')
        return tax_amount.quantize(Decimal('0.01'))
    
    def get_applicable_tax_rate(
        self,
        country: str,
        state: str = ''
    ) -> Optional[TaxRate]:
        """
        Get applicable tax rate for location
        
        Args:
            country: Country code
            state: State/province code
            
        Returns:
            TaxRate or None: Applicable tax rate
        """
        # Try state-specific first
        if state:
            tax_rate = TaxRate.objects.filter(
                workspace=self.workspace,
                country=country,
                state=state,
                is_active=True
            ).first()
            
            if tax_rate:
                return tax_rate
        
        # Fall back to country-level
        return TaxRate.objects.filter(
            workspace=self.workspace,
            country=country,
            state='',
            is_active=True
        ).first()
