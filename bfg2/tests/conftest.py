"""
Pytest fixtures for BFG2 tests
"""

import pytest
from decimal import Decimal
from tests.client import WorkspaceAPIClient
from tests.factories import (
    WorkspaceFactory, UserFactory, CustomerFactory,
    StoreFactory, WarehouseFactory
)

# Configure Celery for testing (EAGER mode)
@pytest.fixture(scope='session', autouse=True)
def configure_celery_for_tests():
    """Configure Celery to run tasks synchronously in tests"""
    try:
        from config.celery import app as celery_app
        from django.conf import settings
        
        # Force EAGER mode for tests
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        celery_app.conf.broker_url = 'memory://'
        celery_app.conf.result_backend = 'cache+memory://'
    except:
        pass

@pytest.fixture
def api_client():
    """DRF API Client"""
    return WorkspaceAPIClient()

@pytest.fixture
def workspace():
    """Default test workspace"""
    return WorkspaceFactory()

@pytest.fixture
def user(workspace):
    """Default test user (admin)"""
    user = UserFactory(default_workspace=workspace)
    # Create admin role and staff member
    from tests.factories import StaffRoleFactory, StaffMemberFactory
    role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
    StaffMemberFactory(workspace=workspace, user=user, role=role)
    return user

@pytest.fixture
def customer(workspace, user):
    """Default test customer"""
    return CustomerFactory(workspace=workspace, user=user)

@pytest.fixture
def authenticated_client(workspace, user, customer, message_templates):
    """Authenticated API Client with workspace and customer"""
    client = WorkspaceAPIClient(workspace=workspace)
    client.force_authenticate(user=user)
    # Attach customer to request for tests that need it
    client._customer = customer
    return client

@pytest.fixture
def warehouse(workspace):
    """Default warehouse"""
    return WarehouseFactory(workspace=workspace)

@pytest.fixture
def store(workspace, warehouse):
    """Default store"""
    return StoreFactory(workspace=workspace, warehouses=[warehouse])

@pytest.fixture
def message_templates(workspace):
    """Create default message templates for notifications"""
    from bfg.inbox.models import MessageTemplate
    
    templates_data = [
        {
            'name': 'Order Created',
            'code': 'order_created',
            'event': 'order.created',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Order Confirmation - {{ order_number }}',
            'email_body': 'Thank you for your order! Order Number: {{ order_number }}, Total: {{ total }}',
            'app_message_enabled': True,
            'app_message_title': 'Order Created',
            'app_message_body': 'Your order {{ order_number }} has been created. Total: {{ total }}',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Order Confirmed',
            'push_body': 'Order {{ order_number }} confirmed. Total: {{ total }}',
            'is_active': True,
        },
        {
            'name': 'Order Shipped',
            'code': 'order_shipped',
            'event': 'order.shipped',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Order Shipped - {{ order_number }}',
            'email_body': 'Your order {{ order_number }} has been shipped. Tracking: {{ tracking_number }}',
            'app_message_enabled': True,
            'app_message_title': 'Order Shipped',
            'app_message_body': 'Your order {{ order_number }} has been shipped.',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Order Shipped',
            'push_body': 'Order {{ order_number }} has been shipped.',
            'is_active': True,
        },
        {
            'name': 'Payment Received',
            'code': 'payment_received',
            'event': 'payment.completed',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Payment Received - {{ order_number }}',
            'email_body': 'Payment of {{ amount }} received for order {{ order_number }}',
            'app_message_enabled': True,
            'app_message_title': 'Payment Received',
            'app_message_body': 'Payment of {{ amount }} received for order {{ order_number }}',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Payment Received',
            'push_body': 'Payment received for order {{ order_number }}',
            'is_active': True,
        },
        {
            'name': 'Order Cancelled',
            'code': 'order_cancelled',
            'event': 'order.cancelled',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Order Cancelled - {{ order_number }}',
            'email_body': 'Your order {{ order_number }} has been cancelled.',
            'app_message_enabled': True,
            'app_message_title': 'Order Cancelled',
            'app_message_body': 'Your order {{ order_number }} has been cancelled.',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Order Cancelled',
            'push_body': 'Order {{ order_number }} has been cancelled.',
            'is_active': True,
        },
    ]
    
    templates = []
    for data in templates_data:
        template, _ = MessageTemplate.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            language=data['language'],
            defaults=data
        )
        templates.append(template)
    
    return templates

@pytest.fixture
def currency(db):
    """Default USD currency"""
    from bfg.finance.models import Currency
    currency, _ = Currency.objects.get_or_create(
        code='USD',
        defaults={
            'name': 'US Dollar',
            'symbol': '$',
            'decimal_places': 2
        }
    )
    return currency

@pytest.fixture
def carrier(workspace):
    """Default carrier for delivery"""
    from bfg.delivery.models import Carrier
    return Carrier.objects.create(
        workspace=workspace,
        name="Test Carrier",
        code="TC-001"
    )

@pytest.fixture
def freight_service(workspace, carrier):
    """Default freight service"""
    from bfg.delivery.models import FreightService
    return FreightService.objects.create(
        workspace=workspace,
        carrier=carrier,
        name="Standard Shipping",
        code="STD",
        base_price=Decimal('10.00')
    )

@pytest.fixture
def payment_gateway(workspace):
    """Default payment gateway"""
    from bfg.finance.models import PaymentGateway
    return PaymentGateway.objects.create(
        workspace=workspace,
        name="Test Gateway",
        gateway_type="custom",
        is_active=True
    )

@pytest.fixture
def test_address(workspace, authenticated_client):
    """Create test address via API"""
    response = authenticated_client.post('/api/common/addresses/', {
        'full_name': 'John Doe',
        'address_line1': '123 Main St',
        'city': 'Test City',
        'country': 'US',
        'postal_code': '12345'
    })
    assert response.status_code == 201
    return response.data
