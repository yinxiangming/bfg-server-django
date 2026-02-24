# -*- coding: utf-8 -*-
"""
Tests for ProductPriceService
"""

import pytest
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from bfg.shop.services.product_price_service import ProductPriceService
from bfg.shop.models import Product, ProductPriceHistory
from bfg.common.models import Workspace
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def workspace(db):
    """Create a test workspace."""
    return Workspace.objects.create(
        name="Test Workspace",
        slug="test-workspace"
    )


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123"
    )


@pytest.fixture
def product(workspace):
    """Create a test product."""
    return Product.objects.create(
        workspace=workspace,
        name="Test Product",
        slug="test-product",
        price=Decimal('100.00'),
        product_type='physical',
        language='en',
        is_active=True
    )


@pytest.fixture
def service():
    """Create ProductPriceService instance."""
    return ProductPriceService()


@pytest.mark.django_db
class TestProductPriceService:
    """Test suite for ProductPriceService."""
    
    def test_get_effective_price_no_history(self, service, product):
        """Test getting effective price when no price history exists."""
        price = service.get_effective_price(product)
        assert price == Decimal('100.00')
    
    def test_get_effective_price_with_active_history(self, service, product, user):
        """Test getting effective price with active price history."""
        # Create an active price change
        past_time = timezone.now() - timedelta(days=1)
        ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('100.00'),
            new_price=Decimal('120.00'),
            effective_at=past_time,
            changed_by=user,
            status='active'
        )
        
        price = service.get_effective_price(product)
        assert price == Decimal('120.00')
    
    def test_get_effective_price_inactive_product(self, service, product):
        """Test that inactive products raise ValueError."""
        product.is_active = False
        product.save()
        
        with pytest.raises(ValueError, match="is not active"):
            service.get_effective_price(product)
    
    def test_get_effective_price_at_specific_time(self, service, product, user):
        """Test getting price at a specific point in time."""
        # Create price history
        t1 = timezone.now() - timedelta(days=10)
        t2 = timezone.now() - timedelta(days=5)
        
        ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('100.00'),
            new_price=Decimal('110.00'),
            effective_at=t1,
            changed_by=user,
            status='active'
        )
        
        ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('110.00'),
            new_price=Decimal('120.00'),
            effective_at=t2,
            changed_by=user,
            status='active'
        )
        
        # Check price 7 days ago (should be 110)
        price_at_t = service.get_effective_price(
            product,
            at_time=timezone.now() - timedelta(days=7)
        )
        assert price_at_t == Decimal('110.00')
        
        # Check current price (should be 120)
        current_price = service.get_effective_price(product)
        assert current_price == Decimal('120.00')
    
    def test_schedule_price_change_immediate(self, service, product, user):
        """Test scheduling immediate price change."""
        now = timezone.now()
        
        history = service.schedule_price_change(
            product=product,
            new_price=Decimal('150.00'),
            effective_at=now,
            changed_by=user,
            reason="Price increase"
        )
        
        # Check history record
        assert history.status == 'active'
        assert history.new_price == Decimal('150.00')
        assert history.old_price == Decimal('100.00')
        
        # Check product was updated
        product.refresh_from_db()
        assert product.price == Decimal('150.00')
    
    def test_schedule_price_change_future(self, service, product, user):
        """Test scheduling future price change."""
        future = timezone.now() + timedelta(days=7)
        
        history = service.schedule_price_change(
            product=product,
            new_price=Decimal('200.00'),
            effective_at=future,
            changed_by=user,
            reason="Upcoming promotion"
        )
        
        # Check history record
        assert history.status == 'pending'
        assert history.new_price == Decimal('200.00')
        
        # Check product price unchanged
        product.refresh_from_db()
        assert product.price == Decimal('100.00')
    
    def test_activate_pending_price_changes(self, service, product, user):
        """Test activating pending price changes."""
        # Create a pending change that should activate
        past_time = timezone.now() - timedelta(minutes=5)
        ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('100.00'),
            new_price=Decimal('130.00'),
            effective_at=past_time,
            changed_by=user,
            status='pending'
        )
        
        # Create a future pending change that should not activate
        future_time = timezone.now() + timedelta(days=1)
        future_change = ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('130.00'),
            new_price=Decimal('140.00'),
            effective_at=future_time,
            changed_by=user,
            status='pending'
        )
        
        # Activate
        result = service.activate_pending_price_changes()
        
        # Check results
        assert result['activated_count'] == 1
        assert result['failed_count'] == 0
        
        # Check product price updated
        product.refresh_from_db()
        assert product.price == Decimal('130.00')
        
        # Check future change still pending
        future_change.refresh_from_db()
        assert future_change.status == 'pending'
    
    def test_multiple_price_changes_order(self, service, product, user):
        """Test that most recent price change is used."""
        t1 = timezone.now() - timedelta(days=3)
        t2 = timezone.now() - timedelta(days=2)
        t3 = timezone.now() - timedelta(days=1)
        
        ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('100.00'),
            new_price=Decimal('110.00'),
            effective_at=t1,
            changed_by=user,
            status='active'
        )
        
        ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('110.00'),
            new_price=Decimal('105.00'),
            effective_at=t2,
            changed_by=user,
            status='active'
        )
        
        ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=Decimal('105.00'),
            new_price=Decimal('115.00'),
            effective_at=t3,
            changed_by=user,
            status='active'
        )
        
        # Should return most recent (115)
        price = service.get_effective_price(product)
        assert price == Decimal('115.00')
