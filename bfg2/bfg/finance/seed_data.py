# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.finance module.
"""

import os
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db import IntegrityError
from .models import (
    Currency, ExchangeRate, PaymentGateway, PaymentMethod,
    Brand, FinancialCode, Invoice, InvoiceItem, Payment, Refund, TaxRate,
    Transaction, Wallet, BillingCycle, BillingStatement
)


def clear_data():
    """Clear finance module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect cache keys before delete (this module has no cache)
    # 2. Delete in dependency order
    BillingStatement.objects.all().delete()
    BillingCycle.objects.all().delete()
    Transaction.objects.all().delete()
    Wallet.objects.all().delete()
    Refund.objects.all().delete()
    Payment.objects.all().delete()
    InvoiceItem.objects.all().delete()
    Invoice.objects.all().delete()
    FinancialCode.objects.all().delete()
    Brand.objects.all().delete()
    PaymentMethod.objects.all().delete()
    PaymentGateway.objects.all().delete()
    TaxRate.objects.all().delete()
    ExchangeRate.objects.all().delete()
    Currency.objects.all().delete()
    # 3. Invalidate caches (none for finance)


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed finance module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context (admin_user, customers, etc.)
    
    Returns:
        dict: Created data
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating finance module data...'))
    
    from bfg.common.models import Customer
    
    admin_user = context.get('admin_user')
    customers = context.get('customers', [])
    
    # Always query customers from database to ensure we get them
    if customers:
        if isinstance(customers, list):
            customer_ids = [c.id if hasattr(c, 'id') else c for c in customers]
            customers_qs = Customer.objects.filter(workspace=workspace, id__in=customer_ids)
        else:
            customers_qs = customers.filter(workspace=workspace) if hasattr(customers, 'filter') else customers
    else:
        customers_qs = Customer.objects.filter(workspace=workspace)
    
    customers_list = list(customers_qs)
    if stdout and customers_list:
        stdout.write(style.SUCCESS(f'📦 Found {len(customers_list)} customer(s) for finance module'))
    
    # Create currencies
    currencies = create_currencies(stdout, style)
    
    # Create exchange rates
    create_exchange_rates(currencies, stdout, style)
    
    # Create payment gateways
    payment_gateways = create_payment_gateways(workspace, stdout, style)
    
    # Create tax rates
    tax_rates = create_tax_rates(workspace, stdout, style)
    
    # Create brands
    brands = create_brands(workspace, stdout, style, **context)
    
    # Create financial codes
    financial_codes = create_financial_codes(workspace, stdout, style)
    
    # Create payment methods for customers
    payment_methods = create_payment_methods(customers_list, payment_gateways, stdout, style)
    
    # Create wallets for customers
    create_wallets(customers_list, currencies, stdout, style)
    
    # Get orders for invoices
    from bfg.shop.models import Order
    orders_qs = Order.objects.filter(workspace=workspace)
    orders_list = list(orders_qs[:10])
    
    if stdout:
        orders_count = len(orders_list)
        stdout.write(style.SUCCESS(f'📦 Found {orders_count} order(s) for invoice creation'))
    
    # Create invoices
    invoices = create_invoices(workspace, customers_list, orders_list, currencies, tax_rates, brands, financial_codes, stdout, style)
    
    # Create payments
    payments = create_payments(workspace, customers_list, invoices, orders_list, payment_gateways, payment_methods, currencies, stdout, style)
    
    # Create refunds
    create_refunds(payments, admin_user, stdout, style)
    
    # Create transactions
    create_transactions(workspace, customers, payments, invoices, currencies, admin_user, stdout, style)
    
    # Create billing cycles
    billing_cycles = create_billing_cycles(workspace, customers, stdout, style)
    
    # Create billing statements
    create_billing_statements(billing_cycles, stdout, style)
    
    summary = [
        {'label': 'Invoices', 'count': Invoice.objects.count()},
        {'label': 'Payments', 'count': Payment.objects.count()},
    ]
    return {
        'currencies': currencies,
        'payment_gateways': payment_gateways,
        'tax_rates': tax_rates,
        'brands': brands,
        'financial_codes': financial_codes,
        'payment_methods': payment_methods,
        'invoices': invoices,
        'payments': payments,
        'billing_cycles': billing_cycles,
        'summary': summary,
    }


