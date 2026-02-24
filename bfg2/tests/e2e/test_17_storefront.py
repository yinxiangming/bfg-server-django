"""
E2E Test 17: Storefront API Flow (Base)

This file has been split into multiple files for better organization:
- test_17_storefront_products.py - Product-related tests
- test_17_storefront_categories.py - Category-related tests
- test_17_storefront_cart.py - Cart-related tests
- test_17_storefront_orders.py - Order-related tests
- test_17_storefront_me.py - Personal information API tests
- test_17_storefront_payments.py - Payment-related tests

This file is kept for backward compatibility and can be removed if not needed.
"""

import pytest

# This file is intentionally minimal
# All tests have been moved to separate files for better organization

@pytest.mark.e2e
@pytest.mark.django_db
class TestStorefrontAPIBase:
    """Base test class - all tests moved to separate files"""
    pass
