"""
BFG Delivery Module API Views

ViewSets for delivery module
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.contenttypes.models import ContentType
from django.db import models

from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff
from bfg.delivery.models import (
    Warehouse, Carrier, FreightService, Manifest, Consignment,
    Package, TrackingEvent, FreightStatus, DeliveryZone, PackagingType,
    FreightState, PackageTemplate
)
from bfg.delivery.serializers import (
    WarehouseSerializer, CarrierSerializer, FreightServiceSerializer,
    ManifestListSerializer, ManifestDetailSerializer,
    ConsignmentListSerializer, ConsignmentDetailSerializer,
    PackageSerializer, TrackingEventSerializer, FreightStatusSerializer,
    DeliveryZoneSerializer, PackagingTypeSerializer, PackageTemplateSerializer
)
from bfg.delivery.services import DeliveryService, ManifestService
from bfg.delivery.schemas import (
    get_carrier_config_schema,
    get_carrier_form_schema,
    get_freight_service_config_schema,
    get_freight_service_form_schema,
    get_delivery_zone_form_schema,
    get_all_templates,
    get_template,
)


class WarehouseViewSet(viewsets.ModelViewSet):
    """Warehouse management ViewSet (Admin only)"""
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_queryset(self):
        """Get warehouses for current workspace"""
        return Warehouse.objects.filter(
            workspace=self.request.workspace
        ).order_by('name')
    
    def perform_create(self, serializer):
        """Create warehouse with workspace"""
        serializer.save(workspace=self.request.workspace)
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set warehouse as default"""
        warehouse = self.get_object()
        
        # Unset other defaults
        Warehouse.objects.filter(
            workspace=request.workspace,
            is_default=True
        ).exclude(id=warehouse.id).update(is_default=False)
        
        warehouse.is_default = True
        warehouse.save()
        
        serializer = self.get_serializer(warehouse)
        return Response(serializer.data)


