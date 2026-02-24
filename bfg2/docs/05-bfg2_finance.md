# BFG2_FINANCE Module - Financial Management

## Overview

The `bfg2_finance` module handles invoicing, payments, payment gateways, and financial transactions. It supports multiple payment methods and currencies.

## Features

- 💰 **Invoice Management** - Generate and track invoices
- 💳 **Payment Processing** - Multi-gateway payment support
- 🏦 **Payment Gateways** - WeChat Pay, Alipay, Stripe, etc.
- 💵 **Multi-currency** - Support for international transactions
- 📊 **Transaction Tracking** - Complete financial audit trail
- 🔄 **Refunds** - Process refunds and credits
- 💸 **Wallet System** - Customer balance and credits
- 📈 **Tax Management** - Tax calculation and reporting

## Models

### Invoice

**Purpose**: Bill for services or products.

**Migrated from**: `freight/models/finance.py`

```python
class Invoice(models.Model):
    """
    Invoice for services or products.
    """
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('partially_paid', 'Partially Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT)
    
    # Identification
    reference_number = models.CharField(max_length=100, unique=True)
    invoice_number = models.CharField(max_length=100)  # Display number
    
    # Financial
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='NZD')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Dates
    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Links
    order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    consignment = models.ForeignKey('bfg2_delivery.Consignment', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    
    # PDF
    pdf_file = models.FileField(upload_to='invoices/%Y/%m/', blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `reference_number`, `invoice_number`, `workspace + customer`, `status`, `due_date`

---

### Wallet

**Purpose**: Customer wallet/balance for credits and prepaid amounts.

```python
class Wallet(models.Model):
    """
    Customer wallet with balance tracking.
    """
    customer = models.OneToOneField('common.Customer', on_delete=models.CASCADE, related_name='wallet')
    
    # Balance
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='NZD')
    
    # Limits
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### InvoiceItem

**Purpose**: Line items on an invoice.

```python
class InvoiceItem(models.Model):
    """
    Invoice line item.
    """
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Optional product link
    product = models.ForeignKey('bfg2_shop.Product', on_delete=models.SET_NULL, null=True, blank=True)
    
    order = models.IntegerField(default=0)
```

---

### Payment

**Purpose**: Payment records.

**Migrated from**: `freight/models/finance.py`

```python
class Payment(models.Model):
    """
    Payment record.
    """
    METHOD_CHOICES = (
        ('wechat', 'WeChat Pay'),
        ('alipay', 'Alipay'),
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
        ('bank', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('wallet', 'Wallet Balance'),
        ('other', 'Other'),
    )
    
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT)
    
    # Amount
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='NZD')
    
    # Exchange (if paid in different currency)
    original_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    original_currency = models.CharField(max_length=3, blank=True)
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    # Method & Gateway
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    gateway = models.ForeignKey('PaymentGateway', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # External reference
    transaction_id = models.CharField(max_length=100, blank=True)  # Gateway transaction ID
    authorization_code = models.CharField(max_length=100, blank=True)
    
    # Linked records
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Proof (for manual methods)
    proof_file = models.FileField(upload_to='payments/proofs/', blank=True)
    
    # Gateway response
    gateway_response = models.JSONField(default=dict, blank=True)
    
    # Dates
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `transaction_id`, `workspace + customer`, `status`, `method`

---

### PaymentGateway

**Purpose**: Payment gateway configuration.

```python
class PaymentGateway(models.Model):
    """
    Payment gateway configuration.
    """
    GATEWAY_TYPE_CHOICES = (
        ('wechat', 'WeChat Pay'),
        ('alipay', 'Alipay'),
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
        ('square', 'Square'),
        ('custom', 'Custom'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Gateway info
    name = models.CharField(max_length=100)
    gateway_type = models.CharField(max_length=20, choices=GATEWAY_TYPE_CHOICES)
    
    # Configuration (API keys, secrets, etc.)
    config = models.JSONField(default=dict)
    # Example for Stripe:
    # {
    #   "public_key": "pk_test_...",
    #   "secret_key": "sk_test_...",
    #   "webhook_secret": "whsec_..."
    # }
    
    # Supported currencies
    supported_currencies = models.JSONField(default=list)  # ['USD', 'NZD', 'CNY']
    
    # Fees
    transaction_fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    transaction_fee_fixed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Display
    logo = models.ImageField(upload_to='gateways/', blank=True)
    order = models.IntegerField(default=0)
    
    # Settings
    is_active = models.BooleanField(default=True)
    is_test_mode = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### Transaction

**Purpose**: Wallet transaction history.

**Migrated from**: `freight/models/finance.py`

```python
class Transaction(models.Model):
    """
    Wallet transaction (credits, debits, adjustments).
    """
    TYPE_CHOICES = (
        ('deposit', 'Deposit'),
        ('withdraw', 'Withdrawal'),
        ('payment', 'Payment'),
        ('refund', 'Refund'),
        ('adjustment', 'Adjustment'),
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE)
    
    # Amount
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_before = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Type
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    description = models.CharField(max_length=255, blank=True)
    
    # Reference
    reference = models.CharField(max_length=100, blank=True)
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)
    order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    
    created_by = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
```

---

### Refund

**Purpose**: Refund processing.

```python
class Refund(models.Model):
    """
    Refund record.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    )
    
    REASON_CHOICES = (
        ('customer_request', 'Customer Request'),
        ('defective', 'Defective Product'),
        ('wrong_item', 'Wrong Item'),
        ('not_received', 'Not Received'),
        ('other', 'Other'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT)
    
    # Original payment
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='refunds')
    order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Refund amount
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='NZD')
    
    # Reason
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    notes = models.TextField(blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Processing
    refund_method = models.CharField(max_length=20)  # Same as payment method or wallet
    transaction_id = models.CharField(max_length=100, blank=True)
    
    # Dates
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### TaxRate

**Purpose**: Tax rate configuration.

```python
class TaxRate(models.Model):
    """
    Tax rate configuration.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)  # e.g., "GST", "VAT", "Sales Tax"
    rate = models.DecimalField(max_digits=5, decimal_places=2)  # Percentage
    
    # Geographic applicability
    country = models.CharField(max_length=2, blank=True)  # ISO code
    state = models.CharField(max_length=100, blank=True)
    postal_codes = models.JSONField(default=list, blank=True)
    
    # Product applicability
    applies_to_all = models.BooleanField(default=True)
    product_categories = models.ManyToManyField('bfg2_shop.ProductCategory', blank=True)
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### Currency

**Purpose**: Currency configuration.

```python
class Currency(models.Model):
    """
    Currency configuration with exchange rates.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Currency
    code = models.CharField(max_length=3)  # ISO code: USD, NZD, CNY
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10)
    
    # Exchange rate (relative to base currency)
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, default=1)
    
    # Display
    decimal_places = models.IntegerField(default=2)
    thousand_separator = models.CharField(max_length=1, default=',')
    decimal_separator = models.CharField(max_length=1, default='.')
    
    is_active = models.BooleanField(default=True)
    is_base = models.BooleanField(default=False)  # Base currency for workspace
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### ExchangeRate

