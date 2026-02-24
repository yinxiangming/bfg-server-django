# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.delivery module.
"""

from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from .models import (
    Warehouse, Carrier, FreightService, FreightStatus, PackagingType,
    Manifest, Consignment, Package, TrackingEvent, FreightState,
    DeliveryZone, StorageLocation, PackageTemplate
)
from bfg.common.models import Address


def clear_data():
    """Clear delivery module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect cache keys before delete (this module has no cache)
    # 2. Delete in dependency order (drop FKs that reference delivery models first)
    try:
        from apps.transport.models import LoadingManifest
        LoadingManifest.objects.all().delete()
    except ImportError:
        pass
    TrackingEvent.objects.all().delete()
    Package.objects.all().delete()
    Consignment.objects.all().delete()
    Manifest.objects.all().delete()
    StorageLocation.objects.all().delete()
    Warehouse.objects.all().delete()
    DeliveryZone.objects.all().delete()
    Carrier.objects.all().delete()
    PackagingType.objects.all().delete()
    PackageTemplate.objects.all().delete()
    FreightStatus.objects.all().delete()
    # 3. Invalidate caches (none for delivery)


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed delivery module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context (customers, addresses, etc.)
    
    Returns:
        dict: Created data
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating delivery module data...'))
    
    # Get context data
    customers = context.get('customers', [])
    addresses = context.get('addresses', [])
    
    # Create freight statuses
    freight_statuses = create_freight_statuses(workspace, stdout, style)
    
    # Create packaging types
    packaging_types = create_packaging_types(workspace, stdout, style)
    
    # Create carriers
    carriers = create_carriers(workspace, stdout, style)
    
    # Create freight services
    freight_services = create_freight_services(workspace, carriers, stdout, style)
    
    # Create warehouses
    warehouses = create_warehouses(workspace, stdout, style)
    
    # Create manifests
    manifests = create_manifests(workspace, warehouses, carriers, freight_statuses, stdout, style)
    
    # Create consignments
    consignments = create_consignments(
        workspace, customers, warehouses, manifests, 
        freight_statuses, freight_services, addresses, stdout, style
    )
    
    # Create packages
    packages = create_packages(workspace, consignments, freight_statuses, packaging_types, stdout, style)
    
    # Create tracking events
    tracking_events = create_tracking_events(workspace, consignments, stdout, style)
    
    # Create delivery zones
    delivery_zones = create_delivery_zones(workspace, stdout, style)
    
    # Create storage locations
    storage_locations = create_storage_locations(warehouses, stdout, style)
    
    # Create package templates
    package_templates = create_package_templates(workspace, stdout, style)
    
    summary = [
        {'label': 'Warehouses', 'count': Warehouse.objects.count()},
        {'label': 'Manifests', 'count': Manifest.objects.count()},
        {'label': 'Consignments', 'count': Consignment.objects.count()},
        {'label': 'Packages', 'count': Package.objects.count()},
    ]
    return {
        'freight_statuses': freight_statuses,
        'packaging_types': packaging_types,
        'carriers': carriers,
        'freight_services': freight_services,
        'warehouses': warehouses,
        'manifests': manifests,
        'consignments': consignments,
        'packages': packages,
        'tracking_events': tracking_events,
        'delivery_zones': delivery_zones,
        'storage_locations': storage_locations,
        'package_templates': package_templates,
        'summary': summary,
    }


