"""
E2E Test 17.5: Storefront Me API

Test personal information API endpoints (/api/v1/me/)
Covers: user info, addresses, settings, orders, password management
"""

import pytest
from decimal import Decimal
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from tests.client import WorkspaceAPIClient
from tests.factories import StaffRoleFactory, StaffMemberFactory

User = get_user_model()


@pytest.mark.e2e
@pytest.mark.django_db
class TestStorefrontMe:
    """Test storefront personal information API"""
    
    def test_me_api(self, authenticated_client, workspace):
        """Test /api/v1/me/ API for personal information"""
        # Get current user info
        me_res = authenticated_client.get('/api/v1/me/')
        assert me_res.status_code == 200
        assert 'id' in me_res.data
        assert 'username' in me_res.data
        assert 'email' in me_res.data
        assert 'customer' in me_res.data
        
        # Update user info
        update_res = authenticated_client.patch('/api/v1/me/', {
            "first_name": "Updated",
            "last_name": "Name",
            "phone": "+1234567890"
        })
        assert update_res.status_code == 200
        assert update_res.data['first_name'] == "Updated"
        assert update_res.data['last_name'] == "Name"
        assert update_res.data['phone'] == "+1234567890"
        
        # Test change password
        # Get the user from the authenticated client
        # The authenticated_client fixture should have a user
        from tests.client import WorkspaceAPIClient
        if hasattr(authenticated_client, 'user'):
            user = authenticated_client.user
        elif hasattr(authenticated_client, '_force_user'):
            user = authenticated_client._force_user
        else:
            # Get user from the me response
            user = User.objects.get(id=me_res.data['id'])
        
        # Set initial password
        user.set_password('oldpass123')
        user.save()
        # Re-authenticate with the new password
        authenticated_client.force_authenticate(user=user)
        
        change_pwd_res = authenticated_client.post('/api/v1/me/change-password/', {
            "old_password": "oldpass123",
            "new_password": "newpass123",
            "confirm_password": "newpass123"
        })
        assert change_pwd_res.status_code == 200, f"Expected 200, got {change_pwd_res.status_code}. Response: {change_pwd_res.data}"
        assert 'detail' in change_pwd_res.data
        
        # Test reset password request
        reset_pwd_res = authenticated_client.post('/api/v1/me/reset-password/', {
            "email": user.email
        })
        assert reset_pwd_res.status_code == 200
        assert 'detail' in reset_pwd_res.data
    
    def test_address_management(self, authenticated_client, workspace):
        """Test customer address management via /api/v1/me/addresses/"""
        # Create address
        create_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "John Doe",
            "phone": "+1234567890",
            "email": "john@example.com",
            "address_line1": "123 Main Street",
            "address_line2": "Apt 4B",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US",
            "is_default": True
        })
        assert create_res.status_code == 201
        address_id = create_res.data['id']
        assert create_res.data['full_name'] == "John Doe"
        assert create_res.data['city'] == "New York"
        assert create_res.data['is_default'] is True
        
        # List addresses
        list_res = authenticated_client.get('/api/v1/me/addresses/')
        assert list_res.status_code == 200
        # Handle both paginated and non-paginated responses
        if isinstance(list_res.data, list):
            addresses = list_res.data
        else:
            addresses = list_res.data.get('results', [])
        assert len(addresses) >= 1
        
        # Get default address
        default_res = authenticated_client.get('/api/v1/me/addresses/default/')
        assert default_res.status_code == 200
        assert default_res.data['id'] == address_id
        
        # Update address
        update_res = authenticated_client.patch(f'/api/v1/me/addresses/{address_id}/', {
            "city": "Brooklyn"
        })
        assert update_res.status_code == 200
        assert update_res.data['city'] == "Brooklyn"
    
    def test_address_deletion(self, authenticated_client, workspace):
        """Test address deletion"""
        # Create multiple addresses
        addr1_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "John Doe",
            "phone": "+1234567890",
            "address_line1": "123 Main St",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US",
            "is_default": True
        })
        assert addr1_res.status_code == 201
        addr1_id = addr1_res.data['id']
        
        addr2_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "Jane Smith",
            "phone": "+0987654321",
            "address_line1": "456 Oak Ave",
            "city": "Los Angeles",
            "state": "CA",
            "postal_code": "90001",
            "country": "US",
            "is_default": False
        })
        assert addr2_res.status_code == 201
        addr2_id = addr2_res.data['id']
        
        # Test: Delete address
        delete_res = authenticated_client.delete(f'/api/v1/me/addresses/{addr2_id}/')
        assert delete_res.status_code == 204, "Delete should return 204 No Content"
        
        # Verify address is deleted
        list_res = authenticated_client.get('/api/v1/me/addresses/')
        assert list_res.status_code == 200
        addresses = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        address_ids = [addr['id'] for addr in addresses]
        assert addr2_id not in address_ids, "Deleted address should not be in list"
        assert addr1_id in address_ids, "Other address should still exist"
        
        # Test: Cannot delete non-existent address
        fake_id = 99999
        delete_fake_res = authenticated_client.delete(f'/api/v1/me/addresses/{fake_id}/')
        assert delete_fake_res.status_code == 404, "Should return 404 for non-existent address"
    
    def test_me_settings(self, authenticated_client, workspace, user):
        """Test /api/v1/me/settings/ API for user preferences"""
        # Get preferences (should auto-create if not exists)
        get_res = authenticated_client.get('/api/v1/me/settings/')
        assert get_res.status_code == 200
        assert 'email_notifications' in get_res.data
        assert 'theme' in get_res.data
        assert 'profile_visibility' in get_res.data
        
        # Update preferences
        update_res = authenticated_client.patch('/api/v1/me/settings/', {
            "email_notifications": False,
            "theme": "dark",
            "profile_visibility": "public",
            "notify_promotions": False,
            "items_per_page": 50
        })
        assert update_res.status_code == 200
        assert update_res.data['email_notifications'] is False
        assert update_res.data['theme'] == "dark"
        assert update_res.data['profile_visibility'] == "public"
        assert update_res.data['notify_promotions'] is False
        assert update_res.data['items_per_page'] == 50
        
        # Verify update persisted
        get_again_res = authenticated_client.get('/api/v1/me/settings/')
        assert get_again_res.status_code == 200
        assert get_again_res.data['theme'] == "dark"
        assert get_again_res.data['profile_visibility'] == "public"
        
        # Full update (PUT)
        put_res = authenticated_client.put('/api/v1/me/settings/', {
            "email_notifications": True,
            "sms_notifications": True,
            "push_notifications": True,
            "notify_order_updates": True,
            "notify_promotions": True,
            "notify_product_updates": True,
            "notify_support_replies": True,
            "profile_visibility": "private",
            "show_email": False,
            "show_phone": False,
            "theme": "light",
            "items_per_page": 25,
            "custom_preferences": {"preferred_currency": "USD"}
        })
        assert put_res.status_code == 200
        assert put_res.data['email_notifications'] is True
        assert put_res.data['theme'] == "light"
        assert put_res.data['custom_preferences']['preferred_currency'] == "USD"
    
    def test_me_orders(self, authenticated_client, workspace, user):
        """Test /api/v1/me/orders/ API (alias for /api/store/orders/)"""
        # Setup: Create order via checkout (similar to test_checkout_flow)
        from bfg.delivery.models import Warehouse
        from bfg.shop.models import Store
        
        warehouse = Warehouse.objects.create(
            workspace=workspace,
            name="Main Warehouse",
            code="WH-001",
            city="New York",
            country="US",
            postal_code="10001"
        )
        
        store = Store.objects.create(
            workspace=workspace,
            name="Test Store",
            code="STORE-001"
        )
        store.warehouses.add(warehouse)
        
        # Create category and product
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": "Clothing", "slug": "clothing", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": "T-Shirt", "slug": "t-shirt", "price": "25.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False
        })
        prod_id = prod_res.data['id']
        
        # Add to cart
        add_res = authenticated_client.post('/api/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 1
        })
        assert add_res.status_code == 200
        
        # Create shipping address
        addr_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "Jane Smith",
            "phone": "+1987654321",
            "address_line1": "456 Oak Avenue",
            "city": "Los Angeles",
            "state": "CA",
            "postal_code": "90001",
            "country": "US",
            "is_default": True
        })
        assert addr_res.status_code == 201
        address_id = addr_res.data['id']
        
        # Checkout
        checkout_res = authenticated_client.post('/api/store/cart/checkout/', {
            "store": store.id,
            "shipping_address": address_id
        })
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']
        
        # Test: List orders via /api/v1/me/orders/
        list_res = authenticated_client.get('/api/v1/me/orders/')
        assert list_res.status_code == 200, f"Expected 200, got {list_res.status_code}. Response: {list_res.data if hasattr(list_res, 'data') else list_res.content}"
        orders = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        assert len(orders) >= 1, f"Expected at least 1 order, got {len(orders)}. Orders: {orders}"
        order_ids = [o['id'] for o in orders]
        assert order_id in order_ids, f"Created order {order_id} should be in list {order_ids}"
        
        # Test: Get order detail via /api/v1/me/orders/{id}/
        detail_res = authenticated_client.get(f'/api/v1/me/orders/{order_id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['id'] == order_id
        assert detail_res.data['status'] == 'pending'
        
        # Test: Filter by status
        status_res = authenticated_client.get('/api/v1/me/orders/?status=pending')
        assert status_res.status_code == 200
        orders = status_res.data if isinstance(status_res.data, list) else status_res.data.get('results', [])
        for order in orders:
            assert order['status'] == 'pending'
        
        # Test: Cancel order via /api/v1/me/orders/{id}/cancel/
        cancel_res = authenticated_client.post(f'/api/v1/me/orders/{order_id}/cancel/', {
            "reason": "Changed my mind"
        })
        assert cancel_res.status_code == 200
        assert cancel_res.data['status'] == 'cancelled'
        
        # Verify cancellation via detail endpoint
        detail_after_cancel = authenticated_client.get(f'/api/v1/me/orders/{order_id}/')
        assert detail_after_cancel.status_code == 200
        assert detail_after_cancel.data['status'] == 'cancelled'
    
    def test_me_reset_password(self, authenticated_client, workspace, user):
        """Test /api/v1/me/reset-password/ API with django-allauth integration"""
        # Test password reset request
        reset_res = authenticated_client.post('/api/v1/me/reset-password/', {
            "email": user.email
        })
        assert reset_res.status_code == 200
        assert 'detail' in reset_res.data
        # Should not reveal if email exists
        assert 'password reset link' in reset_res.data['detail'].lower() or 'sent' in reset_res.data['detail'].lower()
        
        # Test with invalid email format
        invalid_res = authenticated_client.post('/api/v1/me/reset-password/', {
            "email": "not-an-email"
        })
        assert invalid_res.status_code == 400
    
    def test_me_payment_methods(self, authenticated_client, workspace, user):
        """Test /api/v1/me/payment-methods/ API for payment method management"""
        from bfg.common.models import Customer
        from bfg.finance.models import PaymentGateway, Currency
        
        # Setup: Create payment gateway and currency
        currency, _ = Currency.objects.get_or_create(
            code='USD',
            defaults={'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2, 'is_active': True}
        )
        
        gateway = PaymentGateway.objects.create(
            workspace=workspace,
            name="Test Gateway",
            gateway_type="custom",
            is_active=True
        )
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        # Test: List payment methods (initially empty)
        list_res = authenticated_client.get('/api/v1/me/payment-methods/')
        assert list_res.status_code == 200
        payment_methods = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        initial_count = len(payment_methods)
        
        # Test: Create payment method
        # Note: In MePaymentMethodViewSet, customer is automatically set, so we don't need customer_id
        create_res = authenticated_client.post('/api/v1/me/payment-methods/', {
            "gateway": gateway.id,
            "method_type": "card",
            "cardholder_name": "John Doe",
            "card_brand": "visa",  # Must be lowercase per CARD_BRAND_CHOICES
            "card_last4": "1234",
            "card_exp_month": 12,
            "card_exp_year": timezone.now().year + 1,  # Use future year to avoid validation error
            "display_info": "**** **** **** 1234",
            "is_default": True,
            "is_active": True
        })
        if create_res.status_code != 201:
            print(f"Create payment method failed: {create_res.status_code}, {create_res.data}")
        assert create_res.status_code == 201
        pm_id = create_res.data['id']
        assert create_res.data['method_type'] == "card"
        assert create_res.data['card_last4'] == "1234"
        assert create_res.data['is_default'] is True
        
        # Test: List payment methods (should have one now)
        list_res = authenticated_client.get('/api/v1/me/payment-methods/')
        assert list_res.status_code == 200
        payment_methods = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        assert len(payment_methods) == initial_count + 1
        
        # Test: Get payment method detail
        detail_res = authenticated_client.get(f'/api/v1/me/payment-methods/{pm_id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['id'] == pm_id
        assert detail_res.data['cardholder_name'] == "John Doe"
        
        # Test: Create another payment method (should not be default)
        create_res2 = authenticated_client.post('/api/v1/me/payment-methods/', {
            "gateway": gateway.id,
            "method_type": "card",
            "cardholder_name": "Jane Smith",
            "card_brand": "mastercard",  # Must be lowercase per CARD_BRAND_CHOICES
            "card_last4": "5678",
            "card_exp_month": 6,
            "card_exp_year": timezone.now().year + 1,  # Use future year
            "display_info": "**** **** **** 5678",
            "is_default": False,
            "is_active": True
        })
        assert create_res2.status_code == 201
        pm_id2 = create_res2.data['id']
        assert create_res2.data['is_default'] is False
        
        # Test: Update payment method to set as default (should unset first one)
        update_res = authenticated_client.patch(f'/api/v1/me/payment-methods/{pm_id2}/', {
            "is_default": True
        })
        assert update_res.status_code == 200
        assert update_res.data['is_default'] is True
        
        # Verify first payment method is no longer default
        detail_res = authenticated_client.get(f'/api/v1/me/payment-methods/{pm_id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['is_default'] is False
        
        # Test: Update payment method
        update_res2 = authenticated_client.patch(f'/api/v1/me/payment-methods/{pm_id}/', {
            "cardholder_name": "John Updated"
        })
        assert update_res2.status_code == 200
        assert update_res2.data['cardholder_name'] == "John Updated"
        
        # Test: Delete payment method
        delete_res = authenticated_client.delete(f'/api/v1/me/payment-methods/{pm_id}/')
        assert delete_res.status_code == 204
        
        # Verify payment method is deleted
        detail_res = authenticated_client.get(f'/api/v1/me/payment-methods/{pm_id}/')
        assert detail_res.status_code == 404
        
        # Test: Cannot delete non-existent payment method
        fake_id = 99999
        delete_fake_res = authenticated_client.delete(f'/api/v1/me/payment-methods/{fake_id}/')
        assert delete_fake_res.status_code == 404
        
        # Test: Cannot access other user's payment methods
        other_user = User.objects.create_user(
            username='otheruser2',
            email='otheruser2@test.com',
            password='testpass123'
        )
        other_client = WorkspaceAPIClient(workspace=workspace)
        other_client.force_authenticate(user=other_user)
        unauthorized_res = other_client.get(f'/api/v1/me/payment-methods/{pm_id2}/')
        # Should return 404 (not found) or 403 (forbidden) depending on implementation
        assert unauthorized_res.status_code in [403, 404]
    
    def test_me_payments(self, authenticated_client, workspace, user):
        """Test /api/v1/me/payments/ API for payment history (read-only)"""
        from bfg.common.models import Customer
        from bfg.finance.models import PaymentGateway, Payment, Currency
        from bfg.shop.models import Store, Order
        from bfg.delivery.models import Warehouse
        from django.contrib.contenttypes.models import ContentType
        from bfg.shop.services import OrderService
        
        # Setup: Create currency and gateway
        currency, _ = Currency.objects.get_or_create(
            code='USD',
            defaults={'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2, 'is_active': True}
        )
        
        gateway = PaymentGateway.objects.create(
            workspace=workspace,
            name="Test Gateway",
            gateway_type="custom",
            is_active=True
        )
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        # Create store and order for payment
        warehouse = Warehouse.objects.create(
            workspace=workspace,
            name="WH", code="WH-001", city="City", country="US", postal_code="12345"
        )
        store = Store.objects.create(workspace=workspace, name="Store", code="ST-001")
        store.warehouses.add(warehouse)
        
        customer_type = ContentType.objects.get_for_model(Customer)
        address = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "Test User",
            "phone": "1234567890",
            "address_line1": "123 St",
            "city": "City",
            "country": "US",
            "postal_code": "12345"
        }).data
        
        order_service = OrderService(workspace=workspace, user=user)
        from bfg.common.models import Address as AddressModel
        shipping_address = AddressModel.objects.get(id=address['id'])
        
        order = order_service.create_order(
            customer=customer,
            store=store,
            shipping_address=shipping_address,
            billing_address=shipping_address,
            status='pending',
            payment_status='pending'
        )
        
        # Create payments
        from bfg.finance.services import PaymentService
        payment_service = PaymentService(workspace=workspace, user=user)
        
        payment1 = payment_service.create_payment(
            customer=customer,
            amount=Decimal('100.00'),
            currency=currency,
            gateway=gateway,
            order=order
        )
        
        payment2 = payment_service.create_payment(
            customer=customer,
            amount=Decimal('50.00'),
            currency=currency,
            gateway=gateway,
            order=order
        )
        
        # Test: List payments
        list_res = authenticated_client.get('/api/v1/me/payments/')
        assert list_res.status_code == 200
        payments = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        assert len(payments) >= 2
        payment_ids = [p['id'] for p in payments]
        assert payment1.id in payment_ids
        assert payment2.id in payment_ids
        
        # Test: Get payment detail
        detail_res = authenticated_client.get(f'/api/v1/me/payments/{payment1.id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['id'] == payment1.id
        assert detail_res.data['amount'] == "100.00"
        assert detail_res.data['currency_code'] == "USD"
        
        # Test: Filter by status
        status_res = authenticated_client.get('/api/v1/me/payments/?status=pending')
        assert status_res.status_code == 200
        payments = status_res.data if isinstance(status_res.data, list) else status_res.data.get('results', [])
        for payment in payments:
            assert payment['status'] == 'pending'
        
        # Test: Cannot access other user's payments
        other_user = User.objects.create_user(
            username='otheruser3',
            email='otheruser3@test.com',
            password='testpass123'
        )
        other_client = WorkspaceAPIClient(workspace=workspace)
        other_client.force_authenticate(user=other_user)
        unauthorized_res = other_client.get(f'/api/v1/me/payments/{payment1.id}/')
        assert unauthorized_res.status_code in [403, 404]
        
        # Test: Cannot create payment via this endpoint (read-only)
        create_res = authenticated_client.post('/api/v1/me/payments/', {
            "amount": "200.00",
            "currency": currency.id,
            "gateway": gateway.id
        })
        assert create_res.status_code == 405  # Method not allowed for read-only ViewSet
    
    def test_me_invoices(self, authenticated_client, workspace, user):
        """Test /api/v1/me/invoices/ API for invoices (read-only)"""
        from decimal import Decimal
        from bfg.common.models import Customer
        from bfg.finance.models import Invoice, InvoiceItem, Currency, Brand, TaxRate, FinancialCode
        
        # Setup: Create currency
        currency, _ = Currency.objects.get_or_create(
            code='USD',
            defaults={'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2, 'is_active': True}
        )
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        # Create brand
        brand, _ = Brand.objects.get_or_create(
            workspace=workspace,
            name="Test Brand",
            defaults={'is_default': True}
        )
        
        # Create tax rate
        tax_rate, _ = TaxRate.objects.get_or_create(
            workspace=workspace,
            defaults={'rate': Decimal('15.00'), 'is_active': True}
        )
        
        # Create financial code
        financial_code, _ = FinancialCode.objects.get_or_create(
            workspace=workspace,
            code='001',
            defaults={'name': 'Service', 'tax_type': 'default', 'is_active': True}
        )
        
        # Create invoices with unique invoice numbers
        from datetime import datetime
        invoice_number1 = f'INV-TEST-{datetime.now().strftime("%Y%m%d%H%M%S")}-001'
        invoice_number2 = f'INV-TEST-{datetime.now().strftime("%Y%m%d%H%M%S")}-002'
        
        invoice1 = Invoice.objects.create(
            workspace=workspace,
            customer=customer,
            brand=brand,
            currency=currency,
            invoice_number=invoice_number1,
            status='sent',
            issue_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
            subtotal=Decimal('100.00'),
            tax=Decimal('15.00'),
            total=Decimal('115.00')
        )
        
        InvoiceItem.objects.create(
            invoice=invoice1,
            description="Test Item 1",
            quantity=Decimal('1'),
            unit_price=Decimal('100.00'),
            discount=Decimal('1.00'),
            subtotal=Decimal('100.00'),
            tax=Decimal('15.00'),
            tax_type='default',
            financial_code=financial_code
        )
        
        invoice2 = Invoice.objects.create(
            workspace=workspace,
            customer=customer,
            brand=brand,
            currency=currency,
            invoice_number=invoice_number2,
            status='paid',
            issue_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
            subtotal=Decimal('200.00'),
            tax=Decimal('30.00'),
            total=Decimal('230.00')
        )
        
        InvoiceItem.objects.create(
            invoice=invoice2,
            description="Test Item 2",
            quantity=Decimal('2'),
            unit_price=Decimal('100.00'),
            discount=Decimal('1.00'),
            subtotal=Decimal('200.00'),
            tax=Decimal('30.00'),
            tax_type='default',
            financial_code=financial_code
        )
        
        # Test: List invoices
        list_res = authenticated_client.get('/api/v1/me/invoices/')
        assert list_res.status_code == 200
        invoices = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        assert len(invoices) >= 2
        invoice_ids = [inv['id'] for inv in invoices]
        assert invoice1.id in invoice_ids
        assert invoice2.id in invoice_ids
        
        # Test: Get invoice detail (should include items)
        detail_res = authenticated_client.get(f'/api/v1/me/invoices/{invoice1.id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['id'] == invoice1.id
        assert detail_res.data['status'] == 'sent'
        assert detail_res.data['total'] == "115.00"
        assert 'items' in detail_res.data
        assert len(detail_res.data['items']) == 1
        assert detail_res.data['items'][0]['description'] == "Test Item 1"
        
        # Test: Filter by status
        status_res = authenticated_client.get('/api/v1/me/invoices/?status=paid')
        assert status_res.status_code == 200
        invoices = status_res.data if isinstance(status_res.data, list) else status_res.data.get('results', [])
        for invoice in invoices:
            assert invoice['status'] == 'paid'
        
        # Test: Cannot access other user's invoices
        other_user = User.objects.create_user(
            username='otheruser4',
            email='otheruser4@test.com',
            password='testpass123'
        )
        other_client = WorkspaceAPIClient(workspace=workspace)
        other_client.force_authenticate(user=other_user)
        unauthorized_res = other_client.get(f'/api/v1/me/invoices/{invoice1.id}/')
        assert unauthorized_res.status_code in [403, 404]
        
        # Test: Cannot create invoice via this endpoint (read-only)
        create_res = authenticated_client.post('/api/v1/me/invoices/', {
            "customer": customer.id,
            "currency": currency.id,
            "status": "draft"
        })
        assert create_res.status_code == 405  # Method not allowed for read-only ViewSet