def create_currencies(stdout=None, style=None):
    """Create currencies"""
    currencies_data = [
        {'code': 'USD', 'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2},
        {'code': 'EUR', 'name': 'Euro', 'symbol': '€', 'decimal_places': 2},
        {'code': 'GBP', 'name': 'British Pound', 'symbol': '£', 'decimal_places': 2},
        {'code': 'CNY', 'name': 'Chinese Yuan', 'symbol': '¥', 'decimal_places': 2},
    ]
    currencies = []
    for data in currencies_data:
        currency, created = Currency.objects.get_or_create(
            code=data['code'],
            defaults={
                'name': data['name'],
                'symbol': data['symbol'],
                'decimal_places': data['decimal_places'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created currency: {currency.code}'))
        currencies.append(currency)
    return currencies


def create_exchange_rates(currencies, stdout=None, style=None):
    """Create exchange rates"""
    if len(currencies) < 2:
        return
    
    usd = currencies[0]
    rates = []
    for currency in currencies[1:]:
        if currency.code == 'EUR':
            rate = Decimal('0.85')
        elif currency.code == 'GBP':
            rate = Decimal('0.75')
        elif currency.code == 'CNY':
            rate = Decimal('7.20')
        else:
            rate = Decimal('1.00')
        
        exchange_rate, created = ExchangeRate.objects.get_or_create(
            from_currency=usd,
            to_currency=currency,
            effective_date=timezone.now().date(),
            defaults={'rate': rate}
        )
        if created:
            rates.append(exchange_rate)
    
    if rates and stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(rates)} exchange rates'))


def create_payment_gateways(workspace, stdout=None, style=None):
    """Create payment gateways"""
    # Get Stripe configuration from environment variables
    stripe_secret_key = os.getenv('STRIPE_SECRET_KEY', '')
    stripe_publishable_key = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
    stripe_webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    
    # Determine if Stripe should be in test mode based on secret key
    stripe_is_test_mode = stripe_secret_key.startswith('sk_test_') if stripe_secret_key else True
    
    # Build Stripe config
    stripe_config = {}
    if stripe_secret_key:
        stripe_config['secret_key'] = stripe_secret_key
    if stripe_publishable_key:
        stripe_config['publishable_key'] = stripe_publishable_key
    if stripe_webhook_secret:
        stripe_config['webhook_secret'] = stripe_webhook_secret
    
    # If no Stripe config provided, use test defaults
    if not stripe_config:
        stripe_config = {'api_key': 'test_key', 'api_secret': 'test_secret'}
        if stdout:
            stdout.write(style.WARNING('⚠️  No Stripe environment variables found, using test defaults'))
    
    gateways_data = [
        {
            'name': 'Stripe',
            'gateway_type': 'stripe',
            'is_test_mode': stripe_is_test_mode,
            'config': stripe_config,
            'test_config': stripe_config,
        },
        {'name': 'PayPal', 'gateway_type': 'paypal', 'is_test_mode': True},
        {'name': 'WeChat Pay', 'gateway_type': 'wechat', 'is_test_mode': False},
    ]
    gateways = []
    for data in gateways_data:
        gateway, created = PaymentGateway.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'gateway_type': data['gateway_type'],
                'config': data.get('config', {'api_key': 'test_key', 'api_secret': 'test_secret'}),
                'is_active': True,
                'is_test_mode': data['is_test_mode'],
            }
        )
        # Update config if gateway already exists and new config is provided
        if not created and data.get('config') and gateway.gateway_type == 'stripe':
            gateway.config = data['config']
            gateway.is_test_mode = data['is_test_mode']
            gateway.save()
            if stdout:
                stdout.write(style.SUCCESS(f'↻ Updated payment gateway: {gateway.name}'))
        elif created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created payment gateway: {gateway.name}'))
        gateways.append(gateway)
    return gateways


def create_tax_rates(workspace, stdout=None, style=None):
    """Create tax rates"""
    tax_rates_data = [
        {'name': 'NZ GST', 'rate': Decimal('15.00'), 'country': 'NZ', 'state': 'NZ', 'is_active': True},
    ]
    tax_rates = []
    for data in tax_rates_data:
        tax_rate, created = TaxRate.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'rate': data['rate'],
                'country': data.get('country', ''),
                'state': data.get('state', ''),
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created tax rate: {tax_rate.name}'))
        tax_rates.append(tax_rate)
    return tax_rates


def create_brands(workspace, stdout=None, style=None, **context):
    """Create brands for workspace"""
    from bfg.common.models import Address
    from django.contrib.contenttypes.models import ContentType
    
    # Get workspace addresses or create one if needed
    workspace_content_type = ContentType.objects.get_for_model(workspace.__class__)
    workspace_addresses = Address.objects.filter(
        workspace=workspace,
        content_type=workspace_content_type
    )
    
    # If no workspace address exists, create one
    if not workspace_addresses.exists():
        workspace_address = Address.objects.create(
            workspace=workspace,
            content_type=workspace_content_type,
            object_id=workspace.id,
            full_name=workspace.name,
            phone='+1-555-0000',
            email=workspace.email or 'info@example.com',
            company=workspace.name,
            address_line1='123 Business Street',
            city='New York',
            state='NY',
            postal_code='10001',
            country='US',
            is_default=True,
        )
        workspace_addresses = [workspace_address]
    
    brands_data = [
        {
            'name': f'{workspace.name} Main',
            'address': workspace_addresses[0] if workspace_addresses else None,
            'is_default': True,
            'tax_id': 'TAX-001',
            'registration_number': 'REG-001',
        },
        {
            'name': f'{workspace.name} International',
            'address': workspace_addresses[0] if workspace_addresses else None,
            'is_default': False,
            'tax_id': 'TAX-002',
            'registration_number': 'REG-002',
        },
    ]
    
    brands = []
    for data in brands_data:
        brand, created = Brand.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'address': data['address'],
                'is_default': data['is_default'],
                'tax_id': data.get('tax_id', ''),
                'registration_number': data.get('registration_number', ''),
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created brand: {brand.name}'))
        brands.append(brand)
    
    return brands


def create_financial_codes(workspace, stdout=None, style=None):
    """Create financial codes for workspace"""
    financial_codes_data = [
        {
            'code': '001',
            'name': 'Software Service',
            'description': 'Standard software service with default tax rate',
            'tax_type': 'default',
            'is_active': True,
        },
        {
            'code': '002',
            'name': 'Overseas Software Service',
            'description': 'Overseas software service with zero GST',
            'tax_type': 'zero_gst',
            'is_active': True,
        },
        {
            'code': '003',
            'name': 'Consulting Service',
            'description': 'Consulting service with default tax rate',
            'tax_type': 'default',
            'is_active': True,
        },
        {
            'code': '004',
            'name': 'Tax-Free Product',
            'description': 'Tax-free product or service',
            'tax_type': 'no_tax',
            'is_active': True,
        },
    ]
    
    financial_codes = []
    for data in financial_codes_data:
        financial_code, created = FinancialCode.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'description': data.get('description', ''),
                'tax_type': data['tax_type'],
                'is_active': data['is_active'],
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created financial code: {financial_code.code} - {financial_code.name}'))
        financial_codes.append(financial_code)
    
    return financial_codes


def create_payment_methods(customers, payment_gateways, stdout=None, style=None):
    """Create payment methods for customers"""
    if not customers or not payment_gateways:
        return []
    
    payment_methods = []
    for i, customer in enumerate(customers[:3]):
        gateway = payment_gateways[i % len(payment_gateways)]
        method_types = ['card', 'card', 'bank']
        method_type = method_types[i % len(method_types)]
        
        display_info = f"**** **** **** {1234 + i}" if method_type == 'card' else f"Bank Account {i+1}"
        
        # Skip Stripe gateways in seed data - they require real PaymentMethod IDs
        # Stripe payment methods should be created through actual Stripe integration
        if gateway.gateway_type == 'stripe':
            if stdout:
                stdout.write(style.WARNING(f'⚠ Skipping Stripe payment method creation (requires real PaymentMethod ID)'))
            continue
        
        # For non-Stripe gateways, use test token format
        payment_method, created = PaymentMethod.objects.get_or_create(
            customer=customer,
            gateway=gateway,
            gateway_token=f'token_{customer.id}_{i}',
            defaults={
                'method_type': method_type,
                'display_info': display_info,
                'is_default': (i == 0),
                'is_active': True,
            }
        )
        if created:
            payment_methods.append(payment_method)
    
    if payment_methods and stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(payment_methods)} payment methods'))
    return payment_methods


