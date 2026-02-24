# BFG2_DELIVERY Module - Delivery & Logistics

## Overview

The `bfg2_delivery` module handles shipment tracking, delivery management, and logistics operations. It migrates core models from the existing `freight` app.

## Features

- 📦 **Shipment Tracking** - Real-time package tracking
- 🚚 **Carrier Management** - Multiple delivery carriers
- 🏭 **Warehouse Management** - Inventory locations
- 📊 **Manifest Management** - Shipping batches and master waybills
- 🌍 **Delivery Zones** - Geographic delivery areas
- 📍 **Route Optimization** - Delivery route planning
- 🔔 **Notifications** - Real-time delivery updates

## Models

### Warehouse

**Purpose**: Physical warehouse locations for inventory management.

**Migrated from**: `freight/models/freight.py`

```python
class Warehouse(models.Model):
    """
    Warehouse location.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Basic Info
    title = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='local')
    
    # Location
    address = models.TextField(blank=True)
    country = models.CharField(max_length=2)  # ISO country code
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    
    # Contact
    contact = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    
    # Capacity
    space_capacity = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # m3
    current_usage = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    
    # Settings
    is_active = models.BooleanField(default=True)
    accepts_international = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `workspace + code`, `country + city`

---

### Carrier

**Purpose**: Delivery carrier/courier companies.

```python
class Carrier(models.Model):
    """
    Delivery carrier (e.g., DHL, FedEx, UPS).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Basic Info
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    
    # Contact
    website = models.URLField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    
    # API Integration
    api_enabled = models.BooleanField(default=False)
    api_config = models.JSONField(default=dict, blank=True)  # API credentials, endpoints
    
    # Tracking
    tracking_url_template = models.CharField(max_length=255, blank=True)  # e.g., "https://track.carrier.com/{tracking_number}"
    
    # Settings
    is_active = models.BooleanField(default=True)
    logo = models.ImageField(upload_to='carriers/', blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### DeliveryZone

**Purpose**: Geographic delivery zones with pricing.

```python
class DeliveryZone(models.Model):
    """
    Delivery zone for shipping rate calculation.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    
    # Geographic definition
    countries = models.JSONField(default=list)  # List of country codes
    postal_codes = models.JSONField(default=list, blank=True)  # Postal code patterns
    
    # Pricing
    base_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    per_kg_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Estimated delivery time
    min_days = models.IntegerField(default=1)
    max_days = models.IntegerField(default=7)
    
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=100, blank=True)
    color = models.CharField(max_length=20, default='#000000')  # Hex color
