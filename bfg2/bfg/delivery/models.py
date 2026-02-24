# -*- coding: utf-8 -*-
"""
Models for BFG Delivery module.
Logistics, shipment tracking, and warehouse management.
"""

from enum import Enum
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal


# Transport type choices
TRANSPORT_TYPE_CHOICES = [
    ("air", _("Air")),
    ("sea", _("Sea")),
    ("road", _("Road")),
    ("rail", _("Rail")),
    ("other", _("Other")),
]


class Warehouse(models.Model):
    """Warehouse/fulfillment center."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='warehouses')
    
    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50)
    
    # Address
    address_line1 = models.CharField(_("Address Line 1"), max_length=255)
    address_line2 = models.CharField(_("Address Line 2"), max_length=255, blank=True)
    city = models.CharField(_("City"), max_length=100)
    state = models.CharField(_("State/Province"), max_length=100, blank=True)
    postal_code = models.CharField(_("Postal Code"), max_length=20)
    country = models.CharField(_("Country"), max_length=2)
    
    # Coordinates (for carrier APIs that require them)
    latitude = models.DecimalField(_("Latitude"), max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(_("Longitude"), max_digits=10, decimal_places=7, null=True, blank=True)
    
    # Contact
    phone = models.CharField(_("Phone"), max_length=50, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    is_default = models.BooleanField(_("Default"), default=False)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Warehouse")
        verbose_name_plural = _("Warehouses")
        ordering = ['name']
        unique_together = ('workspace', 'code')
    
    def __str__(self):
        return self.name


class StorageLocation(models.Model):
    """Specific location/shelf within a warehouse."""
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='locations')
    
    code = models.CharField(_("Code"), max_length=50)
    description = models.TextField(_("Description"), blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Storage Location")
        verbose_name_plural = _("Storage Locations")
        unique_together = ('warehouse', 'code')
        ordering = ['code']

    def __str__(self):
        return f"{self.warehouse.code} - {self.code}"


class Carrier(models.Model):
    """
    Shipping carrier/courier with plugin support.
    
    carrier_type: Plugin identifier (e.g., 'parcelport', 'nzpost').
                  Available types are discovered from carriers/ directory.
    config: Live API credentials and settings
    test_config: Test/sandbox API credentials
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='carriers')
    
    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50)
    
    # Plugin type - dynamically validated against available plugins
    carrier_type = models.CharField(
        _("Carrier Type"), 
        max_length=50, 
        blank=True,
        help_text=_("Plugin identifier. Leave empty for manual/custom carriers.")
    )
    
    # Configuration (similar to PaymentGateway)
    config = models.JSONField(_("Configuration"), default=dict, blank=True)
    test_config = models.JSONField(_("Test Configuration"), default=dict, blank=True)
    is_test_mode = models.BooleanField(_("Test Mode"), default=False)
    
    tracking_url_template = models.CharField(_("Tracking URL Template"), max_length=500, blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Carrier")
        verbose_name_plural = _("Carriers")
        ordering = ['name']
        unique_together = ('workspace', 'code')
    
    def __str__(self):
        mode = 'Test' if self.is_test_mode else 'Live'
        return f"{self.name} ({mode})"
    
    def get_active_config(self):
        """Get the active configuration based on test mode."""
        return self.test_config if self.is_test_mode else self.config


class FreightService(models.Model):
    """Shipping service/method."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='freight_services')
    carrier = models.ForeignKey(Carrier, on_delete=models.CASCADE, related_name='services')
    
    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50)
    description = models.TextField(_("Description"), blank=True)
    
    # Pricing
    base_price = models.DecimalField(_("Base Price"), max_digits=10, decimal_places=2)
    price_per_kg = models.DecimalField(_("Price per kg"), max_digits=10, decimal_places=2, default=0)
    
    # Delivery time
    estimated_days_min = models.PositiveIntegerField(_("Est. Days (Min)"), default=1)
    estimated_days_max = models.PositiveIntegerField(_("Est. Days (Max)"), default=7)
    
    # Constraints for delivery logic
    min_weight = models.DecimalField(_("Min Weight"), max_digits=10, decimal_places=2, default=0)
    max_weight = models.DecimalField(_("Max Weight"), max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Configuration for billing (product mapping)
    config = models.JSONField(_("Configuration"), default=dict, blank=True, help_text=_("Billing configuration, e.g. mapping to products."))

    # Transport type
    transport_type = models.CharField(_("Transport Type"), max_length=50, choices=TRANSPORT_TYPE_CHOICES, blank=True)

    # Delivery zones
    delivery_zones = models.ManyToManyField('delivery.DeliveryZone', related_name='freight_services', blank=True, verbose_name=_("Delivery Zones"))

    is_active = models.BooleanField(_("Active"), default=True)
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    
    class Meta:
        verbose_name = _("Freight Service")
        verbose_name_plural = _("Freight Services")
        ordering = ['order', 'name']
    
    def __str__(self):
        return f"{self.carrier.name} - {self.name}"


class FreightState(Enum):
    """
    Standard consignment/package states:
    - PENDING: Created, awaiting payment
    - PAID: Payment completed, awaiting warehouse processing
    - PROCESSING: Currently being processed in warehouse
    - READY: Warehouse processed, ready to ship
    - SHIPPED: In transit
    - DELIVERED: Successfully delivered
    - CANCELLED: Order cancelled
    - RETURNED: Returned to sender
    """
    PENDING = 'PENDING'
    PAID = 'PAID'
    PROCESSING = 'PROCESSING'
    READY = 'READY'
    SHIPPED = 'SHIPPED'
    DELIVERED = 'DELIVERED'
    CANCELLED = 'CANCELLED'
    RETURNED = 'RETURNED'

    @classmethod
    def choices(cls):
        return [
            (cls.PENDING.value, _("Pending")),
            (cls.PAID.value, _("Paid")),
            (cls.PROCESSING.value, _("Processing")),
            (cls.READY.value, _("Ready to Ship")),
            (cls.SHIPPED.value, _("Shipped")),
            (cls.DELIVERED.value, _("Delivered")),
            (cls.CANCELLED.value, _("Cancelled")),
            (cls.RETURNED.value, _("Returned")),
        ]
    

class FreightStatus(models.Model):    
    """Freight status - workspace customizable"""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, 
                                related_name='freight_statuses', 
                                verbose_name=_("Workspace"))
    code = models.CharField(_("Code"), max_length=50)
    name = models.CharField(_("Name"), max_length=100)
    type = models.CharField(_("Type"), max_length=50, choices=[
        ("manifest", _("Manifest")),
        ("consignment", _("Consignment")),
        ("package", _("Package")),
    ])
    mapped_consignment_status = models.ForeignKey(
        'delivery.FreightStatus',
        on_delete=models.CASCADE,
        related_name='package_statuses_mapped_to_this_consignment_status',
        null=True,
        blank=True,
        verbose_name=_("Mapped Consignment Status"),
        help_text=_("For a package status, the corresponding consignment FreightStatus (if any)")
    )
    state = models.CharField(_("State"), max_length=50, choices=FreightState.choices())
    description = models.TextField(_("Description"), blank=True, null=True, default=None)
    color = models.CharField(_("Color"), max_length=7, default='#000000')
    order = models.IntegerField(_("Order"), default=0)
    is_active = models.BooleanField(_("Active"), default=True)
    is_public = models.BooleanField(_("Public"), default=False)
    send_message = models.BooleanField(_("Send Message"), default=False)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Freight Status")
        verbose_name_plural = _("Freight Statuses")
        unique_together = ('workspace', 'code')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.workspace.name} - {self.name}"


class PackagingType(models.Model):
    """Packaging type - workspace customizable"""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE,
                                related_name='packaging_types',
                                verbose_name=_("Workspace"))
    code = models.CharField(_("Code"), max_length=50)
    name = models.CharField(_("Name"), max_length=100)
    description = models.TextField(_("Description"), blank=True)
    order = models.IntegerField(_("Order"), default=0)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        verbose_name = _("Packaging Type")
        verbose_name_plural = _("Packaging Types")
        unique_together = ('workspace', 'code')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.workspace.name} - {self.name}"


class PackageTemplate(models.Model):
    """
    Predefined package box sizes for quick selection.
    Examples: A4, B5, Small Box, Medium Box, etc.
    """
    workspace = models.ForeignKey(
        'common.Workspace', 
        on_delete=models.CASCADE, 
        related_name='package_templates'
    )
    
    # Identification
    code = models.CharField(_("Code"), max_length=50)
    name = models.CharField(_("Name"), max_length=100)
    description = models.TextField(_("Description"), blank=True)
    
    # Dimensions (in cm)
    length = models.DecimalField(_("Length (cm)"), max_digits=10, decimal_places=2)
    width = models.DecimalField(_("Width (cm)"), max_digits=10, decimal_places=2)
    height = models.DecimalField(_("Height (cm)"), max_digits=10, decimal_places=2)
    
    # Default weight (tare weight of box, in kg)
    tare_weight = models.DecimalField(
        _("Tare Weight (kg)"), 
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0'),
        help_text=_("Empty box weight")
    )
    
    # Max weight capacity
    max_weight = models.DecimalField(
        _("Max Weight (kg)"), 
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text=_("Maximum weight capacity")
    )
    
    # Ordering and status
    order = models.PositiveIntegerField(_("Order"), default=0)
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Package Template")
        verbose_name_plural = _("Package Templates")
        unique_together = ('workspace', 'code')
        ordering = ['order', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.length}x{self.width}x{self.height}cm)"
    
    @property
    def volume_cm3(self) -> Decimal:
        """Calculate volume in cm³"""
        return self.length * self.width * self.height
    
    @property
    def volume_m3(self) -> Decimal:
        """Calculate volume in m³"""
        return self.volume_cm3 / Decimal('1000000')


class Manifest(models.Model):
    """Shipping manifest (batch of consignments)."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='manifests')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='manifests', 
                                   verbose_name=_("Origin Warehouse"))
    destination_warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, 
                                               related_name='incoming_manifests',
                                               verbose_name=_("Destination Warehouse"),
                                               null=True, blank=True)
    carrier = models.ForeignKey(Carrier, on_delete=models.CASCADE, related_name='manifests')
    
    manifest_number = models.CharField(_("Manifest Number"), max_length=100, unique=True)
    
    # Dates
    manifest_date = models.DateField(_("Manifest Date"))
    pickup_date = models.DateField(_("Pickup Date"), null=True, blank=True)
    
    # Status
    state = models.CharField(_("State"), max_length=50, choices=FreightState.choices())
    status = models.ForeignKey('delivery.FreightStatus', on_delete=models.CASCADE, related_name='manifests')
    is_closed = models.BooleanField(_("Closed"), default=False)
    
    notes = models.TextField(_("Notes"), blank=True)
    
    tracking_events = GenericRelation('delivery.TrackingEvent', related_query_name='manifest')
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='manifests_created')
    
    class Meta:
        verbose_name = _("Manifest")
        verbose_name_plural = _("Manifests")
        ordering = ['-manifest_date', '-created_at']
        indexes = [
            models.Index(fields=['workspace', '-manifest_date']),
            models.Index(fields=['manifest_number']),
        ]
    
    def __str__(self):
        return self.manifest_number


