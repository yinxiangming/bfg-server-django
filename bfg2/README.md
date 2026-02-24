# BFG2 - Business Foundation Generator 2

BFG2 is a comprehensive Django library for building modern websites and e-commerce platforms with built-in multi-tenancy, multi-language support, and modular architecture.

## Features

- 🌐 **Multi-site & Multi-workspace** - Host multiple websites with isolated data
- 🛍️ **E-commerce** - Complete online store with products, orders, subscriptions
- 📦 **Logistics** - Delivery management and tracking
- 💰 **Finance** - Payment processing, invoicing, wallet system
- 🎯 **Marketing** - Campaigns, coupons, referrals, affiliates
- 💬 **Support** - Ticketing system and knowledge base
- 🌍 **Multi-language** - Full i18n support with translations
- 🔐 **Authentication** - django-allauth integration with social login

## Modules

- **bfg.common** - Shared infrastructure (Workspace, User, Customer, Address)
- **bfg.web** - Website CMS with multi-site support
- **bfg.shop** - E-commerce and subscriptions
- **bfg.delivery** - Logistics and shipment tracking
- **bfg.marketing** - Marketing campaigns and promotions
- **bfg.finance** - Payment and financial management
- **bfg.support** - Customer support and ticketing

## Installation

```bash
pip install bfg2
```

## Quick Start

1. Add BFG2 apps to your `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # Django apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party
    'rest_framework',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'corsheaders',
    
    # BFG2
    'bfg.common',
    'bfg.web',
    'bfg.shop',
    'bfg.delivery',
    'bfg.marketing',
    'bfg.finance',
    'bfg.support',
]
```

2. Run migrations:

```bash
python manage.py migrate
```

3. Create a workspace and start building!

## Testing

### E2E Test Suite

BFG2 includes a comprehensive E2E test suite with **19 tests** covering the complete business workflow:

| Test Module | Tests | Coverage |
|------------|-------|----------|
| `test_01_registration.py` | 3 | Workspace, Customer, Address creation |
| `test_02_website_setup.py` | 2 | Site and Page management |
| `test_03_store_setup.py` | 2 | Warehouse and Store setup |
| `test_04_product_mgmt.py` | 2 | Product and Variant management |
| `test_05_media_upload.py` | 1 | Media upload |
| `test_06_warehouse_setup.py` | 2 | Warehouse configuration and inventory |
| `test_07_shopping_flow.py` | 2 | Cart and checkout |
| `test_08_payment_flow.py` | 2 | Payment creation and processing |
| `test_09_fulfillment.py` | 2 | Consignment creation and tracking |
| `test_10_full_workflow.py` | 1 | Complete customer journey |

**Status:** ✅ All 19 tests passing (100%)

### Run E2E Tests

```bash
# Method 1: Using the test script (recommended)
./test_e2e.sh

# Method 2: Direct command
source venv/bin/activate
python -m pytest tests/e2e/ -v

# Method 3: Quick run (quiet mode)
python -m pytest tests/e2e/ -q

# Method 4: Run specific test file
python -m pytest tests/e2e/test_01_registration.py -v

# Method 5: Run specific test
python -m pytest tests/e2e/test_04_product_mgmt.py::TestProductManagement::test_product_creation -vv

# Method 6: Run with debug output
python -m pytest tests/e2e/ -vv -s

# Method 7: Stop at first failure
python -m pytest tests/e2e/ -x
```

### Test Features

- ✅ **Complete workflow coverage** - From registration to fulfillment
- ✅ **In-memory database** - Fast, isolated test runs
- ✅ **Factory-based fixtures** - Consistent test data
- ✅ **API testing** - Full REST API validation
- ✅ **Multi-workspace aware** - Tests workspace isolation

All tests use an in-memory SQLite database and run automatically with migrations applied.

## Documentation

Full documentation available at `docs/`

## Requirements

- Python >= 3.11
- Django >= 5.0
- MySQL or PostgreSQL

## License

MIT License
