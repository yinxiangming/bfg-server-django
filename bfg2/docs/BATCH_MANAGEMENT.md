# BFG2 Batch Management (Optional Feature)

## How to Enable

Batch management is an advanced feature that is **disabled by default**. It's designed for scenarios requiring batch/lot tracking and expiry management (e.g., food, pharmaceuticals).

### Method 1: Enable per Workspace

```python
# Enable for specific workspace
from bfg.common.models import Workspace

workspace = Workspace.objects.get(slug='your-workspace')
workspace.settings['features'] = workspace.settings.get('features', {})
workspace.settings['features']['batch_management'] = True
workspace.save()
```

### Method 2: Enable Globally in Django Settings

```python
# settings.py
BFG2_SETTINGS = {
    'ENABLE_BATCH_MANAGEMENT': True,
}
```

---

## Database Migration

After enabling the feature, run migrations to create batch tables:

```bash
python manage.py makemigrations shop
python manage.py migrate
```

---

## Usage Examples

### 1. Create a Batch

```python
from bfg.shop.services.batch_service import BatchService
from datetime import date

service = BatchService(workspace=workspace, user=user)

batch = service.create_batch(
    variant=product_variant,
    warehouse=warehouse,
    batch_number='LOT20251123001',
    quantity=1000,
    manufactured_date=date(2025, 11, 23),
    expiry_date=date(2026, 11, 23),  # 1 year shelf life
    purchase_price=Decimal('50.00'),
)
```

### 2. FIFO Stock Allocation

```python
# Allocate stock using First-In-First-Out principle
allocations = service.allocate_stock_fifo(
    variant=product_variant,
    warehouse=warehouse,
    required_quantity=100
)

# Result: [(batch1, 50), (batch2, 50)]
# batch1 is the earliest expiring batch
```

### 3. Reserve Batch Stock

```python
# Reserve batches for an order
service.reserve_batches(allocations, order)
```

### 4. Query Expiring Batches

```python
# Get batches expiring within 7 days
expiring = service.get_expiring_batches(days_threshold=7)

for batch in expiring:
    print(f"{batch.variant.product.name}")
    print(f"  Batch: {batch.batch_number}")
    print(f"  Expires: {batch.expiry_date}")
    print(f"  Days left: {batch.days_to_expiry}")
    print(f"  Stock: {batch.available} units")
```

---

## Scheduled Tasks Configuration

### Celery Beat Configuration

```python
# tasks.py
from celery import shared_task
from bfg.shop.services.batch_service import BatchService, ExpiryNotificationService

@shared_task
def update_batch_status():
    """Update batch status daily"""
    from bfg.common.models import Workspace
    
    for workspace in Workspace.objects.filter(is_active=True):
        if workspace.settings.get('features', {}).get('batch_management'):
            service = BatchService(workspace=workspace)
            service.update_batch_status()

@shared_task
def send_expiry_notifications():
    """Send expiry warnings daily"""
    from bfg.common.models import Workspace
    
    for workspace in Workspace.objects.filter(is_active=True):
        if workspace.settings.get('features', {}).get('batch_management'):
            service = ExpiryNotificationService(workspace=workspace)
            service.send_expiry_warnings()

# Schedule configuration
from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    'update-batch-status-daily': {
        'task': 'bfg.shop.tasks.update_batch_status',
        'schedule': crontab(hour=1, minute=0),  # 1 AM daily
    },
    'send-expiry-warnings-daily': {
        'task': 'bfg.shop.tasks.send_expiry_notifications',
        'schedule': crontab(hour=9, minute=0),  # 9 AM daily
    },
}
```

---

## Model Structure

### ProductBatch

| Field | Type | Description |
|-------|------|-------------|
| batch_number | CharField | Batch number (unique) |
| manufactured_date | DateField | Manufacturing date |
| expiry_date | DateField | Expiry date (optional) |
| quantity | IntegerField | Total stock |
| reserved | IntegerField | Reserved stock |
| quality_status | CharField | Quality status (normal/warning/expired/recalled) |

**Properties:**
- `available` - Available stock (quantity - reserved)
- `days_to_expiry` - Days until expiry
- `is_near_expiry` - Near expiry (within 30 days)
- `is_expired` - Already expired

### BatchMovement

| Field | Type | Description |
|-------|------|-------------|
| batch | ForeignKey | Related batch |
| movement_type | CharField | Movement type (in/out/transfer/adjustment/return) |
| quantity | IntegerField | Quantity (positive for increase, negative for decrease) |
| order | ForeignKey | Related order |
| reason | CharField | Reason |

---

## Features

✅ **Automatic FIFO Allocation** - Prioritize selling earliest expiring batches  
✅ **Expiry Warnings** - Automatic detection and notification of expiring stock  
✅ **Batch Traceability** - Complete batch movement history  
✅ **Precise Inventory** - Batch-level inventory management  
✅ **Recall Support** - Quick location of specific batches  
✅ **Optional Enable** - Enable on-demand, doesn't affect basic functionality

---

## Important Notes

1. **Backup before enabling** - Migration creates new tables
2. **Performance impact** - Batch management adds query complexity, suitable for small-medium scale inventory
3. **Scheduled tasks** - Must configure Celery Beat to auto-update batch status
4. **Permission control** - Recommended to only allow warehouse managers to create/modify batches

---

## Disable Feature

To disable:

```python
# Disable at workspace level
workspace.settings['features']['batch_management'] = False
workspace.save()

# Or disable globally
# settings.py
BFG2_SETTINGS = {
    'ENABLE_BATCH_MANAGEMENT': False,
}
```

After disabling, batch-related features will be unavailable, but data remains in the database.
