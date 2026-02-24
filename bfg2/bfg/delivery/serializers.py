"""
BFG Delivery Module Serializers

Serializers for delivery module models
"""

from rest_framework import serializers
from pydantic import ValidationError as PydanticValidationError

from bfg.core.schema_convert import validation_error_to_message
from bfg.delivery.models import (
    Warehouse, Carrier, FreightService, DeliveryZone,
    Manifest, Consignment, Package, TrackingEvent, FreightStatus, PackagingType,
    PackageTemplate
)
from bfg.delivery.schemas import (
    CarrierConfigModel,
    DeliveryZoneConfigModel,
    FreightServiceConfigModel,
    prepare_freight_config_payload,
    form_params_to_config,
)


class WarehouseSerializer(serializers.ModelSerializer):
    """Warehouse serializer"""
    
    class Meta:
        model = Warehouse
        fields = [
            'id', 'name', 'code', 'address_line1', 'address_line2',
            'city', 'state', 'postal_code', 'country', 'latitude', 'longitude',
            'phone', 'email', 'is_active', 'is_default', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'address_line1': {'required': False},
            'city': {'required': False},
            'postal_code': {'required': False},
            'country': {'required': False},
        }


class CarrierSerializer(serializers.ModelSerializer):
    """Carrier serializer"""
    
    class Meta:
        model = Carrier
        fields = [
            'id', 'name', 'code', 'carrier_type', 'config', 'test_config',
            'is_test_mode', 'tracking_url_template', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    @staticmethod
    def _validate_config_payload(value):
        if value in (None, ''):
            return {}
        try:
            CarrierConfigModel.model_validate(value)
        except PydanticValidationError as exc:
            raise serializers.ValidationError(validation_error_to_message(exc))
        return value

    def validate_config(self, value):
        """Validate live carrier config."""
        return self._validate_config_payload(value)

    def validate_test_config(self, value):
        """Validate test carrier config."""
        return self._validate_config_payload(value)


class PackagingTypeSerializer(serializers.ModelSerializer):
    """Packaging type serializer"""
    
    class Meta:
        model = PackagingType
        fields = [
            'id', 'code', 'name', 'description', 'order', 'is_active'
        ]
        read_only_fields = ['id']


class FreightServiceSerializer(serializers.ModelSerializer):
    """Freight service serializer. Accepts template_id + template_params to build config."""
    carrier_name = serializers.CharField(source='carrier.name', read_only=True)
    template_id = serializers.CharField(required=False, write_only=True, allow_blank=True)
    template_params = serializers.JSONField(required=False, write_only=True)

    class Meta:
        model = FreightService
        fields = [
            'id', 'carrier', 'carrier_name', 'name', 'code', 'description',
            'base_price', 'price_per_kg', 'estimated_days_min',
            'estimated_days_max', 'is_active', 'order', 'config',
            'template_id', 'template_params',
        ]
        read_only_fields = ['id']

    def validate_config(self, value):
        """Validate FreightService.config JSON (used when not saving via template)."""
        if value in (None, ''):
            return {}
        try:
            prepared = prepare_freight_config_payload(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        try:
            model = FreightServiceConfigModel.model_validate(prepared)
        except PydanticValidationError as exc:
            raise serializers.ValidationError(validation_error_to_message(exc))
        return model.model_dump(exclude_none=True)

    def validate(self, attrs):
        """If template_id + template_params provided, build config and set base_price/price_per_kg."""
        template_id = (attrs.pop('template_id', None) or '').strip()
        template_params = attrs.pop('template_params', None) or {}
        if template_id and isinstance(template_params, dict):
            try:
                config, base_price, price_per_kg = form_params_to_config(
                    template_id.strip(), template_params
                )
            except ValueError as e:
                raise serializers.ValidationError({'template_params': str(e)})
            attrs['config'] = config
            attrs['base_price'] = base_price
            attrs['price_per_kg'] = price_per_kg
        return attrs


class FreightStatusSerializer(serializers.ModelSerializer):
    """Freight status serializer"""
    state = serializers.CharField()  # ensure enum -> string
    
    class Meta:
        model = FreightStatus
        fields = [
            'id', 'code', 'name', 'type', 'state', 'description',
            'color', 'order', 'is_active'
        ]
        read_only_fields = ['id']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if 'state' in data and data['state'] is not None:
            data['state'] = str(data['state'])
        return data


class TrackingEventSerializer(serializers.ModelSerializer):
    """Tracking event serializer"""
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    target_type = serializers.CharField(source='content_type.model', read_only=True)
    target_id = serializers.IntegerField(source='object_id', read_only=True)
    
    class Meta:
        model = TrackingEvent
        fields = [
            'id', 'event_type', 'event_type_display', 'description', 
            'location', 'event_time', 'is_public', 'created_at',
            'target_type', 'target_id'
        ]
        read_only_fields = ['id', 'created_at', 'event_type_display', 'target_type', 'target_id']


class PackageSerializer(serializers.ModelSerializer):
    """Package serializer"""
    status_name = serializers.CharField(source='status.name', read_only=True)
    
    class Meta:
        model = Package
        fields = [
            'id', 'package_number', 'weight', 'length', 'width', 'height', 'pieces',
            'state', 'status', 'status_name', 'description', 'created_at'
        ]
        read_only_fields = ['id', 'package_number', 'created_at']


class ConsignmentListSerializer(serializers.ModelSerializer):
    """Consignment list serializer (concise)"""
    service_name = serializers.CharField(source='service.name', read_only=True)
    carrier_name = serializers.CharField(source='service.carrier.name', read_only=True)
    status_name = serializers.CharField(source='status.name', read_only=True)
    package_count = serializers.SerializerMethodField()
    state = serializers.CharField()  # Serialize as string, not Enum
    
    class Meta:
        model = Consignment
        fields = [
            'id', 'consignment_number', 'tracking_number',
            'service', 'service_name', 'carrier_name',
            'state', 'status', 'status_name', 'package_count',
            'ship_date', 'estimated_delivery', 'actual_delivery',
            'created_at'
        ]
        read_only_fields = ['id', 'consignment_number', 'created_at']
    
    def get_package_count(self, obj):
        """Get package count"""
        return obj.packages.count()
    
    def to_representation(self, instance):
        """Convert state to string for JSON serialization"""
        ret = super().to_representation(instance)
        if 'state' in ret:
            # Ensure state is a string value, not Enum
            ret['state'] = str(ret['state'])
        return ret


class ConsignmentCreateSerializer(serializers.ModelSerializer):
    """Consignment create serializer"""
    service_id = serializers.IntegerField(write_only=True, required=True)
    sender_address_id = serializers.IntegerField(write_only=True, required=True)
    recipient_address_id = serializers.IntegerField(write_only=True, required=True)
    status_id = serializers.IntegerField(write_only=True, required=True)
    order_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    # Read fields for response
    id = serializers.IntegerField(read_only=True)
    consignment_number = serializers.CharField(read_only=True)
    service = serializers.IntegerField(source='service.id', read_only=True)
    sender_address = serializers.IntegerField(source='sender_address.id', read_only=True)
    recipient_address = serializers.IntegerField(source='recipient_address.id', read_only=True)
    status = serializers.IntegerField(source='status.id', read_only=True)
    state = serializers.CharField(read_only=True)  # Serialize as string, not Enum
    
    class Meta:
        model = Consignment
        fields = [
            'id', 'consignment_number', 'service', 'service_id',
            'sender_address', 'sender_address_id',
            'recipient_address', 'recipient_address_id',
            'status', 'status_id', 'state', 'tracking_number',
            'ship_date', 'estimated_delivery', 'order_ids',
            'created_at'
        ]
        read_only_fields = ['id', 'consignment_number', 'service', 'sender_address',
                           'recipient_address', 'status', 'state', 'created_at']
    
    def to_representation(self, instance):
        """Convert state to string for JSON serialization"""
        ret = super().to_representation(instance)
        if 'state' in ret:
            # Ensure state is a string value, not Enum
            ret['state'] = str(ret['state'])
        return ret
    
    def validate(self, data):
        """Validate consignment data"""
        # Validate state if provided
        if 'state' in data:
            from bfg.delivery.models import FreightState
            valid_states = [choice[0] for choice in FreightState.choices()]
            if data['state'] not in valid_states:
                raise serializers.ValidationError({
                    'state': f'State must be one of: {", ".join(valid_states)}'
                })
        return data


class ConsignmentDetailSerializer(serializers.ModelSerializer):
    """Consignment detail serializer (full)"""
    service_name = serializers.CharField(source='service.name', read_only=True)
    carrier_name = serializers.CharField(source='service.carrier.name', read_only=True)
    status_name = serializers.CharField(source='status.name', read_only=True)
    packages = PackageSerializer(many=True, read_only=True)
    tracking_events = TrackingEventSerializer(many=True, read_only=True)
    order_ids = serializers.SerializerMethodField()
    
    class Meta:
        model = Consignment
        fields = [
            'id', 'consignment_number', 'tracking_number', 'manifest',
            'service', 'service_name', 'carrier_name',
            'sender_address', 'recipient_address',
            'state', 'status', 'status_name',
            'ship_date', 'estimated_delivery', 'actual_delivery',
            'packages', 'tracking_events', 'order_ids',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'consignment_number', 'created_at', 'updated_at']
    
    def get_order_ids(self, obj):
        """Get linked order IDs"""
        return list(obj.orders.values_list('id', flat=True))


class ManifestListSerializer(serializers.ModelSerializer):
    """Manifest list serializer (concise)"""
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    carrier_name = serializers.CharField(source='carrier.name', read_only=True)
    status_name = serializers.CharField(source='status.name', read_only=True)
    consignment_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Manifest
        fields = [
            'id', 'manifest_number', 'warehouse', 'warehouse_name',
            'carrier', 'carrier_name', 'manifest_date', 'pickup_date',
            'state', 'status', 'status_name', 'is_closed',
            'consignment_count', 'created_at'
        ]
        read_only_fields = ['id', 'manifest_number', 'created_at']
    
    def get_consignment_count(self, obj):
        """Get consignment count"""
        return obj.consignments.count()


class ManifestDetailSerializer(serializers.ModelSerializer):
    """Manifest detail serializer (full)"""
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    carrier_name = serializers.CharField(source='carrier.name', read_only=True)
    status_name = serializers.CharField(source='status.name', read_only=True)
    consignments = ConsignmentListSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = Manifest
        fields = [
            'id', 'manifest_number', 'warehouse', 'warehouse_name',
            'carrier', 'carrier_name', 'manifest_date', 'pickup_date',
            'state', 'status', 'status_name', 'is_closed', 'notes',
            'consignments', 'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'manifest_number', 'created_by', 'created_at', 'updated_at'
        ]


class DeliveryZoneSerializer(serializers.ModelSerializer):
    """Delivery zone serializer"""
    
    class Meta:
        model = DeliveryZone
        fields = [
            'id', 'name', 'code', 'countries', 'postal_code_patterns',
            'is_active'
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        """Validate country/pattern lists via Pydantic."""
        attrs = super().validate(attrs)
        payload = {
            'countries': attrs.get('countries', getattr(self.instance, 'countries', [])),
            'postal_code_patterns': attrs.get('postal_code_patterns', getattr(self.instance, 'postal_code_patterns', [])),
        }
        try:
            validated = DeliveryZoneConfigModel.model_validate(payload)
        except PydanticValidationError as exc:
            raise serializers.ValidationError(validation_error_to_message(exc))
        attrs['countries'] = validated.countries
        attrs['postal_code_patterns'] = validated.postal_code_patterns
        return attrs


class PackageTemplateSerializer(serializers.ModelSerializer):
    """Package template serializer for predefined box sizes"""
    volume_cm3 = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    
    class Meta:
        model = PackageTemplate
        fields = [
            'id', 'code', 'name', 'description',
            'length', 'width', 'height',
            'tare_weight', 'max_weight',
            'volume_cm3', 'order', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'volume_cm3', 'created_at', 'updated_at']