class Consignment(models.Model):
    """Shipment/consignment."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='consignments')
    manifest = models.ForeignKey(Manifest, on_delete=models.SET_NULL, null=True, blank=True, related_name='consignments')
    
    # Link to orders (ManyToMany as per user request)
    orders = models.ManyToManyField('shop.Order', related_name='consignments')
    
    consignment_number = models.CharField(_("Consignment Number"), max_length=100, unique=True)
    tracking_number = models.CharField(_("Tracking Number"), max_length=100, blank=True)
    
    # Service
    service = models.ForeignKey(FreightService, on_delete=models.PROTECT, related_name='consignments')
    
    # Addresses
    sender_address = models.ForeignKey('common.Address', on_delete=models.PROTECT, related_name='sent_consignments')
    recipient_address = models.ForeignKey('common.Address', on_delete=models.PROTECT, related_name='received_consignments')
    
    # Status (customizable per workspace via ConsignmentStatus model - not defined yet but mentioned in plan)
    state = models.CharField(_("State"), max_length=50, choices=FreightState.choices())
    status = models.ForeignKey('delivery.FreightStatus', on_delete=models.CASCADE, related_name='consignments')
    
    # Dates
    ship_date = models.DateField(_("Ship Date"), null=True, blank=True)
    estimated_delivery = models.DateField(_("Estimated Delivery"), null=True, blank=True)
    actual_delivery = models.DateTimeField(_("Actual Delivery"), null=True, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    
    tracking_events = GenericRelation('delivery.TrackingEvent', related_query_name='consignment')
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Consignment")
        verbose_name_plural = _("Consignments")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['consignment_number']),
            models.Index(fields=['tracking_number']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return self.consignment_number


class Package(models.Model):
    """Individual package within a consignment or order."""
    
    consignment = models.ForeignKey(Consignment, on_delete=models.CASCADE, related_name='packages', null=True, blank=True)
    
    # Order relation (for shop order fulfillment)
    order = models.ForeignKey(
        'shop.Order', 
        on_delete=models.CASCADE, 
        related_name='packages', 
        null=True, 
        blank=True,
        help_text=_("Shop order this package belongs to")
    )
    
    # Package template reference
    template = models.ForeignKey(
        'delivery.PackageTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='packages',
        help_text=_("Package template used for dimensions")
    )
    
    package_number = models.CharField(_("Package Number"), max_length=100)
    
    # Dimensions
    weight = models.DecimalField(_("Weight (kg)"), max_digits=10, decimal_places=2, null=True, blank=True)
    length = models.DecimalField(_("Length (cm)"), max_digits=10, decimal_places=2, null=True, blank=True)
    width = models.DecimalField(_("Width (cm)"), max_digits=10, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(_("Height (cm)"), max_digits=10, decimal_places=2, null=True, blank=True)
    pieces = models.IntegerField(_("Pieces"), default=1, null=True, blank=True)
    
    # Status
    state = models.CharField(_("State"), max_length=50, choices=FreightState.choices())
    status = models.ForeignKey('delivery.FreightStatus', on_delete=models.CASCADE, related_name='packages')

    # Location
    storage_location = models.ForeignKey(StorageLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name='packages', verbose_name=_("Storage Location"))

    # Contents
    description = models.CharField(_("Description"), max_length=255, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    
    tracking_events = GenericRelation('delivery.TrackingEvent', related_query_name='package')
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Package")
        verbose_name_plural = _("Packages")
        ordering = ['package_number']
    
    def __str__(self):
        if self.consignment:
            return f"{self.consignment.consignment_number} - {self.package_number}"
        if self.order:
            return f"{self.order.order_number} - {self.package_number}"
        return self.package_number
    
    @property
    def volumetric_weight(self):
        """
        Calculate volumetric weight (DIM weight).
        Standard formula: L x W x H / 5000 (for kg, cm)
        """
        from decimal import Decimal
        if not all([self.length, self.width, self.height]):
            return Decimal('0')
        return (self.length * self.width * self.height) / Decimal('5000')
    
    @property
    def billing_weight(self):
        """
        Get billing weight (higher of actual vs volumetric).
        This is the weight used for shipping cost calculation.
        """
        from decimal import Decimal
        actual = self.weight or Decimal('0')
        return max(actual, self.volumetric_weight)
    
    @property
    def total_billing_weight(self):
        """Billing weight multiplied by pieces (quantity)"""
        pieces = self.pieces or 1
        return self.billing_weight * pieces


class TrackingEvent(models.Model):
    """Generic tracking event/log for consignments, manifests, packages, etc."""
    EVENT_TYPE_CHOICES = (
        ('created', _('Created')),
        ('status_change', _('Status Changed')),
        ('attribute_change', _('Attribute Changed')),
        ('picked_up', _('Picked Up')),
        ('in_transit', _('In Transit')),
        ('out_for_delivery', _('Out for Delivery')),
        ('delivered', _('Delivered')),
        ('exception', _('Exception')),
        ('returned', _('Returned')),
        ('note_added', _('Note Added')),
        ('customer_changed', _('Customer Changed')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='tracking_events', null=True, blank=True)
    
    # Generic relation to any object (Consignment, Manifest, Package, etc.)
    content_type = models.ForeignKey('contenttypes.ContentType', on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey('content_type', 'object_id')
    
    event_type = models.CharField(_("Event Type"), max_length=50, choices=EVENT_TYPE_CHOICES)
    description = models.TextField(_("Description"))
    location = models.CharField(_("Location"), max_length=255, blank=True)
    is_public = models.BooleanField(_("Publicly Visible"), default=False)
    
    event_time = models.DateTimeField(_("Event Time"))
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='tracking_events_created')
    
    class Meta:
        verbose_name = _("Tracking Event")
        verbose_name_plural = _("Tracking Events")
        ordering = ['-event_time']
        indexes = [
            models.Index(fields=['content_type', 'object_id', '-event_time']),
            models.Index(fields=['workspace', '-event_time']),
        ]
    
    def __str__(self):
        target_str = str(self.target) if self.target else f"{self.content_type} {self.object_id}"
        return f"{target_str} - {self.get_event_type_display()}"


class DeliveryZone(models.Model):
    """Delivery zone for shipping rate calculation."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='delivery_zones')
    
    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50)
    
    # Geographic coverage (simplified - could be more complex)
    countries = models.JSONField(_("Countries"), default=list)  # List of ISO country codes
    postal_code_patterns = models.JSONField(_("Postal Code Patterns"), default=list, blank=True)
    
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Delivery Zone")
        verbose_name_plural = _("Delivery Zones")
        ordering = ['order', 'name']
        unique_together = ('workspace', 'code')
    
    def __str__(self):
        return self.name

class ConsignmentNote(models.Model):
    """
    Note/Event log for a consignment with visibility and prioritization.
    """
    TYPE_CHOICES = (
        ('general', _('General')),
        ('address_change', _('Address Change')),
        ('info_change', _('Info Change')),
        ('issue', _('Issue/Problem')),
        ('special_request', _('Special Request'))
    )
    
    PRIORITY_CHOICES = (
        ('normal', _('Normal')),
        ('high', _('High')),
        ('critical', _('Critical')),
    )

    consignment = models.ForeignKey(Consignment, on_delete=models.CASCADE, related_name='consignment_notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    content = models.TextField(_("Content"))
    
    note_type = models.CharField(_("Type"), max_length=20, choices=TYPE_CHOICES, default='general')
    priority = models.CharField(_("Priority"), max_length=20, choices=PRIORITY_CHOICES, default='normal')
    
    is_visible_to_customer = models.BooleanField(_("Visible to Customer"), default=False)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Consignment Note")
        verbose_name_plural = _("Consignment Notes")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.consignment.consignment_number} - {self.get_note_type_display()}"