def create_wallets(customers, currencies, stdout=None, style=None):
    """Create wallets for customers"""
    if not customers or not currencies:
        return
    
    wallets = []
    currency = currencies[0]
    for customer in customers:
        wallet, created = Wallet.objects.get_or_create(
            customer=customer,
            defaults={
                'balance': Decimal(f'{100.00 + customer.id * 10}'),
                'currency': currency,
                'credit_limit': Decimal('500.00'),
            }
        )
        if created:
            wallets.append(wallet)
    
    if wallets and stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(wallets)} wallets'))


def create_invoices(workspace, customers, orders, currencies, tax_rates, brands, financial_codes, stdout=None, style=None):
    """Create invoices"""
    from bfg.shop.models import OrderItem
    from bfg.common.models import Customer as CustomerModel
    
    if not currencies:
        if stdout:
            stdout.write(style.WARNING('⚠️  No currencies available, skipping invoice creation'))
        return []
    
    # Always query customers from database if not provided or empty
    if not customers:
        customers_qs = CustomerModel.objects.filter(workspace=workspace)
        customers = list(customers_qs)
        if stdout:
            stdout.write(style.SUCCESS(f'📦 Queried {len(customers)} customer(s) from database'))
    
    if not customers:
        if stdout:
            stdout.write(style.WARNING('⚠️  No customers available, skipping invoice creation'))
        return []
    
    invoices = []
    currency = currencies[0]
    customer_list = list(customers)[:5] if isinstance(customers, (list, tuple)) else list(customers)[:5]
    
    # Get default brand if available
    default_brand = brands[0] if brands else None
    
    # Create invoices from orders if available
    if orders:
        order_list = list(orders)[:5]
        for i, order in enumerate(order_list):
            customer = order.customer
            invoice_number = f'INV-{timezone.now().strftime("%Y%m%d")}-{i+1:04d}'
            
            subtotal = order.subtotal
            tax_rate = tax_rates[0] if tax_rates else None
            tax = subtotal * (tax_rate.rate / 100) if tax_rate else Decimal('0.00')
            total = subtotal + tax
            
            statuses = ['draft', 'sent', 'paid', 'overdue']
            status = statuses[i % len(statuses)]
            
            invoice, created = Invoice.objects.get_or_create(
                workspace=workspace,
                invoice_number=invoice_number,
                defaults={
                    'customer': customer,
                    'order': order,
                    'brand': default_brand,
                    'status': status,
                    'subtotal': subtotal,
                    'tax': tax,
                    'total': total,
                    'currency': currency,
                    'issue_date': timezone.now().date() - timedelta(days=i),
                    'due_date': timezone.now().date() + timedelta(days=30 - i),
                    'paid_date': timezone.now().date() - timedelta(days=i-2) if status == 'paid' else None,
                    'notes': f'Invoice for order {order.order_number}',
                }
            )
            if created:
                # Create invoice items from order items
                order_items = OrderItem.objects.filter(order=order)
                for j, order_item in enumerate(order_items):
                    # Assign financial code based on item index
                    financial_code = financial_codes[j % len(financial_codes)] if financial_codes else None
                    # Determine tax_type from financial_code or use default
                    tax_type = financial_code.tax_type if financial_code else 'default'
                    
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        description=f"{order_item.product.name if order_item.product else 'Item'}",
                        quantity=order_item.quantity,
                        unit_price=order_item.price,
                        subtotal=order_item.subtotal,
                        tax_type=tax_type,
                        financial_code=financial_code,
                        product=order_item.product,
                    )
                invoices.append(invoice)
                if stdout:
                    stdout.write(style.SUCCESS(f'✓ Created invoice: {invoice.invoice_number}'))
    else:
        # Create standalone invoices without orders
        if stdout:
            stdout.write(style.WARNING('⚠️  No orders available, creating standalone invoices'))
        
        for i, customer in enumerate(customer_list):
            invoice_number = f'INV-{timezone.now().strftime("%Y%m%d")}-{i+1:04d}'
            
            subtotal = Decimal('100.00') * (i + 1)
            tax_rate = tax_rates[0] if tax_rates else None
            tax = subtotal * (tax_rate.rate / 100) if tax_rate else Decimal('0.00')
            total = subtotal + tax
            
            statuses = ['draft', 'sent', 'paid', 'overdue']
            status = statuses[i % len(statuses)]
            
            invoice, created = Invoice.objects.get_or_create(
                workspace=workspace,
                invoice_number=invoice_number,
                defaults={
                    'customer': customer,
                    'order': None,
                    'brand': default_brand,
                    'status': status,
                    'subtotal': subtotal,
                    'tax': tax,
                    'total': total,
                    'currency': currency,
                    'issue_date': timezone.now().date() - timedelta(days=i),
                    'due_date': timezone.now().date() + timedelta(days=30 - i),
                    'paid_date': timezone.now().date() - timedelta(days=i-2) if status == 'paid' else None,
                    'notes': f'Standalone invoice for customer {customer}',
                }
            )
            if created:
                # Create invoice items with financial code
                financial_code = financial_codes[i % len(financial_codes)] if financial_codes else None
                tax_type = financial_code.tax_type if financial_code else 'default'
                
                InvoiceItem.objects.create(
                    invoice=invoice,
                    description='Product/Service Item',
                    quantity=1,
                    unit_price=subtotal,
                    subtotal=subtotal,
                    tax_type=tax_type,
                    financial_code=financial_code,
                )
                invoices.append(invoice)
                if stdout:
                    stdout.write(style.SUCCESS(f'✓ Created invoice: {invoice.invoice_number}'))
    
    return invoices