def create_freight_statuses(workspace, stdout=None, style=None):
    """Create freight statuses"""
    statuses_data = [
        {'code': 'pending', 'name': 'Pending', 'type': 'consignment', 'state': FreightState.PENDING, 'color': '#FF9800', 'order': 1},
        {'code': 'in_transit', 'name': 'In Transit', 'type': 'consignment', 'state': FreightState.SHIPPED, 'color': '#2196F3', 'order': 2},
        {'code': 'delivered', 'name': 'Delivered', 'type': 'consignment', 'state': FreightState.DELIVERED, 'color': '#4CAF50', 'order': 3},
        {'code': 'cancelled', 'name': 'Cancelled', 'type': 'consignment', 'state': FreightState.CANCELLED, 'color': '#F44336', 'order': 4},
    ]
    statuses = []
    for data in statuses_data:
        status, created = FreightStatus.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'type': data['type'],
                'state': data['state'].value,
                'color': data['color'],
                'order': data['order'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created freight status: {status.name}'))
        statuses.append(status)
    return statuses


def create_packaging_types(workspace, stdout=None, style=None):
    """Create packaging types"""
    types_data = [
        {'code': 'box', 'name': 'Box', 'description': 'Standard cardboard box', 'order': 1},
        {'code': 'envelope', 'name': 'Envelope', 'description': 'Document envelope', 'order': 2},
        {'code': 'pallet', 'name': 'Pallet', 'description': 'Wooden pallet', 'order': 3},
        {'code': 'crate', 'name': 'Crate', 'description': 'Wooden crate', 'order': 4},
    ]
    types = []
    for data in types_data:
        pkg_type, created = PackagingType.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'description': data['description'],
                'order': data['order'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created packaging type: {pkg_type.name}'))
        types.append(pkg_type)
    return types


def create_carriers(workspace, stdout=None, style=None):
    """Create carriers based on available plugins"""
    carriers_data = [
        {
            'name': 'ParcelPort',
            'code': 'PARCELPORT',
            'carrier_type': 'parcelport',
            'config': {
                'username': 'surlex',
                'password': 'Abcd123321',
            },
            'is_test_mode': False,
        },
        {
            'name': 'Starshipit',
            'code': 'STARSHIPIT',
            'carrier_type': 'starshipit',
            'config': {
                'api_key': 'cc3996b75b1c43fb8628789d921669e5',
                'subscription_key': '38dc581b5dae454aa79c273c7010c6df',
            },
            'is_test_mode': False,
        },
    ]
    carriers = []
    for data in carriers_data:
        carrier, created = Carrier.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'carrier_type': data.get('carrier_type', ''),
                'config': data.get('config', {}),
                'is_test_mode': data.get('is_test_mode', False),
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created carrier: {carrier.name}'))
        carriers.append(carrier)
    return carriers


def create_freight_services(workspace, carriers, stdout=None, style=None):
    """Create freight services (limit to 5 total)"""
    services = []
    service_templates = [
        {'name': 'Standard Shipping', 'code': 'STANDARD', 'base_price': Decimal('10.00'), 'price_per_kg': Decimal('2.00'), 'estimated_days_min': 3, 'estimated_days_max': 7},
        {'name': 'Express Shipping', 'code': 'EXPRESS', 'base_price': Decimal('25.00'), 'price_per_kg': Decimal('5.00'), 'estimated_days_min': 1, 'estimated_days_max': 3},
        {'name': 'Overnight', 'code': 'OVERNIGHT', 'base_price': Decimal('50.00'), 'price_per_kg': Decimal('10.00'), 'estimated_days_min': 1, 'estimated_days_max': 1},
    ]
    
    # Create only 5 services total
    service_count = 0
    max_services = 5
    
    for carrier in carriers:
        if service_count >= max_services:
            break
        for template in service_templates:
            if service_count >= max_services:
                break
            service, created = FreightService.objects.get_or_create(
                workspace=workspace,
                carrier=carrier,
                code=f"{carrier.code}_{template['code']}",
                defaults={
                    'name': f"{carrier.name} {template['name']}",
                    'base_price': template['base_price'],
                    'price_per_kg': template['price_per_kg'],
                    'estimated_days_min': template['estimated_days_min'],
                    'estimated_days_max': template['estimated_days_max'],
                    'is_active': True,
                    'order': service_count + 1,
                }
            )
            if created and stdout:
                stdout.write(style.SUCCESS(f'✓ Created freight service: {service.name}'))
            services.append(service)
            service_count += 1
    
    return services


def create_warehouses(workspace, stdout=None, style=None):
    """Create warehouses with New Zealand address"""
    warehouses_data = [
        {
            'name': 'Auckland Warehouse',
            'code': 'AKL-WH',
            'address_line1': '40 Airpark dr',
            'city': 'Mangere',
            'state': 'Auckland',
            'postal_code': '2022',
            'country': 'NZ',
            'is_default': True,
        },
        {
            'name': 'Wellington Warehouse',
            'code': 'WLG-WH',
            'address_line1': '15 Tory Street',
            'city': 'Wellington',
            'state': 'Wellington',
            'postal_code': '6011',
            'country': 'NZ',
            'is_default': False,
        },
        {
            'name': 'Christchurch Warehouse',
            'code': 'CHC-WH',
            'address_line1': '123 Main South Road',
            'city': 'Christchurch',
            'state': 'Canterbury',
            'postal_code': '8022',
            'country': 'NZ',
            'is_default': False,
        },
    ]
    warehouses = []
    for data in warehouses_data:
        warehouse, created = Warehouse.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'address_line1': data['address_line1'],
                'city': data['city'],
                'state': data['state'],
                'postal_code': data['postal_code'],
                'country': data['country'],
                'is_active': True,
                'is_default': data.get('is_default', False),
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created warehouse: {warehouse.name}'))
        warehouses.append(warehouse)
    return warehouses


def create_manifests(workspace, warehouses, carriers, freight_statuses, stdout=None, style=None):
    """Create shipping manifests"""
    manifests = []
    base_date = timezone.now().date()
    
    for i in range(10):
        manifest_date = base_date - timedelta(days=i)
        warehouse = warehouses[i % len(warehouses)]
        carrier = carriers[i % len(carriers)]
        status = freight_statuses[0]  # Use first status
        
        manifest, created = Manifest.objects.get_or_create(
            manifest_number=f'MF-{manifest_date.strftime("%Y%m%d")}-{i+1:03d}',
            defaults={
                'workspace': workspace,
                'warehouse': warehouse,
                'carrier': carrier,
                'manifest_date': manifest_date,
                'pickup_date': manifest_date + timedelta(days=1),
                'state': FreightState.PENDING.value,
                'status': status,
                'is_closed': False,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created manifest: {manifest.manifest_number}'))
        manifests.append(manifest)
    return manifests


def create_consignments(workspace, customers, warehouses, manifests, freight_statuses, freight_services, addresses, stdout=None, style=None):
    """Create consignments"""
    consignments = []
    
    if not customers:
        return consignments
    
    for i in range(25):
        customer = customers[i % len(customers)]
        warehouse = warehouses[i % len(warehouses)]
        manifest = manifests[i % len(manifests)] if manifests else None
        status = freight_statuses[i % len(freight_statuses)]
        service = freight_services[i % len(freight_services)]
        
        # Get customer addresses
        customer_addresses = Address.objects.filter(
            workspace=workspace,
            content_type__model='customer',
            object_id=customer.id
        )
        sender_addr = customer_addresses.first()
        recipient_addr = customer_addresses.last() if customer_addresses.count() > 1 else sender_addr
        
        # Create recipient address if needed
        if not recipient_addr:
            recipient_addr, _ = Address.objects.get_or_create(
                workspace=workspace,
                content_type=ContentType.objects.get_for_model(customer),
                object_id=customer.id,
                address_line1=f'{100 + i} Delivery St',
                defaults={
                    'full_name': customer.user.get_full_name(),
                    'phone': customer.user.phone or '+1-555-0000',
                    'email': customer.user.email,
                    'city': 'Destination City',
                    'state': 'CA',
                    'postal_code': '90001',
                    'country': 'US',
                }
            )
        
        consignment_number = f'CN-{timezone.now().strftime("%Y%m%d")}-{i+1:04d}'
        tracking_number = f'TRK{timezone.now().strftime("%Y%m%d")}{i+1:04d}'
        
        try:
            consignment, created = Consignment.objects.get_or_create(
                consignment_number=consignment_number,
                defaults={
                    'workspace': workspace,
                    'manifest': manifest,
                    'service': service,
                    'sender_address': sender_addr,
                    'recipient_address': recipient_addr,
                    'tracking_number': tracking_number,
                    'ship_date': timezone.now().date() - timedelta(days=i % 10),
                    'estimated_delivery': timezone.now().date() + timedelta(days=5 + (i % 10)),
                    'state': status.state,
                    'status': status,
                }
            )
            if created:
                consignments.append(consignment)
        except IntegrityError:
            pass
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(consignments)} consignments'))
    return consignments


def create_packages(workspace, consignments, freight_statuses, packaging_types, stdout=None, style=None):
    """Create packages for consignments"""
    packages = []
    
    for consignment in consignments:
        # Create 1-3 packages per consignment
        num_packages = (consignment.id % 3) + 1
        status = freight_statuses[consignment.id % len(freight_statuses)]
        
        for j in range(num_packages):
            package_number = f'{consignment.consignment_number}-PKG-{j+1}'
            try:
                package, created = Package.objects.get_or_create(
                    package_number=package_number,
                    defaults={
                        'consignment': consignment,
                        'weight': Decimal(f'{10 + (j * 5)}.50'),
                        'length': Decimal('30.00'),
                        'width': Decimal('20.00'),
                        'height': Decimal('15.00'),
                        'state': status.state,
                        'status': status,
                        'description': f'Package {j+1} of {num_packages}',
                    }
                )
                if created:
                    packages.append(package)
            except IntegrityError:
                pass
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(packages)} packages'))
    return packages


def create_tracking_events(workspace, consignments, stdout=None, style=None):
    """Create tracking events for consignments"""
    from datetime import datetime
    
    if not consignments:
        return []
    
    events = []
    event_types = ['created', 'picked_up', 'in_transit', 'out_for_delivery', 'delivered']
    locations = ['Auckland Warehouse', 'Auckland Distribution Center', 'Destination Facility']
    
    # Get ContentType for Consignment
    from django.contrib.contenttypes.models import ContentType
    consignment_content_type = ContentType.objects.get_for_model(Consignment)
    
    for consignment in consignments[:10]:  # Create events for first 10 consignments
        # Create multiple events per consignment
        num_events = min(3, len(event_types))
        base_time = timezone.now() - timedelta(days=num_events)
        
        for i, event_type in enumerate(event_types[:num_events]):
            # Calculate event time based on sequence
            event_time = base_time + timedelta(days=i)
            
            # Use GenericForeignKey fields (content_type and object_id) instead of direct assignment
            event, created = TrackingEvent.objects.get_or_create(
                workspace=workspace,
                content_type=consignment_content_type,
                object_id=consignment.id,
                event_type=event_type,
                event_time=event_time,
                defaults={
                    'description': f'Package {event_type.replace("_", " ").title()}',
                    'location': locations[i % len(locations)],
                }
            )
            if created:
                events.append(event)
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(events)} tracking events'))
    return events


def create_delivery_zones(workspace, stdout=None, style=None):
    """Create delivery zones"""
    zones_data = [
        {
            'name': 'North America Zone',
            'code': 'NA',
            'countries': ['US', 'CA', 'MX'],
        },
        {
            'name': 'Europe Zone',
            'code': 'EU',
            'countries': ['GB', 'FR', 'DE', 'IT', 'ES'],
        },
        {
            'name': 'Asia Pacific Zone',
            'code': 'APAC',
            'countries': ['CN', 'JP', 'KR', 'SG', 'AU', 'NZ'],
        },
        {
            'name': 'Middle East Zone',
            'code': 'ME',
            'countries': ['AE', 'SA', 'IL'],
        },
    ]
    
    zones = []
    for data in zones_data:
        zone, created = DeliveryZone.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'countries': data['countries'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created delivery zone: {zone.name}'))
        zones.append(zone)
    
    return zones


def create_storage_locations(warehouses, stdout=None, style=None):
    """Create storage locations for warehouses"""
    locations = []
    
    if not warehouses:
        return locations
    
    # Location patterns: sections (A-D) x aisles (01-05) x levels (1-3)
    sections = ['A', 'B', 'C', 'D']
    aisles = ['01', '02', '03', '04', '05']
    levels = ['1', '2', '3']
    
    for warehouse in warehouses:
        # Create some locations for each warehouse
        for section in sections[:2]:  # First 2 sections
            for aisle in aisles[:3]:  # First 3 aisles
                for level in levels:
                    code = f'{section}-{aisle}-{level}'
                    location, created = StorageLocation.objects.get_or_create(
                        warehouse=warehouse,
                        code=code,
                        defaults={
                            'description': f'Section {section}, Aisle {aisle}, Level {level}',
                            'is_active': True,
                        }
                    )
                    if created:
                        locations.append(location)
        
        if stdout and locations:
            # Count locations for this warehouse
            wh_locations = [loc for loc in locations if loc.warehouse == warehouse]
            stdout.write(style.SUCCESS(f'✓ Created {len(wh_locations)} storage locations for {warehouse.name}'))
    
    return locations


def create_package_templates(workspace, stdout=None, style=None):
    """Create package templates for testing"""
    templates_data = [
        {
            'code': 'SMALL_BOX',
            'name': 'Small Box',
            'description': 'Small cardboard box',
            'length': Decimal('20.00'),
            'width': Decimal('15.00'),
            'height': Decimal('10.00'),
            'tare_weight': Decimal('0.20'),
            'max_weight': Decimal('5.00'),
            'order': 1,
        },
        {
            'code': 'MEDIUM_BOX',
            'name': 'Medium Box',
            'description': 'Medium cardboard box',
            'length': Decimal('30.00'),
            'width': Decimal('25.00'),
            'height': Decimal('20.00'),
            'tare_weight': Decimal('0.40'),
            'max_weight': Decimal('10.00'),
            'order': 2,
        },
        {
            'code': 'LARGE_BOX',
            'name': 'Large Box',
            'description': 'Large cardboard box',
            'length': Decimal('40.00'),
            'width': Decimal('35.00'),
            'height': Decimal('30.00'),
            'tare_weight': Decimal('0.60'),
            'max_weight': Decimal('20.00'),
            'order': 3,
        },
        {
            'code': 'A4_ENVELOPE',
            'name': 'A4 Envelope',
            'description': 'A4 document envelope',
            'length': Decimal('29.70'),
            'width': Decimal('21.00'),
            'height': Decimal('2.00'),
            'tare_weight': Decimal('0.05'),
            'max_weight': Decimal('0.50'),
            'order': 4,
        },
    ]
    
    templates = []
    for data in templates_data:
        template, created = PackageTemplate.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'description': data['description'],
                'length': data['length'],
                'width': data['width'],
                'height': data['height'],
                'tare_weight': data['tare_weight'],
                'max_weight': data.get('max_weight'),
                'order': data['order'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created package template: {template.name}'))
        templates.append(template)
    
    return templates