```

---

### ManifestStatus

**Purpose**: Customizable manifest statuses per workspace.

**Migrated from**: `freight/models/freight.py`

```python
class ManifestStatus(models.Model):
    """
    Customizable manifest status.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # System event mapping
    event = models.CharField(max_length=30, blank=True)  # 'created', 'shipped', 'arrived', etc.
    
    order = models.IntegerField(default=0)
    color = models.CharField(max_length=7, default='#000000')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### Manifest

**Purpose**: Master waybill / shipping batch.

**Migrated from**: `freight/models/freight.py`

```python
class Manifest(models.Model):
    """
    Manifest represents a shipping batch or master waybill.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Identification
    title = models.CharField(max_length=255)
    master_waybill = models.CharField(max_length=100, blank=True)
    
    # Transport details
    freight_type = models.CharField(max_length=20, choices=FREIGHT_TYPE_CHOICES, default='sea')
    vessel_name = models.CharField(max_length=100, blank=True)
    voyage_number = models.CharField(max_length=50, blank=True)
    container_number = models.CharField(max_length=50, blank=True)
    
    # Carrier
    carrier = models.ForeignKey(Carrier, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Route
    source_warehouse = models.ForeignKey(Warehouse, related_name='source_manifests', on_delete=models.SET_NULL, null=True, blank=True)
    target_warehouse = models.ForeignKey(Warehouse, related_name='target_manifests', on_delete=models.SET_NULL, null=True, blank=True)
    origin_port = models.CharField(max_length=100, blank=True)
    dest_port = models.CharField(max_length=100, blank=True)
    
    # Timeline
    etd = models.DateTimeField(blank=True, null=True)  # Estimated Time of Departure
    eta = models.DateTimeField(blank=True, null=True)  # Estimated Time of Arrival
    ata = models.DateTimeField(blank=True, null=True)  # Actual Time of Arrival
    
    # Status
    state = models.CharField(max_length=1, choices=TRANSITION_STATE_CHOICES, default='D')
    status = models.ForeignKey(ManifestStatus, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Capacity
    space_capacity = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # m3
    weight_capacity = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # kg
    space_available = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    weight_available = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    
    # Financial
    invoices = models.ManyToManyField('bfg2_finance.Invoice', related_name='manifests', blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### ConsignmentStatus

**Purpose**: Customizable consignment statuses per workspace.

**Migrated from**: `freight/models/freight.py`

```python
class ConsignmentStatus(models.Model):
    """
    Customizable consignment status.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    event = models.CharField(max_length=30, blank=True)
    
    order = models.IntegerField(default=0)
    color = models.CharField(max_length=7, default='#000000')
    is_active = models.BooleanField(default=True)
    
    # Notification settings
    notify_customer = models.BooleanField(default=False)
    email_template = models.CharField(max_length=100, blank=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### Consignment

**Purpose**: Individual shipment/consignment.

**Migrated from**: `freight/models/freight.py`

```python
class Consignment(models.Model):
    """
    Consignment is an individual shipment.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    manifest = models.ForeignKey(Manifest, on_delete=models.SET_NULL, null=True, blank=True, related_name='consignments')
    
    # Identification
    tracking_number = models.CharField(max_length=100, unique=True)
    reference_id = models.CharField(max_length=50, blank=True)
    
    # Customer & Addresses
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT)
    consignee = models.ForeignKey('common.Address', related_name='consignments_as_consignee', on_delete=models.PROTECT)
    shipper = models.ForeignKey('common.Address', related_name='consignments_as_shipper', on_delete=models.PROTECT, null=True, blank=True)
    
    # Warehouses
    source_warehouse = models.ForeignKey(Warehouse, related_name='source_consignments', on_delete=models.SET_NULL, null=True, blank=True)
    target_warehouse = models.ForeignKey(Warehouse, related_name='target_consignments', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Carrier
    carrier = models.ForeignKey(Carrier, on_delete=models.SET_NULL, null=True, blank=True)
    carrier_tracking_number = models.CharField(max_length=100, blank=True)
    
    # Status
    state = models.CharField(max_length=1, choices=TRANSITION_STATE_CHOICES, default='D')
    status = models.ForeignKey(ConsignmentStatus, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Order link
    orders = models.ManyToManyField('bfg2_shop.Order', blank=True)
    
    # Measurements
    total_weight = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # kg
    total_volume = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # m3
    piece_count = models.IntegerField(default=0)
    
    # Financial
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    invoices = models.ManyToManyField('bfg2_finance.Invoice', related_name='consignments', blank=True)
    
    # Service
    service = models.ForeignKey('FreightService', on_delete=models.SET_NULL, null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### PackageStatus

**Purpose**: Customizable package statuses per workspace.

**Migrated from**: `freight/models/freight.py`

```python
class PackageStatus(models.Model):
    """
    Customizable package status.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    event = models.CharField(max_length=30, blank=True)
    
    order = models.IntegerField(default=0)
    color = models.CharField(max_length=7, default='#000000')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### Package

**Purpose**: Physical package entity.

**Migrated from**: `freight/models/freight.py`

```python
class Package(models.Model):
    """
    Physical package within a consignment.
    """
    consignment = models.ForeignKey(Consignment, on_delete=models.CASCADE, related_name='packages')
    
    tracking_number = models.CharField(max_length=100, blank=True)
    
    # Physical properties
    weight = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # kg
    volume = models.DecimalField(max_digits=10, decimal_places=4, default=0)  # m3
    piece_count = models.IntegerField(default=1)
    
    # Packaging
    packaging_type = models.ForeignKey('PackagingType', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Status
    state = models.CharField(max_length=1, choices=TRANSITION_STATE_CHOICES, default='D')
    status = models.ForeignKey(PackageStatus, on_delete=models.SET_NULL, null=True, blank=True)
    location = models.CharField(max_length=50, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### PackagingType

**Purpose**: Package/wrapping type options.

**Migrated from**: `freight/models/freight.py`

```python
class PackagingType(models.Model):
    """
    Packaging type (carton, pallet, envelope, etc.).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    title = models.CharField(max_length=100)
    subtitle = models.CharField(max_length=255, blank=True)
    content = models.TextField(blank=True)
    
    logo = models.URLField(blank=True)
    style = models.CharField(max_length=50, default='default')
    
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
```

---

### FreightService

**Purpose**: Freight/logistics service offerings.

**Migrated from**: `freight/models/freight.py`

```python
class FreightService(models.Model):
    """
    Freight service type (e.g., Sea Freight Economy, Air Express).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    freight_type = models.CharField(max_length=1, choices=FREIGHT_TYPE_CHOICES, default='S')
    
    # Transit time
    transit_time_min = models.IntegerField(default=0)  # days
    transit_time_max = models.IntegerField(default=0)
    
    # Geographic
    origin_country = models.CharField(max_length=3, blank=True)
    destination_country = models.CharField(max_length=3, blank=True)
    
    # Pricing
    charged_by = models.CharField(max_length=1, choices=CHARGED_BY_CHOICES, default='W')  # Weight or Volume
    min_density = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # kg/m3
    
    # Pricing settings
    config = models.JSONField(default=dict, blank=True)
    
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### TrackingEvent

**Purpose**: Detailed tracking history.

**Migrated from**: `freight/models/freight.py` (was FreightLog)

```python
class TrackingEvent(models.Model):
    """
    Tracking event for shipments and packages.
    """
    # Links (one should be set)
    manifest = models.ForeignKey(Manifest, on_delete=models.CASCADE, related_name='events', null=True, blank=True)
    consignment = models.ForeignKey(Consignment, on_delete=models.CASCADE, related_name='events', null=True, blank=True)
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='events', null=True, blank=True)
    
    # Event details
    event = models.CharField(max_length=30, choices=EVENT_CHOICES, default='custom')
    description = models.TextField(blank=True)
    
    # Location
    location = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    
    # Visibility
    is_visible = models.BooleanField(default=False)  # Show to customers
    
    # Metadata
    timestamp = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
```

---

## API Endpoints

### Warehouses
- `GET /api/delivery/warehouses/` - List warehouses
- `GET /api/delivery/warehouses/{code}/` - Get warehouse details

### Tracking
- `GET /api/delivery/track/{tracking_number}/` - Track shipment
- `GET /api/delivery/consignments/{id}/events/` - Get tracking history

### Manifests
- `GET /api/delivery/manifests/` - List manifests
- `GET /api/delivery/manifests/{id}/` - Get manifest details
- `POST /api/delivery/manifests/` - Create manifest (admin)

### Consignments
- `GET /api/delivery/consignments/` - List consignments
- `GET /api/delivery/consignments/{tracking_number}/` - Get consignment details
- `POST /api/delivery/consignments/` - Create consignment
- `PUT /api/delivery/consignments/{id}/status/` - Update status

## Integration with Other Modules

- **bfg2_shop**: Links orders to consignments for fulfillment
- **bfg2_finance**: Invoicing for shipping costs