def create_payments(workspace, customers, invoices, orders, payment_gateways, payment_methods, currencies, stdout=None, style=None):
    """Create payments"""
    from bfg.common.models import Customer as CustomerModel
    
    if not currencies or not payment_gateways:
        if stdout:
            stdout.write(style.WARNING('⚠️  No currencies or payment gateways available, skipping payment creation'))
        return []
    
    # Always query customers from database if not provided or empty
    if not customers:
        customers_qs = CustomerModel.objects.filter(workspace=workspace)
        customers = list(customers_qs)
        if stdout:
            stdout.write(style.SUCCESS(f'📦 Queried {len(customers)} customer(s) from database for payments'))
    
    payments = []
    currency = currencies[0]
    
    # Create payments for invoices
    payment_counter = 1
    if invoices:
        paid_invoices = [inv for inv in invoices if inv.status == 'paid']
        if paid_invoices:
            for i, invoice in enumerate(paid_invoices):
                payment_number = f'PAY-{timezone.now().strftime("%Y%m%d")}-{payment_counter:04d}'
                gateway = payment_gateways[i % len(payment_gateways)]
                payment_method = payment_methods[i % len(payment_methods)] if payment_methods else None
                
                payment, created = Payment.objects.get_or_create(
                    payment_number=payment_number,
                    defaults={
                        'workspace': workspace,
                        'customer': invoice.customer,
                        'invoice': invoice,
                        'order': invoice.order,
                        'gateway': gateway,
                        'gateway_display_name': gateway.name,
                        'gateway_type': gateway.gateway_type or '',
                        'payment_method': payment_method,
                        'amount': invoice.total,
                        'currency': currency,
                        'status': 'completed',
                        'gateway_transaction_id': f'txn_{invoice.id}_{i}',
                        'completed_at': invoice.paid_date if invoice.paid_date else timezone.now() - timedelta(days=i),
                    }
                )
                if created:
                    payments.append(payment)
                    payment_counter += 1
                    if stdout:
                        stdout.write(style.SUCCESS(f'✓ Created payment: {payment.payment_number}'))
        
        # Also create payments for some non-paid invoices to have variety
        non_paid_invoices = [inv for inv in invoices if inv.status != 'paid'][:2]
        for i, invoice in enumerate(non_paid_invoices):
            payment_number = f'PAY-{timezone.now().strftime("%Y%m%d")}-{payment_counter:04d}'
            gateway = payment_gateways[(i + len(paid_invoices)) % len(payment_gateways)]
            payment_method = payment_methods[(i + len(paid_invoices)) % len(payment_methods)] if payment_methods else None
            
            payment, created = Payment.objects.get_or_create(
                payment_number=payment_number,
                defaults={
                    'workspace': workspace,
                    'customer': invoice.customer,
                    'invoice': invoice,
                    'order': invoice.order,
                    'gateway': gateway,
                    'gateway_display_name': gateway.name,
                    'gateway_type': gateway.gateway_type or '',
                    'payment_method': payment_method,
                    'amount': invoice.total,
                    'currency': currency,
                    'status': 'pending',
                    'gateway_transaction_id': f'txn_pending_{invoice.id}_{i}',
                }
            )
            if created:
                payments.append(payment)
                payment_counter += 1
                if stdout:
                    stdout.write(style.SUCCESS(f'✓ Created payment: {payment.payment_number} (pending)'))
    else:
        # Create standalone payments without invoices
        if stdout:
            stdout.write(style.WARNING('⚠️  No invoices available, creating standalone payments'))
        
        customer_list = list(customers)[:3] if customers else []
        for i, customer in enumerate(customer_list):
            payment_number = f'PAY-{timezone.now().strftime("%Y%m%d")}-{i+1:04d}'
            gateway = payment_gateways[i % len(payment_gateways)]
            payment_method = payment_methods[i % len(payment_methods)] if payment_methods else None
            
            amount = Decimal('100.00') * (i + 1)
            
            payment, created = Payment.objects.get_or_create(
                payment_number=payment_number,
                defaults={
                    'workspace': workspace,
                    'customer': customer,
                    'invoice': None,
                    'order': None,
                    'gateway': gateway,
                    'gateway_display_name': gateway.name,
                    'gateway_type': gateway.gateway_type or '',
                    'payment_method': payment_method,
                    'amount': amount,
                    'currency': currency,
                    'status': 'completed',
                    'gateway_transaction_id': f'txn_standalone_{i}',
                    'completed_at': timezone.now() - timedelta(days=i),
                }
            )
            if created:
                payments.append(payment)
                if stdout:
                    stdout.write(style.SUCCESS(f'✓ Created payment: {payment.payment_number}'))
    
    return payments


