"""
BFG Delivery Module Services

Delivery and consignment management service
"""

from typing import Any, Optional, List, Dict
from datetime import datetime, date
from django.db import models, transaction
from django.db.models import QuerySet
from django.conf import settings
from bfg.core.services import BaseService
from bfg.core.exceptions import ValidationError
from bfg.delivery.exceptions import DeliveryUnavailable
from bfg.delivery.models import (
    Warehouse, Carrier, FreightService, Manifest, Consignment,
    Package, TrackingEvent, FreightStatus, FreightState
)
from bfg.shop.models import Order
from bfg.common.models import Address


class DeliveryService(BaseService):
    """
    Delivery and consignment management service
    
    Handles creation of consignments, packages, and tracking
    """
    
    @transaction.atomic
    def create_consignment(
        self,
        orders: List[Order],
        service: FreightService,
        sender_address: Address,
        recipient_address: Address,
        **kwargs: Any
    ) -> Consignment:
        """
        Create consignment for orders
        
        Args:
            orders: List of Order instances
            service: FreightService instance
            sender_address: Sender address
            recipient_address: Recipient address
            **kwargs: Additional consignment fields
            
        Returns:
            Consignment: Created consignment instance
        """
        # Validate orders belong to workspace
        for order in orders:
            self.validate_workspace_access(order)
        
        # Get freight status - use provided status or get default
        status = kwargs.get('status')
        if not status:
            # Get default freight status for new consignments
            status = FreightStatus.objects.filter(
                workspace=self.workspace,
                type='consignment',
                state=FreightState.PENDING.value
            ).first()
            
            if not status:
                raise DeliveryUnavailable("No freight status configured for consignments")
        
        # Get state - use provided state or derive from status
        state = kwargs.get('state', FreightState.PENDING.value)
        if not state and status:
            state = status.state
        
        # Generate consignment number
        consignment_number = self._generate_consignment_number()
        
        # Create consignment
        consignment = Consignment.objects.create(
            workspace=self.workspace,
            consignment_number=consignment_number,
            tracking_number=kwargs.get('tracking_number', ''),
            service=service,
            sender_address=sender_address,
            recipient_address=recipient_address,
            state=state,
            status=status,
            ship_date=kwargs.get('ship_date'),
            estimated_delivery=kwargs.get('estimated_delivery'),
        )
        
        # Link orders
        consignment.orders.set(orders)
        
        package_count = 0
        if orders:
            # Link packages from orders to consignment (atomic operation)
            order_ids = [order.id for order in orders]
            order_packages = Package.objects.filter(
                order_id__in=order_ids,
                order__workspace=self.workspace,
                consignment__isnull=True
            )
            if not order_packages.exists():
                raise ValidationError(
                    f"No packages found for the orders {order_ids}. Please add packages before creating consignment."
                )
            package_count = order_packages.update(consignment=consignment)
        # When orders is empty, allow creating consignment for parcel-consolidation flow (link parcels via PATCH later)

        # Create tracking event
        self.add_tracking_event(
            consignment,
            'created',
            f'Consignment created with {package_count} package(s)',
            is_public=True
        )
        
        # Emit event
        self.emit_event('consignment.created', {'consignment': consignment})
        
        return consignment
    
    def _generate_consignment_number(self) -> str:
        """
        Generate unique consignment number
        
        Returns:
            str: Consignment number
        """
        import random
        import string
        from django.utils import timezone
        
        # Format: CON-YYYYMMDD-XXXXX
        date_str = timezone.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.digits, k=5))
        
        consignment_number = f"CON-{date_str}-{random_str}"
        
        # Ensure uniqueness
        while Consignment.objects.filter(consignment_number=consignment_number).exists():
            random_str = ''.join(random.choices(string.digits, k=5))
            consignment_number = f"CON-{date_str}-{random_str}"
        
        return consignment_number
    
    @transaction.atomic
    def create_package(
        self,
        consignment: Consignment,
        weight: float,
        **kwargs: Any
    ) -> Package:
        """
        Create package for consignment
        
        Args:
            consignment: Consignment instance
            weight: Package weight in kg
            **kwargs: Additional package fields
            
        Returns:
            Package: Created package instance
        """
        self.validate_workspace_access(consignment)
        
        # Generate package number
        package_count = consignment.packages.count() + 1
        package_number = f"{consignment.consignment_number}-P{package_count:03d}"
        
        # Get default freight status for packages
        status = FreightStatus.objects.filter(
            workspace=self.workspace,
            type='package',
            state=FreightState.PENDING.value
        ).first()
        
        if not status:
            # TODO: Cache. Fallback: get first available package status
            status = FreightStatus.objects.filter(
                workspace=self.workspace,
                type='package',
                is_active=True
            ).order_by('order').first()
            
        if not status:
            raise DeliveryUnavailable("No freight status configured for packages")
        
        # Create package
        package = Package.objects.create(
            consignment=consignment,
            package_number=package_number,
            weight=weight,
            length=kwargs.get('length'),
            width=kwargs.get('width'),
            height=kwargs.get('height'),
            description=kwargs.get('description', ''),
            state=FreightState.PENDING.value,
            status=status,
        )
        
        # Log package creation
        self.add_tracking_event(
            package,
            'created',
            f"Package {package_number} created in consignment {consignment.consignment_number}",
            is_public=False
        )
        
        return package
        
    @transaction.atomic
    def add_tracking_event(
        self,
        target: models.Model,
        event_type: str,
        description: str,
        location: str = '',
        event_time: Optional[datetime] = None,
        is_public: bool = False,
        user: Optional[settings.AUTH_USER_MODEL] = None
    ) -> TrackingEvent:
        """
        Add a generic tracking event to any shipping-related object.
        
        Args:
            target: The object being tracked (Consignment, Manifest, Package, etc.)
            event_type: Event type code
            description: Event description
            location: Event location
            event_time: Event time (defaults to now)
            is_public: Whether the event is visible to customers
            user: User who performed the action
            
        Returns:
            TrackingEvent: Created tracking event
        """
        self.validate_workspace_access(target)
        
        if not event_time:
            from django.utils import timezone
            event_time = timezone.now()
        
        tracking_event = TrackingEvent.objects.create(
            workspace=self.workspace,
            target=target,
            event_type=event_type,
            description=description,
            location=location,
            event_time=event_time,
            is_public=is_public,
            created_by=user or self.user
        )
        
        return tracking_event

    @transaction.atomic
    def sync_consignment_status(self, consignment: Consignment) -> Consignment:
        """
        Synchronize consignment status based on its packages.
        Only updates the consignment status if ALL packages have the SAME status,
        and it differs from the current consignment status.
        
        This is more efficient: uses a single database query to get distinct status IDs,
        then checks if there's exactly one unique status across all packages.
        Note: Package statuses are 'package' type, but we need to find the corresponding
        'consignment' type status with the same state value.
        """
        self.validate_workspace_access(consignment)
        
        # Get distinct package status IDs in a single efficient query
        # Use set() to ensure uniqueness (MySQL distinct() can sometimes return duplicates)
        distinct_status_ids = set(
            consignment.packages.values_list('status_id', flat=True)
        )
        
        # If no packages, nothing to sync
        if not distinct_status_ids:
            return consignment
        
        # Check if all packages have the same status
        # If set has more than 1 element, packages have different statuses
        if len(distinct_status_ids) != 1:
            # Packages have different statuses, don't update consignment
            return consignment
        
        # All packages have the same status (package type)
        # Get the single status_id from the set
        package_status_id = next(iter(distinct_status_ids))
        
        # Get the package status to find its state value
        package_status = FreightStatus.objects.filter(
            pk=package_status_id,
            workspace=self.workspace,
            type='package'
        ).first()
        
        if not package_status:
            # Package status not found, can't update
            return consignment
        
        # Convert from Package FreightStatus to Consignment FreightStatus
        if package_status.mapped_consignment_status:
            target_status = package_status.mapped_consignment_status
        else:
            # Fallback: find a consignment-type status with the same state
            target_status = FreightStatus.objects.filter(
                workspace=self.workspace,
                type='consignment',
                state=package_status.state,
                is_active=True
            ).first()
            if not target_status:
                return consignment            
        
        # Only update if consignment status differs from target status
        consignment.refresh_from_db()
        if consignment.status_id == target_status.pk:
            return consignment
        
        # Get description from FreightStatus, fallback to name if description is empty
        event_description = target_status.description or f"Consignment status updated to {target_status.name}"
        # Map status state to TrackingEvent event_type (must be a valid choice, e.g. 'delivered')
        event_type = 'status_change'
        if target_status.state == FreightState.DELIVERED.value:
            event_type = 'delivered'
        elif target_status.state == FreightState.SHIPPED.value:
            event_type = 'in_transit'
        self.add_tracking_event(
            consignment,
            event_type,
            event_description,
            ""
        )
        
        # Update consignment status and state
        old_status_id = consignment.status_id
        old_state = consignment.state
        consignment.status = target_status
        consignment.state = target_status.state
        consignment.save(update_fields=['status', 'state', 'updated_at'])
        
        # Emit consignment status_change event
        self.emit_event('consignment.status_changed', {
            'consignment_id': consignment.id,
            'consignment_number': consignment.consignment_number,
            'old_status_id': old_status_id,
            'new_status_id': target_status.id,
            'old_state': old_state,
            'new_state': target_status.state,
            'status_code': target_status.code,
            'status_name': target_status.name,
        })
        
        return consignment
    
    @transaction.atomic
    def update_consignment_status(
        self,
        consignment: Consignment,
        new_status: FreightStatus
    ) -> Consignment:
        """
        Update consignment status
        
        Args:
            consignment: Consignment instance
            new_status: New FreightStatus instance
            
        Returns:
            Consignment: Updated consignment instance
        """
        self.validate_workspace_access(consignment)
        
        old_status_name = consignment.status.name if consignment.status else "None"
        consignment.status = new_status
        consignment.state = new_status.state
        consignment.save()

        if new_status.state == FreightState.DELIVERED.value:
            self.emit_event('consignment.delivered', {'consignment': consignment})

        # Log status change
        self.add_tracking_event(
            consignment,
            'status_change',
            f"Consignment status changed from {old_status_name} to {new_status.name}",
            is_public=new_status.is_public
        )
        
        return consignment

    @transaction.atomic
    def update_consignment_notes(self, consignment: Consignment, notes: str) -> Consignment:
        """Update consignment notes with tracking."""
        self.validate_workspace_access(consignment)
        consignment.notes = notes # Assuming notes field exists or added
        consignment.save()
        
        self.add_tracking_event(
            consignment,
            'note_added',
            f"Notes updated: {notes[:50]}...",
            is_public=False
        )
        return consignment

    @transaction.atomic
    def update_consignment_customer(self, consignment: Consignment, customer_id: int) -> Consignment:
        """Update consignment customer with tracking."""
        # This might need common.models.Customer import
        from bfg.common.models import Customer
        self.validate_workspace_access(consignment)
        customer = Customer.objects.get(id=customer_id)
        # Update logic here depends on how Consignment relates to Customer
        # For now, let's assume it has a customer field or we log it generically
        self.add_tracking_event(
            consignment,
            'customer_changed',
            f"Customer changed to {customer.name}",
            is_public=False
        )
        return consignment
    
    def get_consignments_for_orders(
        self,
        orders: List[Order]
    ) -> QuerySet[Consignment]:
        """
        Get consignments for orders
        
        Args:
            orders: List of Order instances
            
        Returns:
            QuerySet: Consignments queryset
        """
        order_ids = [order.id for order in orders]
        
        return Consignment.objects.filter(
            workspace=self.workspace,
            orders__id__in=order_ids
        ).distinct().prefetch_related('packages', 'tracking_events')

    # ========================================================================
    # Carrier Plugin Integration
    # ========================================================================
    
    def _address_to_dict(self, address: Address) -> Dict[str, Any]:
        """Convert Address model to dict for carrier plugin."""
        result = {
            'name': address.full_name or '',
            'company': address.company or '',
            'line1': address.address_line1 or '',
            'line2': address.address_line2 or '',
            'city': address.city or '',
            'state': address.state or '',
            'postal_code': address.postal_code or '',
            'country': address.country or 'NZ',
            'phone': address.phone or '',
            'email': address.email or '',
        }
        
        # Add coordinates if available (from Warehouse or Address model)
        if hasattr(address, 'latitude') and address.latitude:
            result['latitude'] = float(address.latitude)
        if hasattr(address, 'longitude') and address.longitude:
            result['longitude'] = float(address.longitude)
        
        return result
    
    def _packages_to_list(self, packages) -> List[Dict[str, Any]]:
        """Convert Package queryset to list of dicts for carrier plugin."""
        return [
            {
                'weight': float(pkg.weight or 1),
                'length': float(pkg.length or 10),
                'width': float(pkg.width or 10),
                'height': float(pkg.height or 10),
                'description': pkg.description or 'Package',
            }
            for pkg in packages
        ]
    
    def get_shipping_options(
        self,
        carrier: Carrier,
        sender_address: Address,
        recipient_address: Address,
        packages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Get shipping options/quotes from carrier plugin.
        
        Args:
            carrier: Carrier instance
            sender_address: Sender address
            recipient_address: Recipient address
            packages: List of package dicts
            
        Returns:
            List of shipping options with prices
        """
        import logging
        logger = logging.getLogger(__name__)
        
        from bfg.delivery.carriers import get_carrier_plugin
        
        plugin = get_carrier_plugin(carrier)
        if not plugin:
            logger.warning(f"No plugin available for carrier {carrier.name} (type: {carrier.carrier_type})")
            return []
        
        try:
            sender_dict = self._address_to_dict(sender_address)
            recipient_dict = self._address_to_dict(recipient_address)
            
            logger.debug(f"Getting shipping options from {carrier.name} plugin")
            logger.debug(f"Sender: {sender_dict.get('name')}, {sender_dict.get('city')}, {sender_dict.get('country')}")
            logger.debug(f"Recipient: {recipient_dict.get('name')}, {recipient_dict.get('city')}, {recipient_dict.get('country')}")
            logger.debug(f"Packages: {len(packages)} packages")
            
            options = plugin.get_shipping_options(sender_dict, recipient_dict, packages)
            
            logger.info(f"Carrier {carrier.name} returned {len(options)} shipping options")
            
            # Convert ShippingOption objects to dicts, extracting carrier info from extra_data
            result_options = []
            for opt in options:
                option_dict = {
                    'service_code': opt.service_code,
                    'service_name': opt.service_name,
                    'price': str(opt.price),
                    'currency': opt.currency,
                    'estimated_days_min': opt.estimated_days_min,
                    'estimated_days_max': opt.estimated_days_max,
                }
                
                # Extract carrier information from extra_data if available
                if opt.extra_data:
                    quote_info = opt.extra_data.get('quote', {})
                    if quote_info:
                        # Extract carrier_name from quote info
                        carrier_name = quote_info.get('carrier_name')
                        if carrier_name:
                            option_dict['carrier_name'] = carrier_name
                        
                        # Extract carrier_id if available
                        carrier_id = quote_info.get('carrier_id')
                        if carrier_id:
                            option_dict['carrier_id'] = carrier_id
                        
                        # Extract carrier_method_desc for additional description
                        carrier_method_desc = quote_info.get('carrier_method_desc')
                        if carrier_method_desc:
                            option_dict['carrier_method_desc'] = carrier_method_desc
                
                result_options.append(option_dict)
            
            return result_options
        except Exception as e:
            logger.error(f"Error getting shipping options from carrier {carrier.name}: {e}", exc_info=True)
            raise
    
    @transaction.atomic
    def ship_consignment(
        self,
        consignment: Consignment,
        service_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ship consignment using carrier plugin.
        Creates shipment with carrier API and updates tracking number.
        
        Args:
            consignment: Consignment instance
            service_code: Optional service code (uses service default if not provided)
            
        Returns:
            dict: Result with tracking_number, label_url, etc.
        """
        from bfg.delivery.carriers import get_carrier_plugin
        
        self.validate_workspace_access(consignment)
        
        carrier = consignment.service.carrier
        plugin = get_carrier_plugin(carrier)
        
        if not plugin:
            return {
                'success': False,
                'error': f"No plugin available for carrier type: {carrier.carrier_type}"
            }
        
        # Prepare data
        sender_dict = self._address_to_dict(consignment.sender_address)
        recipient_dict = self._address_to_dict(consignment.recipient_address)
        packages_list = self._packages_to_list(consignment.packages.all())
        
        # This should not happen if consignment was created properly
        if not packages_list:
            return {
                'success': False,
                'error': 'No packages found in consignment. Consignment may be invalid.'
            }
        
        # Use provided service_code or get from service
        if not service_code:
            service_code = consignment.service.code
        
        # Get reference from first order
        reference = None
        first_order = consignment.orders.first()
        if first_order:
            reference = first_order.order_number
        
        # Build metadata with local consignment info
        metadata = {
            'consignment_id': consignment.id,
            'consignment_number': consignment.consignment_number,
        }
        
        # Get shipping options first to obtain carrier-specific metadata
        # (e.g., ParcelPort requires QuoteRequestID, carrier_method_id, etc.)
        try:
            shipping_options = plugin.get_shipping_options(
                sender_address=sender_dict,
                recipient_address=recipient_dict,
                packages=packages_list,
            )
            
            # Find matching option by service_code
            matching_option = None
            for option in shipping_options:
                if option.service_code == service_code:
                    matching_option = option
                    break
            
            # If no exact match, try first option
            if not matching_option and shipping_options:
                matching_option = shipping_options[0]
            
            # Extract carrier-specific metadata from the shipping option
            if matching_option and matching_option.extra_data:
                extra = matching_option.extra_data
                # ParcelPort specific fields
                if 'quoteRequestID' in extra:
                    metadata['quoteRequestID'] = extra.get('quoteRequestID')
                
                # Extract from quote object if available
                quote = extra.get('quote', {})
                if quote:
                    metadata['carrier_method_id'] = quote.get('carrier_method_id')
                    metadata['carrier_method_code'] = quote.get('carrier_method_code')
                    metadata['carrier_id'] = quote.get('carrier_id')
        except Exception as e:
            # Log but don't fail - some carriers may not need this
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get shipping options for metadata: {e}")
        
        # Create consignment with carrier
        result = plugin.create_consignment(
            sender_address=sender_dict,
            recipient_address=recipient_dict,
            packages=packages_list,
            service_code=service_code,
            reference=reference,
            metadata=metadata
        )
        
        if not result.success:
            return {
                'success': False,
                'error': result.error
            }
        
        # Update consignment with tracking number
        consignment.tracking_number = result.tracking_number
        consignment.save(update_fields=['tracking_number', 'updated_at'])
        
        # Log tracking event
        self.add_tracking_event(
            consignment,
            'shipped',
            f"Shipment created with carrier. Tracking: {result.tracking_number}",
            is_public=True
        )
        
        # Get shipping label
        label_result = plugin.get_label(result.tracking_number)
        
        response = {
            'success': True,
            'tracking_number': result.tracking_number,
            'carrier_consignment_id': result.carrier_consignment_id,
        }
        
        if label_result.success:
            response['label_url'] = label_result.label_url
        
        # Emit event
        self.emit_event('consignment.shipped', {
            'consignment': consignment,
            'tracking_number': result.tracking_number,
        })
        
        return response
    
    def get_shipping_label(
        self,
        consignment: Consignment
    ) -> Dict[str, Any]:
        """
        Get shipping label for consignment.
        
        Args:
            consignment: Consignment instance
            
        Returns:
            dict: Result with label_url
        """
        from bfg.delivery.carriers import get_carrier_plugin
        
        self.validate_workspace_access(consignment)
        
        if not consignment.tracking_number:
            return {
                'success': False,
                'error': 'Consignment has no tracking number'
            }
        
        carrier = consignment.service.carrier
        plugin = get_carrier_plugin(carrier)
        
        if not plugin:
            return {
                'success': False,
                'error': f"No plugin available for carrier type: {carrier.carrier_type}"
            }
        
        result = plugin.get_label(consignment.tracking_number)
        
        return {
            'success': result.success,
            'label_url': result.label_url if result.success else '',
            'error': result.error if not result.success else '',
        }
    
    def sync_tracking(
        self,
        consignment: Consignment
    ) -> Dict[str, Any]:
        """
        Sync tracking information from carrier.
        
        Args:
            consignment: Consignment instance
            
        Returns:
            dict: Tracking result
        """
        from bfg.delivery.carriers import get_carrier_plugin
        
        self.validate_workspace_access(consignment)
        
        if not consignment.tracking_number:
            return {
                'success': False,
                'error': 'Consignment has no tracking number'
            }
        
        carrier = consignment.service.carrier
        plugin = get_carrier_plugin(carrier)
        
        if not plugin:
            # Fallback: return tracking URL if available
            tracking_url = None
            if carrier.tracking_url_template:
                tracking_url = carrier.tracking_url_template.replace(
                    '{tracking_number}', consignment.tracking_number
                )
            return {
                'success': True,
                'tracking_url': tracking_url,
                'events': [],
                'message': 'Tracking API not available, use tracking URL'
            }
        
        result = plugin.get_tracking(consignment.tracking_number)
        
        if not result.success:
            return {
                'success': False,
                'error': result.error
            }
        
        # Add new tracking events
        for event_data in result.events:
            # Check if event already exists (by timestamp)
            from django.utils.dateparse import parse_datetime
            event_time = parse_datetime(event_data.event_time)
            
            existing = TrackingEvent.objects.filter(
                content_type__model='consignment',
                object_id=consignment.id,
                event_time=event_time,
            ).exists()
            
            if not existing and event_time:
                self.add_tracking_event(
                    consignment,
                    event_data.event_type,
                    event_data.description,
                    location=event_data.location,
                    event_time=event_time,
                    is_public=True
                )
        
        # Update delivered status if applicable
        if result.is_delivered and consignment.state != FreightState.DELIVERED.value:
            delivered_status = FreightStatus.objects.filter(
                workspace=self.workspace,
                type='consignment',
                state=FreightState.DELIVERED.value
            ).first()
            
            if delivered_status:
                from django.utils import timezone
                consignment.status = delivered_status
                consignment.state = FreightState.DELIVERED.value
                consignment.actual_delivery = timezone.now()
                consignment.save()
                self.emit_event('consignment.delivered', {'consignment': consignment})
        
        return {
            'success': True,
            'status': result.status,
            'is_delivered': result.is_delivered,
            'events': [
                {
                    'event_time': e.event_time,
                    'event_type': e.event_type,
                    'description': e.description,
                    'location': e.location,
                }
                for e in result.events
            ]
        }


class ManifestService(BaseService):
    """
    Manifest management service
    
    Handles creation and management of shipping manifests
    """
    
    @transaction.atomic
    def create_manifest(
        self,
        warehouse: Warehouse,
        carrier: Carrier,
        manifest_date: date,
        **kwargs: Any
    ) -> Manifest:
        """
        Create shipping manifest
        
        Args:
            warehouse: Warehouse instance
            carrier: Carrier instance
            manifest_date: Manifest date
            **kwargs: Additional manifest fields
            
        Returns:
            Manifest: Created manifest instance
        """
        self.validate_workspace_access(warehouse)
        self.validate_workspace_access(carrier)
        
        # Generate manifest number
        manifest_number = self._generate_manifest_number()
        
        # Get default freight status
        status = FreightStatus.objects.filter(
            workspace=self.workspace,
            type='manifest',
            state=FreightState.PENDING.value
        ).first()
        
        if not status:
            raise DeliveryUnavailable("No freight status configured for manifests")
        
        # Create manifest
        manifest = Manifest.objects.create(
            workspace=self.workspace,
            warehouse=warehouse,
            carrier=carrier,
            manifest_number=manifest_number,
            manifest_date=manifest_date,
            pickup_date=kwargs.get('pickup_date'),
            state=FreightState.PENDING.value,
            status=status,
            is_closed=False,
            notes=kwargs.get('notes', ''),
            created_by=self.user,
        )
        
        # Dynamic service access
        delivery_service = DeliveryService(self.workspace, self.user)
        delivery_service.add_tracking_event(
            manifest,
            'created',
            f"Manifest {manifest_number} created",
            is_public=False
        )
        
        return manifest
        
        return manifest
    
    def _generate_manifest_number(self) -> str:
        """
        Generate unique manifest number
        
        Returns:
            str: Manifest number
        """
        import random
        import string
        from django.utils import timezone
        
        # Format: MAN-YYYYMMDD-XXXXX
        date_str = timezone.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.digits, k=5))
        
        manifest_number = f"MAN-{date_str}-{random_str}"
        
        # Ensure uniqueness
        while Manifest.objects.filter(manifest_number=manifest_number).exists():
            random_str = ''.join(random.choices(string.digits, k=5))
            manifest_number = f"MAN-{date_str}-{random_str}"
        
        return manifest_number
    
    @transaction.atomic
    def add_consignment_to_manifest(
        self,
        manifest: Manifest,
        consignment: Consignment
    ) -> Manifest:
        """
        Add consignment to manifest
        
        Args:
            manifest: Manifest instance
            consignment: Consignment instance
            
        Returns:
            Manifest: Updated manifest instance
        """
        self.validate_workspace_access(manifest)
        self.validate_workspace_access(consignment)
        
        if manifest.is_closed:
            raise ValidationError("Cannot add consignment to closed manifest")
        
        consignment.manifest = manifest
        consignment.save()
        
        return manifest
    
    @transaction.atomic
    def close_manifest(self, manifest: Manifest) -> Manifest:
        """
        Close manifest (no more consignments can be added)
        
        Args:
            manifest: Manifest instance
            
        Returns:
            Manifest: Updated manifest instance
        """
        self.validate_workspace_access(manifest)
        
        manifest.is_closed = True
        
        # Update status to shipped
        shipped_status = FreightStatus.objects.filter(
            workspace=self.workspace,
            type='manifest',
            state=FreightState.SHIPPED.value
        ).first()
        
        if shipped_status:
            manifest.status = shipped_status
            manifest.state = FreightState.SHIPPED.value
        
        manifest.save()
        
        # Log closure
        delivery_service = DeliveryService(self.workspace, self.user)
        delivery_service.add_tracking_event(
            manifest,
            'status_change',
            f"Manifest {manifest.manifest_number} closed and marked as SHIPPED",
            is_public=False
        )
        
        return manifest
