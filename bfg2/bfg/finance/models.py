# -*- coding: utf-8 -*-
"""
Models for BFG Finance module.
Invoices, payments, billing, and wallet system.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
from decimal import Decimal


class Currency(models.Model):
    """Currency configuration."""
    code = models.CharField(_("Code"), max_length=3, unique=True)  # ISO 4217
    name = models.CharField(_("Name"), max_length=100)
    symbol = models.CharField(_("Symbol"), max_length=10)
    
    decimal_places = models.PositiveSmallIntegerField(_("Decimal Places"), default=2)
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Currency")
        verbose_name_plural = _("Currencies")
        ordering = ['code']
    
    def __str__(self):
        return f"{self.code} ({self.symbol})"


class ExchangeRate(models.Model):
    """Exchange rate between currencies."""
    from_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_from')
    to_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_to')
    
    rate = models.DecimalField(_("Rate"), max_digits=12, decimal_places=6)
    
    effective_date = models.DateField(_("Effective Date"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Exchange Rate")
        verbose_name_plural = _("Exchange Rates")
        ordering = ['-effective_date']
        unique_together = ('from_currency', 'to_currency', 'effective_date')
    
    def __str__(self):
        return f"{self.from_currency.code} → {self.to_currency.code}: {self.rate}"


class PaymentGateway(models.Model):
    """Payment gateway configuration."""
    GATEWAY_TYPE_CHOICES = (
        ('stripe', _('Stripe')),
        ('paypal', _('PayPal')),
        ('wechat', _('WeChat Pay')),
        ('alipay', _('Alipay')),
        ('bank_transfer', _('Bank Transfer')),
        ('custom', _('Custom')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='payment_gateways')
    
    name = models.CharField(_("Name"), max_length=255)
    gateway_type = models.CharField(_("Gateway Type"), max_length=20, choices=GATEWAY_TYPE_CHOICES)
    
    # Configuration
    config = models.JSONField(_("Configuration"), default=dict)
    test_config = models.JSONField(_("Test Configuration"), default=dict) # API keys, etc.
    
    is_active = models.BooleanField(_("Active"), default=True)
    is_test_mode = models.BooleanField(_("Test Mode"), default=False)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Payment Gateway")
        verbose_name_plural = _("Payment Gateways")
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({'Test' if self.is_test_mode else 'Live'})"
    
    def get_active_config(self):
        """
        Get the active configuration based on test mode
        
        Returns:
            dict: Active configuration (config or test_config)
        """
        return self.test_config if self.is_test_mode else self.config


class PaymentMethod(models.Model):
    """
    Customer saved payment method.
    
    Security Notes:
    - Never store full card numbers or CVV codes
    - Only store tokenized references from payment gateways
    - Card information is stored for display purposes only (last 4 digits, brand, etc.)
    - All sensitive operations must go through the payment gateway
    """
    METHOD_TYPE_CHOICES = (
        ('card', _('Credit/Debit Card')),
        ('bank', _('Bank Account')),
        ('wallet', _('Digital Wallet')),
    )
    
    CARD_BRAND_CHOICES = (
        ('visa', _('Visa')),
        ('mastercard', _('MasterCard')),
        ('amex', _('American Express')),
        ('discover', _('Discover')),
        ('jcb', _('JCB')),
        ('diners', _('Diners Club')),
        ('unionpay', _('UnionPay')),
        ('unknown', _('Unknown')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='payment_methods', null=True, blank=True)
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='payment_methods')
    gateway = models.ForeignKey(PaymentGateway, on_delete=models.CASCADE, related_name='payment_methods')
    
    method_type = models.CharField(_("Method Type"), max_length=20, choices=METHOD_TYPE_CHOICES)
    
    # Tokenized reference from gateway (read-only, set by gateway integration)
    gateway_token = models.CharField(_("Gateway Token"), max_length=255, help_text=_("Tokenized reference from payment gateway. Never store raw card data."))
    
    # Card display information (safe to store)
    cardholder_name = models.CharField(_("Cardholder Name"), max_length=255, blank=True, help_text=_("Name on the card"))
    card_brand = models.CharField(_("Card Brand"), max_length=20, choices=CARD_BRAND_CHOICES, blank=True, help_text=_("Card brand (Visa, MasterCard, etc.)"))
    card_last4 = models.CharField(_("Last 4 Digits"), max_length=4, blank=True, help_text=_("Last 4 digits of card number for display"))
    card_exp_month = models.PositiveSmallIntegerField(_("Expiration Month"), null=True, blank=True, help_text=_("Card expiration month (1-12)"))
    card_exp_year = models.PositiveSmallIntegerField(_("Expiration Year"), null=True, blank=True, help_text=_("Card expiration year (YYYY)"))
    
    # Legacy field for backward compatibility (deprecated, use card_exp_month/card_exp_year)
    expires_at = models.DateField(_("Expires At"), null=True, blank=True, help_text=_("Deprecated: Use card_exp_month and card_exp_year instead"))
    
    # Display info (e.g., "Visa •••• 4242")
    display_info = models.CharField(_("Display Info"), max_length=255, blank=True, help_text=_("Human-readable payment method description"))
    
    # Billing address (optional, can be linked to Address model)
    billing_address = models.ForeignKey('common.Address', on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_methods', help_text=_("Billing address for this payment method"))
    
    is_default = models.BooleanField(_("Default"), default=False, help_text=_("Set as default payment method for customer"))
    is_active = models.BooleanField(_("Active"), default=True, help_text=_("Whether this payment method is active"))
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Payment Method")
        verbose_name_plural = _("Payment Methods")
        ordering = ['-is_default', '-created_at']
        indexes = [
            models.Index(fields=['customer', 'is_active']),
            models.Index(fields=['workspace', 'customer']),
        ]
    
    def __str__(self):
        return f"{self.customer} - {self.display_info}"
    
    def clean(self):
        """Validate payment method data"""
        from django.core.exceptions import ValidationError
        
        # Validate expiration month
        if self.card_exp_month is not None:
            if not (1 <= self.card_exp_month <= 12):
                raise ValidationError({'card_exp_month': 'Expiration month must be between 1 and 12'})
        
        # Validate expiration year
        if self.card_exp_year is not None:
            current_year = timezone.now().year
            if self.card_exp_year < current_year:
                raise ValidationError({'card_exp_year': 'Expiration year cannot be in the past'})
            if self.card_exp_year > current_year + 20:
                raise ValidationError({'card_exp_year': 'Expiration year is too far in the future'})
        
        # Validate last 4 digits
        if self.card_last4:
            if not self.card_last4.isdigit() or len(self.card_last4) != 4:
                raise ValidationError({'card_last4': 'Last 4 digits must be exactly 4 numeric characters'})
    
    def save(self, *args, **kwargs):
        """Override save to run validation and auto-generate display_info"""
        # Auto-generate display_info if not provided
        if not self.display_info:
            if self.card_brand and self.card_last4:
                brand_display = self.card_brand.capitalize()
                self.display_info = f"{brand_display} •••• {self.card_last4}"
            elif self.method_type:
                self.display_info = f"{self.method_type.capitalize()} Payment Method"
            else:
                self.display_info = "Payment Method"
        
        self.full_clean()
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        """Check if card is expired"""
        if not self.card_exp_month or not self.card_exp_year:
            return False
        
        from datetime import date
        today = date.today()
        return (self.card_exp_year, self.card_exp_month) < (today.year, today.month)
    
    @property
    def expires_soon(self):
        """Check if card expires within 3 months"""
        if not self.card_exp_month or not self.card_exp_year:
            return False
        
        from datetime import date
        today = date.today()
        # Calculate 3 months later manually to avoid dateutil dependency
        three_months_later_year = today.year
        three_months_later_month = today.month + 3
        if three_months_later_month > 12:
            three_months_later_year += 1
            three_months_later_month -= 12
        three_months_later = date(three_months_later_year, three_months_later_month, 1)
        expiry_date = date(self.card_exp_year, self.card_exp_month, 1)
        return expiry_date <= three_months_later


class Brand(models.Model):
    """Brand/Business Name for Workspace."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='brands')
    
    # Brand Info
    name = models.CharField(_("Business Name"), max_length=255)
    logo = models.ImageField(_("Logo"), upload_to='brands/logos/', blank=True, null=True)
    
    # Address - using ForeignKey to Address model for flexibility
    address = models.ForeignKey('common.Address', on_delete=models.SET_NULL, null=True, blank=True, related_name='brands', verbose_name=_("Address"))
    
    # Default flag
    is_default = models.BooleanField(_("Is Default"), default=False, help_text=_("Only one brand can be default per workspace"))
    
    # Additional info
    tax_id = models.CharField(_("Tax ID"), max_length=100, blank=True, help_text=_("Business registration number or tax ID"))
    registration_number = models.CharField(_("Registration Number"), max_length=100, blank=True)
    
    # Invoice note for payment instructions
    invoice_note = models.TextField(_("Invoice Note"), blank=True, help_text=_("Payment instructions or bank details to display on invoices"))
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Brand")
        verbose_name_plural = _("Brands")
        ordering = ['-is_default', 'name']
        indexes = [
            models.Index(fields=['workspace', '-is_default']),
            models.Index(fields=['workspace', 'name']),
        ]
        constraints = [
            # Ensure only one default brand per workspace
            models.UniqueConstraint(
                fields=['workspace'],
                condition=models.Q(is_default=True),
                name='unique_default_brand_per_workspace'
            )
        ]
    
    def __str__(self):
        return f"{self.name} ({self.workspace.name})"
    
    def save(self, *args, **kwargs):
        # If setting this brand as default, unset other defaults in the same workspace
        if self.is_default:
            Brand.objects.filter(workspace=self.workspace, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class FinancialCode(models.Model):
    """Financial code for categorizing invoice items."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='financial_codes')
    
    # Code Info
    code = models.CharField(_("Code"), max_length=50, help_text=_("Financial code, e.g., '001', '002'"))
    name = models.CharField(_("Name"), max_length=255, help_text=_("Code name, e.g., 'Software Service', 'Overseas Software Service'"))
    description = models.TextField(_("Description"), blank=True, help_text=_("Detailed description of this financial code"))
    
    # Pricing
    unit_price = models.DecimalField(
        _("Unit Price"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Default unit price for items using this financial code")
    )
    unit = models.CharField(
        _("Unit"),
        max_length=50,
        blank=True,
        help_text=_("Unit of measurement, e.g., 'hour', 'day', 'piece', 'item'")
    )
    
    # Tax configuration
    tax_type = models.CharField(
        _("Tax Type"),
        max_length=20,
        choices=(
            ('default', _('Use Workspace Default Tax Rate')),
            ('no_tax', _('No Tax')),
            ('zero_gst', _('Zero Tax')),
        ),
        default='default',
        help_text=_("Tax treatment for items using this code")
    )
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Financial Code")
        verbose_name_plural = _("Financial Codes")
        ordering = ['code']
        unique_together = ('workspace', 'code')
        indexes = [
            models.Index(fields=['workspace', 'code']),
            models.Index(fields=['workspace', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.code} - {self.name}"


class Invoice(models.Model):
    """Invoice."""
    STATUS_CHOICES = (
        ('draft', _('Draft')),
        ('sent', _('Sent')),
        ('paid', _('Paid')),
        ('overdue', _('Overdue')),
        ('cancelled', _('Cancelled')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='invoices')
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT, related_name='invoices')
    
    # Invoice Info
    invoice_number = models.CharField(_("Invoice Number"), max_length=50)
    
    # Related
    order = models.ForeignKey('shop.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    subscription = models.ForeignKey('shop.Subscription', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    
    # Brand - Business Name used for this invoice
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, null=True, blank=True, related_name='invoices', verbose_name=_("Brand"), help_text=_("Business name/brand used for this invoice"))
    
    # Status
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Amounts
    subtotal = models.DecimalField(_("Subtotal"), max_digits=10, decimal_places=2)
    tax = models.DecimalField(_("Tax"), max_digits=10, decimal_places=2, default=Decimal('0'))
    total = models.DecimalField(_("Total"), max_digits=10, decimal_places=2)
    
    # Currency
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    
    # Dates
    issue_date = models.DateField(_("Issue Date"))
    due_date = models.DateField(_("Due Date"))
    paid_date = models.DateField(_("Paid Date"), null=True, blank=True)
    
    notes = models.TextField(_("Notes"), blank=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Invoice")
        verbose_name_plural = _("Invoices")
        ordering = ['-issue_date', '-created_at']
        unique_together = ('workspace', 'invoice_number')
        indexes = [
            models.Index(fields=['workspace', '-issue_date']),
            models.Index(fields=['customer', '-issue_date']),
            models.Index(fields=['invoice_number']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return self.invoice_number


class InvoiceItem(models.Model):
    """Invoice line item."""
    TAX_TYPE_CHOICES = (
        ('default', _('Use Workspace Default Tax Rate')),
        ('no_tax', _('No Tax')),
        ('zero_gst', _('Zero Tax')),
    )
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    
    description = models.CharField(_("Description"), max_length=255)
    quantity = models.DecimalField(_("Quantity"), max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(_("Unit Price"), max_digits=10, decimal_places=2)
    
    # Discount multiplier (1.00 = 100%, 0.80 = 80%)
    discount = models.DecimalField(
        _("Discount"),
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text=_("Discount multiplier (1.00 = 100%, 0.80 = 80%)")
    )
    
    subtotal = models.DecimalField(_("Subtotal"), max_digits=10, decimal_places=2)
    
    # Tax amount for this item
    tax = models.DecimalField(
        _("Tax Amount"),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_("Tax amount calculated based on tax_type and subtotal")
    )
    
    # Tax configuration
    tax_type = models.CharField(
        _("Tax Type"),
        max_length=20,
        choices=TAX_TYPE_CHOICES,
        default='default',
        help_text=_("Tax treatment for this item")
    )
    
    # Financial code
    financial_code = models.ForeignKey(
        FinancialCode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_items',
        verbose_name=_("Financial Code"),
        help_text=_("Financial code for categorizing this item")
    )
    
    # Optional product reference
    product = models.ForeignKey('shop.Product', on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = _("Invoice Item")
        verbose_name_plural = _("Invoice Items")
        indexes = [
            models.Index(fields=['invoice', 'financial_code']),
        ]
    
    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.description}"


class Payment(models.Model):
    """Payment transaction."""
    STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('completed', _('Completed')),
        ('failed', _('Failed')),
        ('refunded', _('Refunded')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='payments')
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT, related_name='payments')
    
    # Related
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    order = models.ForeignKey('shop.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    
    # Payment Info
    payment_number = models.CharField(_("Payment Number"), max_length=50, unique=True)
    
    # Gateway (nullable when gateway is deleted; use snapshot fields for display)
    gateway = models.ForeignKey(
        PaymentGateway, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments'
    )
    gateway_display_name = models.CharField(
        _("Gateway (at payment time)"), max_length=255, blank=True,
        help_text=_("Snapshot of gateway name when payment was made; kept after gateway is removed.")
    )
    gateway_type = models.CharField(
        _("Gateway type (at payment time)"), max_length=20, blank=True,
        help_text=_("Snapshot of gateway type (e.g. stripe, custom); kept after gateway is removed.")
    )
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    
    # Amount
    amount = models.DecimalField(_("Amount"), max_digits=10, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    
    # Status
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Gateway response
    gateway_transaction_id = models.CharField(_("Gateway Transaction ID"), max_length=255, blank=True)
    gateway_response = models.JSONField(_("Gateway Response"), default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    completed_at = models.DateTimeField(_("Completed At"), null=True, blank=True)
    
    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['payment_number']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.payment_number} - {self.amount} {self.currency.code}"

    def set_gateway_snapshot(self, gateway):
        """Store gateway name/type so we can display after gateway is deleted."""
        if gateway:
            self.gateway_display_name = gateway.name
            self.gateway_type = gateway.gateway_type or ""

    def get_gateway_display_name(self):
        """Display name: live gateway name, or snapshot if gateway was removed."""
        if self.gateway:
            return self.gateway.name
        return self.gateway_display_name or _("(Gateway removed)")


class Refund(models.Model):
    """Refund transaction."""
    STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('completed', _('Completed')),
        ('failed', _('Failed')),
    )
    
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='refunds')
    
    amount = models.DecimalField(_("Amount"), max_digits=10, decimal_places=2)
    reason = models.TextField(_("Reason"), blank=True)
    
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Gateway response
    gateway_refund_id = models.CharField(_("Gateway Refund ID"), max_length=255, blank=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    completed_at = models.DateTimeField(_("Completed At"), null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='refunds_created')
    
    class Meta:
        verbose_name = _("Refund")
        verbose_name_plural = _("Refunds")
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Refund {self.id} - {self.amount} {self.payment.currency.code}"


class TaxRate(models.Model):
    """Tax rate configuration."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='tax_rates')
    
    name = models.CharField(_("Name"), max_length=255)
    rate = models.DecimalField(_("Rate %"), max_digits=5, decimal_places=2)
    
    # Geographic scope
    country = models.CharField(_("Country"), max_length=2, blank=True)
    state = models.CharField(_("State/Province"), max_length=100, blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Tax Rate")
        verbose_name_plural = _("Tax Rates")
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class Transaction(models.Model):
    """Financial transaction record."""
    TRANSACTION_TYPE_CHOICES = (
        ('payment', _('Payment')),
        ('refund', _('Refund')),
        ('credit', _('Credit')),
        ('debit', _('Debit')),
        ('adjustment', _('Adjustment')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='transactions')
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT, related_name='transactions')
    
    transaction_type = models.CharField(_("Type"), max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(_("Amount"), max_digits=10, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    
    # Reference
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    
    description = models.CharField(_("Description"), max_length=255)
    notes = models.TextField(_("Notes"), blank=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='transactions_created')
    
    class Meta:
        verbose_name = _("Transaction")
        verbose_name_plural = _("Transactions")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['customer', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} {self.currency.code}"


class Wallet(models.Model):
    """Customer wallet/credit balance."""
    customer = models.OneToOneField('common.Customer', on_delete=models.CASCADE, related_name='wallet')
    
    balance = models.DecimalField(_("Balance"), max_digits=10, decimal_places=2, default=Decimal('0'))
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    
    # Limits
    credit_limit = models.DecimalField(_("Credit Limit"), max_digits=10, decimal_places=2, default=Decimal('0'))
    
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Wallet")
        verbose_name_plural = _("Wallets")
    
    def __str__(self):
        return f"{self.customer} - {self.balance} {self.currency.code}"
    
    @property
    def available_balance(self):
        """Available balance including credit."""
        return self.balance + self.credit_limit


class BillingCycle(models.Model):
    """Billing cycle for recurring billing."""
    CYCLE_TYPE_CHOICES = (
        ('monthly', _('Monthly')),
        ('quarterly', _('Quarterly')),
        ('annual', _('Annual')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='billing_cycles')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='billing_cycles')
    
    cycle_type = models.CharField(_("Cycle Type"), max_length=20, choices=CYCLE_TYPE_CHOICES, default='monthly')
    
    # Dates
    start_date = models.DateField(_("Start Date"))
    end_date = models.DateField(_("End Date"))
    next_billing_date = models.DateField(_("Next Billing Date"))
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Billing Cycle")
        verbose_name_plural = _("Billing Cycles")
        ordering = ['-start_date']
    
    def __str__(self):
        return f"{self.customer} - {self.get_cycle_type_display()}"


class BillingStatement(models.Model):
    """Billing statement."""
    billing_cycle = models.ForeignKey(BillingCycle, on_delete=models.CASCADE, related_name='statements')
    
    statement_number = models.CharField(_("Statement Number"), max_length=50, unique=True)
    
    # Amounts
    previous_balance = models.DecimalField(_("Previous Balance"), max_digits=10, decimal_places=2, default=Decimal('0'))
    charges = models.DecimalField(_("Charges"), max_digits=10, decimal_places=2, default=Decimal('0'))
    payments = models.DecimalField(_("Payments"), max_digits=10, decimal_places=2, default=Decimal('0'))
    adjustments = models.DecimalField(_("Adjustments"), max_digits=10, decimal_places=2, default=Decimal('0'))
    current_balance = models.DecimalField(_("Current Balance"), max_digits=10, decimal_places=2, default=Decimal('0'))
    
    # Dates
    statement_date = models.DateField(_("Statement Date"))
    due_date = models.DateField(_("Due Date"))
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Billing Statement")
        verbose_name_plural = _("Billing Statements")
        ordering = ['-statement_date']
    
    def __str__(self):
        return f"{self.statement_number} - {self.current_balance}"