def create_refunds(payments, admin_user, stdout=None, style=None):
    """Create refunds"""
    if not payments:
        return
    
    refunds = []
    for i, payment in enumerate(payments[:3]):
        if payment.status == 'completed':
            refund, created = Refund.objects.get_or_create(
                payment=payment,
                amount=payment.amount * Decimal('0.5'),
                defaults={
                    'reason': 'Customer requested refund',
                    'status': 'completed' if i % 2 == 0 else 'pending',
                    'gateway_refund_id': f'refund_{payment.id}',
                    'completed_at': timezone.now() - timedelta(days=i) if i % 2 == 0 else None,
                    'created_by': admin_user,
                }
            )
            if created:
                refunds.append(refund)
    
    if refunds and stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(refunds)} refunds'))


def create_transactions(workspace, customers, payments, invoices, currencies, admin_user, stdout=None, style=None):
    """Create transactions"""
    if not customers or not currencies:
        return
    
    transactions = []
    currency = currencies[0]
    
    # Create transactions for payments
    for payment in payments:
        transaction, created = Transaction.objects.get_or_create(
            workspace=workspace,
            customer=payment.customer,
            payment=payment,
            defaults={
                'transaction_type': 'payment',
                'amount': payment.amount,
                'currency': currency,
                'invoice': payment.invoice,
                'description': f'Payment for {payment.invoice.invoice_number if payment.invoice else "order"}',
                'created_by': admin_user,
            }
        )
        if created:
            transactions.append(transaction)
    
    if transactions and stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(transactions)} transactions'))