**Purpose**: Historical exchange rate tracking.

```python
class ExchangeRate(models.Model):
    """
    Historical exchange rates.
    """
    from_currency = models.ForeignKey(Currency, related_name='rates_from', on_delete=models.CASCADE)
    to_currency = models.ForeignKey(Currency, related_name='rates_to', on_delete=models.CASCADE)
    
    rate = models.DecimalField(max_digits=12, decimal_places=6)
    
    # Source
    source = models.CharField(max_length=50, default='manual')  # 'manual', 'api', 'bank'
    
    effective_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('from_currency', 'to_currency', 'effective_date')
```

---

### PaymentMethod

**Purpose**: Saved customer payment methods.

```python
class PaymentMethod(models.Model):
    """
    Customer's saved payment method.
    """
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='payment_methods')
    
    # Method type
    method_type = models.CharField(max_length=20)  # 'card', 'bank_account', 'wallet'
    
    # Card details (encrypted/tokenized)
    card_last4 = models.CharField(max_length=4, blank=True)
    card_brand = models.CharField(max_length=20, blank=True)  # 'visa', 'mastercard'
    card_exp_month = models.IntegerField(null=True, blank=True)
    card_exp_year = models.IntegerField(null=True, blank=True)
    
    # Gateway token
    gateway = models.ForeignKey(PaymentGateway, on_delete=models.CASCADE)
    gateway_token = models.CharField(max_length=255)  # Tokenized by gateway
    
    # Settings
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## API Endpoints

### Invoices
- `GET /api/finance/invoices/` - List customer invoices
- `GET /api/finance/invoices/{reference}/` - Get invoice details
- `GET /api/finance/invoices/{id}/pdf/` - Download invoice PDF
- `POST /api/finance/invoices/` - Create invoice (admin)

### Payments
- `POST /api/finance/payments/create/` - Create payment intent
- `POST /api/finance/payments/{id}/confirm/` - Confirm payment
- `GET /api/finance/payments/` - List customer payments
- `POST /api/finance/payments/webhook/` - Gateway webhook handler

### Payment Gateways
- `GET /api/finance/gateways/` - List available gateways
- `POST /api/finance/gateways/{id}/config/` - Configure gateway (admin)

### Wallet & Transactions
- `GET /api/finance/wallet/balance/` - Get wallet balance
- `GET /api/finance/transactions/` - List transactions
- `POST /api/finance/wallet/topup/` - Top up wallet

### Refunds
- `POST /api/finance/refunds/request/` - Request refund
- `GET /api/finance/refunds/` - List customer refunds

## Integration with Other Modules

- **bfg2_shop**: Order payment and invoicing
- **bfg2_delivery**: Shipping cost invoicing
- **bfg2_promo**: Affiliate commission payments