class CarrierViewSet(viewsets.ModelViewSet):
    """Carrier management ViewSet (Staff)"""
    serializer_class = CarrierSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        """Get carriers for current workspace"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return Carrier.objects.none()
        return Carrier.objects.filter(
            workspace=workspace,
            is_active=True
        ).order_by('name')

    def create(self, request, *args, **kwargs):
        """Create carrier; return 409 on duplicate."""
        from django.db import IntegrityError
        if not getattr(request, 'workspace', None):
            return Response(
                {"detail": "No workspace. Send X-Workspace-ID header."},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError:
            return Response(
                {"detail": "A carrier with this code already exists for this workspace."},
                status=status.HTTP_409_CONFLICT
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        """Create carrier with workspace"""
        serializer.save(workspace=self.request.workspace)
    
    @action(detail=False, methods=['get'])
    def plugins(self, request):
        """
        List available carrier plugins.
        
        Returns list of plugin info with carrier_type, display_name, config_schema
        """
        from bfg.delivery.carriers import CarrierLoader
        
        plugins = []
        for carrier_type, display_name in CarrierLoader.list_available_plugins().items():
            plugin_info = CarrierLoader.get_plugin_info(carrier_type)
            if plugin_info:
                plugins.append(plugin_info)
        
        return Response(plugins)

    @action(detail=False, methods=['get'])
    def config_schema(self, request):
        """
        Return SchemaForm + ConfigSchema metadata for carrier credentials editor.
        """
        return Response({
            'config_schema': get_carrier_config_schema(),
            'form_schema': get_carrier_form_schema(),
        })
    
    @action(detail=True, methods=['post'])
    def get_shipping_options(self, request, pk=None):
        """
        Get shipping options from carrier plugin for an order.
        
        POST /api/v1/carriers/{id}/get_shipping_options/
        Body: {
            "order_id": 123,
            "pickup_address": {  // optional, uses default warehouse if not provided
                "name": "Warehouse Name",
                "address_line1": "123 Main St",
                "address_line2": "",
                "city": "Auckland",
                "state": "",
                "postal_code": "1010",
                "country": "NZ",
                "phone": ""
            }
        }
        
        Returns list of shipping options with service_code, name, price
        """
        from bfg.shop.models import Order
        from bfg.common.models import Address
        from bfg.delivery.services import DeliveryService
        
        carrier = self.get_object()
        order_id = request.data.get('order_id')
        pickup_address = request.data.get('pickup_address')
        
        if not order_id:
            return Response(
                {'detail': 'order_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get order
        try:
            order = Order.objects.get(id=order_id, workspace=request.workspace)
        except Order.DoesNotExist:
            return Response(
                {'detail': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Build sender address dict
        if pickup_address:
            # Use provided pickup address
            sender_address_dict = {
                'full_name': pickup_address.get('name', ''),
                'address_line1': pickup_address.get('address_line1', ''),
                'address_line2': pickup_address.get('address_line2', ''),
                'city': pickup_address.get('city', ''),
                'state': pickup_address.get('state', ''),
                'postal_code': pickup_address.get('postal_code', ''),
                'country': pickup_address.get('country', 'NZ'),
                'phone': pickup_address.get('phone', ''),
                'email': '',
                'company': '',
            }
        else:
            # Fallback to default warehouse
            warehouse = Warehouse.objects.filter(
                workspace=request.workspace,
                is_default=True,
                is_active=True
            ).first()
            
            if not warehouse:
                warehouse = Warehouse.objects.filter(
                    workspace=request.workspace,
                    is_active=True
                ).first()
            
            if not warehouse:
                return Response(
                    {'detail': 'No warehouse configured and no pickup_address provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create sender address dict from warehouse
            sender_address_dict = {
                'full_name': warehouse.name,
                'address_line1': warehouse.address_line1,
                'address_line2': warehouse.address_line2 or '',
                'city': warehouse.city,
                'state': warehouse.state or '',
                'postal_code': warehouse.postal_code,
                'country': warehouse.country or 'NZ',
                'phone': warehouse.phone or '',
                'email': warehouse.email or '',
                'company': '',
            }
            
            # Add coordinates if available
            if warehouse.latitude:
                sender_address_dict['latitude'] = float(warehouse.latitude)
            if warehouse.longitude:
                sender_address_dict['longitude'] = float(warehouse.longitude)
        
        # Get recipient address from order
        recipient_address = order.shipping_address
        if not recipient_address:
            return Response(
                {'detail': 'Order has no shipping address'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get packages from order
        order_packages = order.packages.all()
        if not order_packages.exists():
            return Response(
                {'detail': 'Order has no packages'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Convert packages to dict format
        packages_list = [
            {
                'weight': float(pkg.weight or 1),
                'length': float(pkg.length or 10),
                'width': float(pkg.width or 10),
                'height': float(pkg.height or 10),
                'description': pkg.description or 'Package',
            }
            for pkg in order_packages
        ]
        
        # Get shipping options from carrier plugin
        # Convert addresses to dict format expected by plugin
        import logging
        logger = logging.getLogger(__name__)
        
        service = DeliveryService(workspace=request.workspace, user=request.user)
        
        # Create temporary Address objects for conversion
        from bfg.common.models import Address
        temp_sender = Address(
            workspace=request.workspace,
            full_name=sender_address_dict['full_name'],
            address_line1=sender_address_dict['address_line1'],
            address_line2=sender_address_dict['address_line2'],
            city=sender_address_dict['city'],
            state=sender_address_dict['state'],
            postal_code=sender_address_dict['postal_code'],
            country=sender_address_dict['country'],
            phone=sender_address_dict['phone'],
            email=sender_address_dict['email'],
            company=sender_address_dict['company'],
        )
        
        try:
            options = service.get_shipping_options(
                carrier=carrier,
                sender_address=temp_sender,
                recipient_address=recipient_address,
                packages=packages_list
            )
            
            logger.info(f"Carrier {carrier.name} returned {len(options)} shipping options for order {order.id}")
            
            return Response({
                'carrier_id': carrier.id,
                'carrier_name': carrier.name,
                'order_id': order.id,
                'options': options
            })
        except Exception as e:
            logger.error(f"Error getting shipping options from carrier {carrier.name}: {e}", exc_info=True)
            return Response({
                'carrier_id': carrier.id,
                'carrier_name': carrier.name,
                'order_id': order.id,
                'options': [],
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def ship_order(self, request, pk=None):
        """
        Create consignment for an order using selected shipping option.
        
        POST /api/v1/carriers/{id}/ship_order/
        Body: {
            "order_id": 123,
            "service_code": "EXPRESS",
            "service_name": "Express Delivery",
            "price": "15.00"
        }
        
        Returns created consignment with tracking info
        """
        from bfg.shop.models import Order
        from bfg.common.models import Address
        from bfg.delivery.services import DeliveryService
        from bfg.delivery.carriers import get_carrier_plugin
        
        carrier = self.get_object()
        order_id = request.data.get('order_id')
        service_code = request.data.get('service_code')
        
        if not order_id:
            return Response(
                {'detail': 'order_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not service_code:
            return Response(
                {'detail': 'service_code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get order
        try:
            order = Order.objects.get(id=order_id, workspace=request.workspace)
        except Order.DoesNotExist:
            return Response(
                {'detail': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get sender address (default warehouse)
        warehouse = Warehouse.objects.filter(
            workspace=request.workspace,
            is_default=True,
            is_active=True
        ).first()
        
        if not warehouse:
            warehouse = Warehouse.objects.filter(
                workspace=request.workspace,
                is_active=True
            ).first()
        
        if not warehouse:
            return Response(
                {'detail': 'No warehouse configured'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get or create sender address from warehouse
        sender_address, _ = Address.objects.get_or_create(
            workspace=request.workspace,
            full_name=warehouse.name,
            address_line1=warehouse.address_line1,
            city=warehouse.city,
            postal_code=warehouse.postal_code,
            country=warehouse.country or 'NZ',
            defaults={
                'address_line2': warehouse.address_line2 or '',
                'state': warehouse.state or '',
                'phone': warehouse.phone or '',
                'email': warehouse.email or '',
            }
        )
        
        # Get recipient address from order
        recipient_address = order.shipping_address
        if not recipient_address:
            return Response(
                {'detail': 'Order has no shipping address'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get freight service (or create temp one from carrier)
        freight_service = FreightService.objects.filter(
            carrier=carrier,
            code=service_code,
            is_active=True
        ).first()
        
        if not freight_service:
            # Use default/first service from this carrier
            freight_service = FreightService.objects.filter(
                carrier=carrier,
                is_active=True
            ).first()
        
        if not freight_service:
            return Response(
                {'detail': f'No freight service configured for carrier {carrier.name}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create consignment
        delivery_service = DeliveryService(workspace=request.workspace, user=request.user)
        
        try:
            consignment = delivery_service.create_consignment(
                orders=[order],
                service=freight_service,
                sender_address=sender_address,
                recipient_address=recipient_address,
            )
            
            # Ship the consignment using carrier plugin
            ship_result = delivery_service.ship_consignment(
                consignment=consignment,
                service_code=service_code
            )
            
            if not ship_result.get('success'):
                return Response({
                    'success': False,
                    'consignment_number': consignment.consignment_number,
                    'error': ship_result.get('error', 'Failed to create shipment with carrier')
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Refresh consignment to get updated tracking
            consignment.refresh_from_db()
            
            return Response({
                'success': True,
                'consignment_id': consignment.id,
                'consignment_number': consignment.consignment_number,
                'tracking_number': consignment.tracking_number,
                'label_url': ship_result.get('label_url', ''),
                'carrier_name': carrier.name,
                'service_code': service_code,
            })
            
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class FreightServiceViewSet(viewsets.ModelViewSet):
    """Freight service management ViewSet (Staff)"""
    serializer_class = FreightServiceSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get freight services for current workspace"""
        queryset = FreightService.objects.filter(
            workspace=self.request.workspace
        ).select_related('carrier')
        
        # Filter by carrier if provided
        carrier_id = self.request.query_params.get('carrier')
        if carrier_id:
            queryset = queryset.filter(carrier_id=carrier_id)
        
        # Filter by active status
        active = self.request.query_params.get('active')
        if active == 'true':
            queryset = queryset.filter(is_active=True)
        
        return queryset.order_by('order', 'name')

    @action(detail=False, methods=['get'])
    def config_schema(self, request):
        """
        Return SchemaForm metadata for FreightService.config editor.
        Optional query: template=<id> to get only that template's form_schema.
        """
        template_id = request.query_params.get('template')
        if template_id:
            template = get_template(template_id)
            if not template:
                return Response(
                    {'detail': f'Unknown template: {template_id}'},
                    status=status.HTTP_404_NOT_FOUND
                )
            return Response({
                'form_schema': template.get('form_schema', []),
                'template': template,
            })
        return Response({
            'config_schema': get_freight_service_config_schema(),
            'form_schema': get_freight_service_form_schema(),
        })

    @action(detail=False, methods=['get'], url_path='templates')
    def templates_list(self, request):
        """Return all freight pricing templates (id, label, description, form_schema)."""
        return Response(get_all_templates())

    @action(detail=False, methods=['get'], permission_classes=[AllowAny], authentication_classes=[])
    def for_country(self, request):
        """
        Get active freight services for a specific country.
        Used by storefront checkout page.
        
        Query params:
            country: ISO country code (e.g., 'US', 'NZ')
        """
        from bfg.delivery.models import DeliveryZone
        
        country = request.query_params.get('country')
        if not country:
            return Response(
                {'detail': 'country parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not getattr(request, 'workspace', None):
            return Response(
                {'detail': 'Workspace is required. Send X-Workspace-ID header or use a configured domain.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Get active freight services
        queryset = FreightService.objects.filter(
            workspace=request.workspace,
            is_active=True
        ).select_related('carrier').prefetch_related('delivery_zones')
        
        # Filter by delivery zones that include this country
        delivery_zones = DeliveryZone.objects.filter(
            workspace=request.workspace,
            is_active=True,
            countries__contains=[country]
        )
        from django.db.models import Count
        # Freight services that either: (1) have no delivery zones (all countries),
        # or (2) have at least one zone containing this country. Avoid delivery_zones__in=[]
        # which can yield no results in some ORM versions.
        if delivery_zones.exists():
            queryset = queryset.filter(
                models.Q(delivery_zones__in=delivery_zones) | models.Q(delivery_zones__isnull=True)
            ).distinct()
        else:
            queryset = queryset.annotate(_dz_count=Count('delivery_zones')).filter(_dz_count=0)
        queryset = queryset.order_by('order', 'name')
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def perform_create(self, serializer):
        """Create freight service with workspace"""
        from bfg.common.services import AuditService
        
        freight_service = serializer.save(workspace=self.request.workspace)
        
        # Audit log
        audit = AuditService(workspace=self.request.workspace, user=self.request.user)
        description = f"Created freight service '{freight_service.name}' - Base price: {freight_service.base_price}, Price per kg: {freight_service.price_per_kg}"
        audit.log_create(
            freight_service,
            description=description,
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', '')
        )
    
    def perform_update(self, serializer):
        """Update freight service and log price changes"""
        from bfg.common.services import AuditService
        
        # Get old values before update
        old_instance = self.get_object()
        old_base_price = old_instance.base_price
        old_price_per_kg = old_instance.price_per_kg
        old_name = old_instance.name
        
        # Save updates
        freight_service = serializer.save()
        
        # Track changes
        changes = {}
        if old_base_price != freight_service.base_price:
            changes['base_price'] = {'old': str(old_base_price), 'new': str(freight_service.base_price)}
        if old_price_per_kg != freight_service.price_per_kg:
            changes['price_per_kg'] = {'old': str(old_price_per_kg), 'new': str(freight_service.price_per_kg)}
        if old_name != freight_service.name:
            changes['name'] = {'old': old_name, 'new': freight_service.name}
        
        # Audit log only if there are changes
        if changes:
            audit = AuditService(workspace=self.request.workspace, user=self.request.user)
            description = f"Updated freight service '{freight_service.name}'"
            if 'base_price' in changes or 'price_per_kg' in changes:
                description += f" - New prices: Base {freight_service.base_price}, Per kg {freight_service.price_per_kg}"
            
            audit.log_update(
                freight_service,
                changes=changes,
                description=description,
                ip_address=self.request.META.get('REMOTE_ADDR'),
                user_agent=self.request.META.get('HTTP_USER_AGENT', '')
            )


class PackagingTypeViewSet(viewsets.ModelViewSet):
    """Packaging type management ViewSet (Staff)"""
    serializer_class = PackagingTypeSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get packaging types for current workspace"""
        return PackagingType.objects.filter(
            workspace=self.request.workspace
        ).order_by('order', 'name')
    
    def perform_create(self, serializer):
        """Create packaging type with workspace"""
        serializer.save(workspace=self.request.workspace)


class ManifestViewSet(viewsets.ModelViewSet):
    """Manifest management ViewSet (Staff)"""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'retrieve':
            return ManifestDetailSerializer
        return ManifestListSerializer
    
    def get_queryset(self):
        """Get manifests for current workspace"""
        queryset = Manifest.objects.filter(
            workspace=self.request.workspace
        ).select_related('warehouse', 'carrier', 'status', 'created_by')
        
        # Filter by warehouse
        warehouse_id = self.request.query_params.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        # Filter by carrier
        carrier_id = self.request.query_params.get('carrier')
        if carrier_id:
            queryset = queryset.filter(carrier_id=carrier_id)
        
        # Filter by closed status
        closed = self.request.query_params.get('closed')
        if closed == 'true':
            queryset = queryset.filter(is_closed=True)
        elif closed == 'false':
            queryset = queryset.filter(is_closed=False)
        
        return queryset.order_by('-manifest_date', '-created_at')
    
    def perform_create(self, serializer):
        """Create manifest"""
        serializer.save(
            workspace=self.request.workspace,
            created_by=self.request.user
        )
    
    def perform_update(self, serializer):
        """
        Update manifest and cascade status changes to consignments.
        When manifest state changes to SHIPPED, all consignments are updated to matching state.
        """
        old_state = serializer.instance.state if serializer.instance else None
        manifest = serializer.save()
        new_state = manifest.state
        
        # Cascade status change to consignments
        if new_state != old_state and new_state == FreightState.SHIPPED.value:
            self._update_consignments_status(manifest, new_state)
    
    def _update_consignments_status(self, manifest, new_state: str):
        """
        Update all consignments in manifest to matching state.
        FreightStatus.state maps directly to FreightState values.
        """
        # Get matching consignment status by state
        consignment_status = FreightStatus.objects.filter(
            workspace=self.request.workspace,
            state=new_state,
            type='consignment'
        ).first()
        
        if not consignment_status:
            raise ValueError(f"FreightStatus for state '{new_state}' not found")
        
        # Update all consignments in this manifest
        Consignment.objects.filter(manifest=manifest).update(
            status=consignment_status,
            state=new_state
        )
    
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """
        Close manifest
        
        POST /api/v1/manifests/{id}/close/
        """
        manifest = self.get_object()
        
        service = ManifestService(
            workspace=request.workspace,
            user=request.user
        )
        
        manifest = service.close_manifest(manifest)
        
        serializer = self.get_serializer(manifest)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_consignment(self, request, pk=None):
        """
        Add consignment to manifest
        
        POST /api/v1/manifests/{id}/add_consignment/
        Body: {"consignment_id": 123}
        """
        manifest = self.get_object()
        consignment_id = request.data.get('consignment_id')
        
        if not consignment_id:
            return Response(
                {'detail': 'consignment_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            consignment = Consignment.objects.get(
                id=consignment_id,
                workspace=request.workspace
            )
            
            service = ManifestService(
                workspace=request.workspace,
                user=request.user
            )
            
            service.add_consignment_to_manifest(manifest, consignment)
            
            serializer = self.get_serializer(manifest)
            return Response(serializer.data)
            
        except Consignment.DoesNotExist:
            return Response(
                {'detail': 'Consignment not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class ConsignmentViewSet(viewsets.ModelViewSet):
    """Consignment management ViewSet (Staff)"""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    lookup_field = 'consignment_number'
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'create':
            from bfg.delivery.serializers import ConsignmentCreateSerializer
            return ConsignmentCreateSerializer
        if self.action == 'retrieve':
            return ConsignmentDetailSerializer
        return ConsignmentListSerializer
    
    def get_queryset(self):
        """Get consignments for current workspace"""
        queryset = Consignment.objects.filter(
            workspace=self.request.workspace
        ).select_related('service__carrier', 'status', 'manifest')
        
        # Filter by state
        state_filter = self.request.query_params.get('state')
        if state_filter:
            queryset = queryset.filter(state=state_filter)
        
        # Filter by manifest
        manifest_id = self.request.query_params.get('manifest')
        if manifest_id:
            queryset = queryset.filter(manifest_id=manifest_id)
        
        # Filter by tracking number
        tracking = self.request.query_params.get('tracking')
        if tracking:
            queryset = queryset.filter(tracking_number__icontains=tracking)
        
        # Filter by order
        order_id = self.request.query_params.get('order')
        if order_id:
            queryset = queryset.filter(orders__id=order_id)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create consignment using service"""
        from bfg.common.models import Address
        from bfg.delivery.models import FreightService, FreightStatus
        from bfg.delivery.services import DeliveryService
        from bfg.shop.models import Order
        
        # Get required objects
        service = FreightService.objects.get(
            id=serializer.validated_data['service_id'],
            carrier__workspace=self.request.workspace
        )
        sender_address = Address.objects.get(id=serializer.validated_data['sender_address_id'])
        recipient_address = Address.objects.get(id=serializer.validated_data['recipient_address_id'])
        status = FreightStatus.objects.get(
            id=serializer.validated_data['status_id'],
            workspace=self.request.workspace
        )
        
        # Get state (default to PENDING if not provided)
        state = serializer.validated_data.get('state', FreightState.PENDING.value)
        
        # Get orders if provided
        order_ids = serializer.validated_data.get('order_ids', [])
        orders = []
        if order_ids:
            orders = Order.objects.filter(
                id__in=order_ids,
                workspace=self.request.workspace
            )
        
        # Create consignment using service
        delivery_service = DeliveryService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        consignment = delivery_service.create_consignment(
            orders=list(orders),
            service=service,
            sender_address=sender_address,
            recipient_address=recipient_address,
            tracking_number=serializer.validated_data.get('tracking_number', ''),
            state=state,
            status=status,
            ship_date=serializer.validated_data.get('ship_date'),
            estimated_delivery=serializer.validated_data.get('estimated_delivery'),
            notes=serializer.validated_data.get('notes', ''),
        )
        
        serializer.instance = consignment
    
    def destroy(self, request, *args, **kwargs):
        """
        Delete consignment.
        Only allows deletion of consignments that haven't been shipped.
        If consignment has a tracking_number, attempts to cancel it with carrier first.
        """
        from bfg.delivery.carriers import get_carrier_plugin
        import logging
        
        logger = logging.getLogger(__name__)
        consignment = self.get_object()
        
        # Check if consignment can be deleted (not shipped/delivered)
        if consignment.state in [FreightState.SHIPPED.value, FreightState.DELIVERED.value]:
            return Response(
                {'detail': 'Cannot delete shipped or delivered consignments'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Try to cancel consignment with carrier if tracking_number exists
        if consignment.tracking_number:
            try:
                carrier = consignment.service.carrier
                plugin = get_carrier_plugin(carrier)
                
                if plugin:
                    cancel_result = plugin.cancel_consignment(consignment.tracking_number)
                    if not cancel_result.success:
                        # Log warning but continue with deletion
                        logger.warning(
                            f"Failed to cancel consignment {consignment.consignment_number} "
                            f"with carrier {carrier.name}: {cancel_result.error}"
                        )
                else:
                    logger.warning(
                        f"No plugin available for carrier {carrier.name} "
                        f"to cancel consignment {consignment.consignment_number}"
                    )
            except Exception as e:
                # Log error but continue with deletion
                logger.error(
                    f"Error cancelling consignment {consignment.consignment_number} with carrier: {e}",
                    exc_info=True
                )
        
        # Delete related packages first
        consignment.packages.all().delete()
        
        # Delete consignment
        consignment.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=False, methods=['delete'], url_path='by-id/(?P<id>[^/.]+)')
    def delete_by_id(self, request, id=None):
        """
        Delete consignment by ID.
        
        DELETE /api/v1/consignments/by-id/{id}/
        If consignment has a tracking_number, attempts to cancel it with carrier first.
        """
        from bfg.delivery.carriers import get_carrier_plugin
        import logging
        
        logger = logging.getLogger(__name__)
        
        try:
            consignment = Consignment.objects.get(
                id=id,
                workspace=request.workspace
            )
        except Consignment.DoesNotExist:
            return Response(
                {'detail': 'Consignment not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if consignment can be deleted
        if consignment.state in [FreightState.SHIPPED.value, FreightState.DELIVERED.value]:
            return Response(
                {'detail': 'Cannot delete shipped or delivered consignments'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Try to cancel consignment with carrier if tracking_number exists
        if consignment.tracking_number:
            try:
                carrier = consignment.service.carrier
                plugin = get_carrier_plugin(carrier)
                
                if plugin:
                    cancel_result = plugin.cancel_consignment(consignment.tracking_number)
                    if not cancel_result.success:
                        # Log warning but continue with deletion
                        logger.warning(
                            f"Failed to cancel consignment {consignment.consignment_number} "
                            f"with carrier {carrier.name}: {cancel_result.error}"
                        )
                else:
                    logger.warning(
                        f"No plugin available for carrier {carrier.name} "
                        f"to cancel consignment {consignment.consignment_number}"
                    )
            except Exception as e:
                # Log error but continue with deletion
                logger.error(
                    f"Error cancelling consignment {consignment.consignment_number} with carrier: {e}",
                    exc_info=True
                )
        
        # Delete related packages first
        consignment.packages.all().delete()
        
        # Delete consignment
        consignment.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['post'])
    def add_tracking_event(self, request, consignment_number=None):
        """
        Add tracking event
        
        POST /api/v1/consignments/{consignment_number}/add_tracking_event/
        Body: {
            "event_type": "in_transit",
            "description": "Package in transit",
            "location": "Auckland"
        }
        """
        consignment = self.get_object()
        
        service = DeliveryService(
            workspace=request.workspace,
            user=request.user
        )
        
        event_type = request.data.get('event_type')
        description = request.data.get('description')
        location = request.data.get('location', '')
        
        if not event_type or not description:
            return Response(
                {'detail': 'event_type and description are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        is_public = request.data.get('is_public', False)
        
        tracking_event = service.add_tracking_event(
            target=consignment,
            event_type=event_type,
            description=description,
            location=location,
            is_public=is_public,
            user=request.user
        )
        
        serializer = TrackingEventSerializer(tracking_event)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, consignment_number=None):
        """
        Update consignment status
        
        POST /api/v1/consignments/{consignment_number}/update_status/
        Body: {"status_id": 5}
        """
        consignment = self.get_object()
        status_id = request.data.get('status_id')
        
        if not status_id:
            return Response(
                {'detail': 'status_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            new_status = FreightStatus.objects.get(
                id=status_id,
                workspace=request.workspace,
                type='consignment'
            )
            
            service = DeliveryService(
                workspace=request.workspace,
                user=request.user
            )
            
            consignment = service.update_consignment_status(consignment, new_status)
            
            serializer = self.get_serializer(consignment)
            return Response(serializer.data)
            
        except FreightStatus.DoesNotExist:
            return Response(
                {'detail': 'Freight status not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'])
    def generate_label(self, request, consignment_number=None):
        """
        Generate shipping label for consignment
        
        POST /api/v1/consignments/{consignment_number}/generate_label/
        """
        from bfg.common.services import AuditService
        from bfg.delivery.services import DeliveryService
        
        consignment = self.get_object()
        
        service = DeliveryService(
            workspace=request.workspace,
            user=request.user
        )
        
        result = service.get_shipping_label(consignment)
        
        # Audit log
        audit = AuditService(workspace=request.workspace, user=request.user)
        if result.get('success'):
            description = f"Generated shipping label for consignment {consignment.consignment_number}"
            if consignment.tracking_number:
                description += f" (Tracking: {consignment.tracking_number})"
        else:
            description = f"Failed to generate shipping label for consignment {consignment.consignment_number}: {result.get('error', 'Unknown error')}"
        
        audit.log_action(
            'generate_label',
            consignment,
            description=description,
            changes={'label_url': result.get('label_url', '')} if result.get('success') else {},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        return Response(result, status=status.HTTP_200_OK if result.get('success') else status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, consignment_number=None):
        """
        Cancel consignment (and associated label)
        
        POST /api/v1/consignments/{consignment_number}/cancel/
        """
        from bfg.common.services import AuditService
        from bfg.delivery.models import FreightStatus, FreightState
        from bfg.delivery.services import DeliveryService
        
        consignment = self.get_object()
        
        # Save old state before update
        old_state = consignment.state
        
        # Get cancelled status
        try:
            cancelled_status = FreightStatus.objects.get(
                workspace=request.workspace,
                state=FreightState.CANCELLED.value,
                type='consignment'
            )
        except FreightStatus.DoesNotExist:
            return Response(
                {'detail': 'Cancelled status not found. Please create a cancelled status first.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        service = DeliveryService(
            workspace=request.workspace,
            user=request.user
        )
        
        consignment = service.update_consignment_status(consignment, cancelled_status)
        
        # Audit log
        audit = AuditService(workspace=request.workspace, user=request.user)
        description = f"Cancelled consignment {consignment.consignment_number}"
        if consignment.tracking_number:
            description += f" (Tracking: {consignment.tracking_number})"
        
        audit.log_action(
            'cancel',
            consignment,
            description=description,
            changes={'state': {'old': old_state, 'new': FreightState.CANCELLED.value}},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        serializer = self.get_serializer(consignment)
        return Response(serializer.data)


class PackageViewSet(viewsets.ModelViewSet):
    """Package management ViewSet (Staff)"""
    serializer_class = PackageSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get packages"""
        queryset = Package.objects.select_related('consignment', 'status')
        
        # Filter by consignment
        consignment_id = self.request.query_params.get('consignment')
        if consignment_id:
            queryset = queryset.filter(consignment_id=consignment_id)
        
        return queryset.order_by('-created_at')


class FreightStatusViewSet(viewsets.ModelViewSet):
    """Freight status management ViewSet (Admin)"""
    serializer_class = FreightStatusSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_queryset(self):
        """Get freight statuses for current workspace"""
        return FreightStatus.objects.filter(
            workspace=self.request.workspace
        ).order_by('type', 'order', 'name')
    
    def filter_queryset(self, queryset):
        """Apply filters manually"""
        queryset = super().filter_queryset(queryset)
        
        # Filter by type
        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)
            
        # Filter by code
        code_filter = self.request.query_params.get('code')
        if code_filter:
            queryset = queryset.filter(code=code_filter)
            
        # Filter by state
        state_filter = self.request.query_params.get('state')
        if state_filter:
            queryset = queryset.filter(state=state_filter)
            
        # Filter by active/public
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
             queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset
    
    def perform_create(self, serializer):
        """Create freight status with workspace"""
        serializer.save(workspace=self.request.workspace)


class DeliveryZoneViewSet(viewsets.ModelViewSet):
    """Delivery zone management ViewSet (Staff)"""
    serializer_class = DeliveryZoneSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get delivery zones for current workspace"""
        return DeliveryZone.objects.filter(
            workspace=self.request.workspace
        ).order_by('name')
    
    def perform_create(self, serializer):
        """Create delivery zone with workspace"""
        serializer.save(workspace=self.request.workspace)

    @action(detail=False, methods=['get'])
    def form_schema(self, request):
        """
        SchemaForm metadata for editing DeliveryZone coverage fields.
        """
        return Response({
            'form_schema': get_delivery_zone_form_schema(),
        })


class TrackingEventViewSet(viewsets.ModelViewSet):
    """Tracking event ViewSet (Staff)"""
    serializer_class = TrackingEventSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get tracking events filtered by consignment/package"""
        queryset = TrackingEvent.objects.select_related('content_type', 'workspace', 'created_by')
        
        consignment_id = self.request.query_params.get('consignment')
        if consignment_id:
            consignment_ct = ContentType.objects.get_for_model(Consignment)
            queryset = queryset.filter(content_type=consignment_ct, object_id=consignment_id)
        
        package_id = self.request.query_params.get('package')
        if package_id:
            package_ct = ContentType.objects.get_for_model(Package)
            queryset = queryset.filter(content_type=package_ct, object_id=package_id)
        
        return queryset.order_by('-event_time', '-created_at')


class PackageTemplateViewSet(viewsets.ModelViewSet):
    """
    Package template management ViewSet (Staff only)
    Predefined box sizes for quick selection when packing orders
    """
    serializer_class = PackageTemplateSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    http_method_names = ['get', 'post', 'patch', 'delete']
    pagination_class = None  # Return array directly without pagination
    
    def get_queryset(self):
        """Get package templates for workspace"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return PackageTemplate.objects.none()
        
        queryset = PackageTemplate.objects.filter(workspace=workspace)
        
        # Filter by active status
        active = self.request.query_params.get('active')
        if active == 'true':
            queryset = queryset.filter(is_active=True)
        
        return queryset.order_by('order', 'name')
    
    def perform_create(self, serializer):
        """Create template with workspace"""
        serializer.save(workspace=self.request.workspace)
