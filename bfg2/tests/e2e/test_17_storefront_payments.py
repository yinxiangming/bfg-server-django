"""
E2E Test 17.6: Storefront Payments API

Test payment-related storefront API endpoints
Covers: payment intent creation, payment processing, payment callbacks
"""

import pytest
from django.contrib.auth import get_user_model
from tests.client import WorkspaceAPIClient
from tests.factories import StaffRoleFactory, StaffMemberFactory

User = get_user_model()


@pytest.mark.e2e
@pytest.mark.django_db
class TestStorefrontPayments:
    """Test storefront payment-related API"""
    
    def test_payment_intent_creation(self, authenticated_client, workspace, user):
        """Test payment intent creation"""
        # Setup: Create order, currency, and gateway
        from bfg.common.models import Customer, Address
        from bfg.shop.models import Store, Order
        from bfg.delivery.models import Warehouse
        from bfg.finance.models import Currency, PaymentGateway
        from django.contrib.contenttypes.models import ContentType
        
        # Get or create currency
        currency, _ = Currency.objects.get_or_create(
            code='USD',
            defaults={'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2}
        )
        
        # Create gateway
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
        
        # Create store
        warehouse = Warehouse.objects.create(
            workspace=workspace,
            name="WH", code="WH-001", city="City", country="US", postal_code="12345"
        )
        store = Store.objects.create(workspace=workspace, name="Store", code="ST-001")
        store.warehouses.add(warehouse)
        
        # Create address
        customer_type = ContentType.objects.get_for_model(Customer)
        address = Address.objects.create(
            workspace=workspace,
            content_type=customer_type,
            object_id=customer.id,
            full_name="Test User",
            phone="1234567890",
            address_line1="123 St",
            city="City",
            country="US",
            postal_code="12345"
        )
        
        # Create order
        from bfg.shop.services import OrderService
        order_service = OrderService(workspace=workspace, user=user)
        order = order_service.create_order(
            customer=customer,
            store=store,
            shipping_address=address,
            billing_address=address,
            status='pending',
            payment_status='pending'
        )
        
        # Test: Create payment intent
        intent_res = authenticated_client.post('/api/store/payments/intent/', {
            "order_id": order.id,
            "gateway_id": gateway.id
        })
        assert intent_res.status_code == 201
        assert 'payment_id' in intent_res.data
        assert 'payment_number' in intent_res.data
        assert 'amount' in intent_res.data
        assert 'currency' in intent_res.data
        assert 'gateway_payload' in intent_res.data
        assert 'status' in intent_res.data
        assert intent_res.data['status'] == 'pending'
    
    def test_payment_processing(self, authenticated_client, workspace, user):
        """Test payment processing"""
        # Setup: Create order, currency, gateway, and payment
        from bfg.common.models import Customer, Address
        from bfg.shop.models import Store, Order
        from bfg.delivery.models import Warehouse
        from bfg.finance.models import Currency, PaymentGateway, Payment
        from django.contrib.contenttypes.models import ContentType
        
        # Get or create currency
        currency, _ = Currency.objects.get_or_create(
            code='USD',
            defaults={'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2}
        )
        
        # Create gateway
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
        
        # Create store
        warehouse = Warehouse.objects.create(
            workspace=workspace,
            name="WH", code="WH-001", city="City", country="US", postal_code="12345"
        )
        store = Store.objects.create(workspace=workspace, name="Store", code="ST-001")
        store.warehouses.add(warehouse)
        
        # Create address
        customer_type = ContentType.objects.get_for_model(Customer)
        address = Address.objects.create(
            workspace=workspace,
            content_type=customer_type,
            object_id=customer.id,
            full_name="Test User",
            phone="1234567890",
            address_line1="123 St",
            city="City",
            country="US",
            postal_code="12345"
        )
        
        # Create order
        from bfg.shop.services import OrderService
        order_service = OrderService(workspace=workspace, user=user)
        order = order_service.create_order(
            customer=customer,
            store=store,
            shipping_address=address,
            billing_address=address,
            status='pending',
            payment_status='pending'
        )
        
        # Create payment
        from bfg.finance.services import PaymentService
        payment_service = PaymentService(workspace=workspace, user=user)
        payment = payment_service.create_payment(
            customer=customer,
            amount=order.total,
            currency=currency,
            gateway=gateway,
            order=order
        )
        
        # Test: Process payment
        process_res = authenticated_client.post(f'/api/store/payments/{payment.id}/process/')
        # Payment processing may succeed or fail depending on gateway implementation
        # Just verify the endpoint is accessible and returns appropriate status
        assert process_res.status_code in [200, 400], "Payment process should return 200 or 400"
        assert 'detail' in process_res.data or 'status' in process_res.data, "Response should contain status or detail"
        
        # Test: Cannot process non-existent payment
        fake_id = 99999
        fake_process_res = authenticated_client.post(f'/api/store/payments/{fake_id}/process/')
        assert fake_process_res.status_code == 404, "Should return 404 for non-existent payment"
        
        # Test: Cannot process payment belonging to another customer
        other_user = User.objects.create_user(
            username='otheruser',
            email='otheruser@test.com',
            password='testpass123'
        )
        other_client = WorkspaceAPIClient(workspace=workspace)
        other_client.force_authenticate(user=other_user)
        unauthorized_res = other_client.post(f'/api/store/payments/{payment.id}/process/')
        assert unauthorized_res.status_code == 403, "Should return 403 for unauthorized access"
    
    def test_payment_callback(self, workspace):
        """Test payment gateway callback"""
        # Setup: Create gateway
        admin_user = User.objects.create_user(
            username='admin13',
            email='admin13@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        from bfg.finance.models import PaymentGateway
        gateway = PaymentGateway.objects.create(
            workspace=workspace,
            name="Test Gateway",
            gateway_type="custom",
            is_active=True
        )
        
        # Test: Callback endpoint is accessible (anonymous)
        # Note: Callback endpoint uses gateway_type to lookup PaymentGateway
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        callback_res = anonymous_client.post('/api/store/payments/callback/custom/')
        # Callback should return 200 (received) for valid gateway
        assert callback_res.status_code == 200, "Callback should return 200 for valid gateway"
        assert 'status' in callback_res.data, "Response should contain status"
        
        # Test: Callback with non-existent gateway
        fake_gateway_res = anonymous_client.post('/api/store/payments/callback/non-existent/')
        assert fake_gateway_res.status_code == 404, "Should return 404 for non-existent gateway"