def create_billing_cycles(workspace, customers, stdout=None, style=None):
    """Create billing cycles"""
    if not customers:
        return []
    
    cycles = []
    cycle_types = ['monthly', 'quarterly', 'annual']
    
    for i, customer in enumerate(customers[:3]):
        cycle_type = cycle_types[i % len(cycle_types)]
        start_date = timezone.now().date() - timedelta(days=30 * (i + 1))
        
        cycle, created = BillingCycle.objects.get_or_create(
            workspace=workspace,
            customer=customer,
            cycle_type=cycle_type,
            start_date=start_date,
            defaults={
                'end_date': start_date + timedelta(days=30 if cycle_type == 'monthly' else 90 if cycle_type == 'quarterly' else 365),
                'next_billing_date': timezone.now().date() + timedelta(days=30),
                'is_active': True,
            }
        )
        if created:
            cycles.append(cycle)
    
    if cycles and stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(cycles)} billing cycles'))
    return cycles


def create_billing_statements(billing_cycles, stdout=None, style=None):
    """Create billing statements"""
    if not billing_cycles:
        return
    
    statements = []
    for i, cycle in enumerate(billing_cycles):
        statement_number = f'STMT-{timezone.now().strftime("%Y%m%d")}-{i+1:04d}'
        
        statement, created = BillingStatement.objects.get_or_create(
            statement_number=statement_number,
            defaults={
                'billing_cycle': cycle,
                'previous_balance': Decimal('0.00'),
                'charges': Decimal(f'{100.00 + i * 20}'),
                'payments': Decimal(f'{50.00 + i * 10}'),
                'adjustments': Decimal('0.00'),
                'current_balance': Decimal(f'{50.00 + i * 10}'),
                'statement_date': timezone.now().date() - timedelta(days=i),
                'due_date': timezone.now().date() + timedelta(days=30 - i),
            }
        )
        if created:
            statements.append(statement)
    
    if statements and stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(statements)} billing statements'))

