"""
BFG Common Module Serializers

Serializers for common module models
"""

from rest_framework import serializers
from bfg.common.models import (
    Workspace, Customer, Address, User, StaffRole, StaffMember, Settings,
    CustomerSegment, CustomerTag, UserPreferences, Media, MediaLink, EmailConfig
)



class UserSerializer(serializers.ModelSerializer):
    """User serializer"""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'phone', 'is_active']
        read_only_fields = ['id']


class WorkspaceSerializer(serializers.ModelSerializer):
    """Workspace serializer"""
    
    class Meta:
        model = Workspace
        fields = ['id', 'name', 'slug', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class StaffRoleSerializer(serializers.ModelSerializer):
    """Staff role serializer"""
    code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    
    class Meta:
        model = StaffRole
        fields = ['id', 'name', 'code', 'description', 'permissions', 'is_system', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_system', 'created_at', 'updated_at']


class StaffMemberSerializer(serializers.ModelSerializer):
    """Staff member serializer"""
    user = UserSerializer(read_only=True)
    role = StaffRoleSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    role_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = StaffMember
        fields = [
            'id', 'user', 'role', 'user_id', 'role_id',
            'is_active', 'joined_at', 'created_at'
        ]
        read_only_fields = ['id', 'joined_at', 'created_at']


class CustomerListSerializer(serializers.ModelSerializer):
    """Customer list serializer (concise)"""
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    user_email = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = [
            'id', 'workspace', 'user', 'user_id', 'user_email', 'customer_number',
            'company_name', 'tax_number', 'credit_limit', 'balance',
            'is_active', 'is_verified', 'created_at'
        ]
        read_only_fields = ['id', 'workspace', 'customer_number', 'created_at']
    
    def get_user_email(self, obj):
        """Get user email for display"""
        return obj.user.email if obj.user else None


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Customer detail serializer (full)"""
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    segments = serializers.SerializerMethodField()
    experience_points = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = [
            'id', 'workspace', 'user', 'user_id', 'customer_number',
            'company_name', 'tax_number', 'credit_limit', 'balance',
            'is_active', 'is_verified', 'verified_at', 'notes',
            'segments', 'experience_points', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'workspace', 'customer_number', 'balance', 'created_at', 'updated_at']
    
    def get_segments(self, obj):
        """Get customer segments that match this customer"""
        # Get all active segments for this workspace
        segments = CustomerSegment.objects.filter(
            workspace=obj.workspace,
            is_active=True
        )
        
        # For now, return all active segments
        # TODO: Implement query evaluation to match customer against segment rules
        # This would require evaluating the JSON query rules against customer data
        return CustomerSegmentSerializer(segments, many=True).data
    
    def get_experience_points(self, obj):
        """Calculate experience points based on completed orders and total spent"""
        try:
            from bfg.shop.models import Order
            from django.db.models import Sum, Count
            from decimal import Decimal
            
            # Get completed orders count and total spent
            completed_orders = Order.objects.filter(
                customer=obj,
                workspace=obj.workspace,
                status__in=['delivered', 'completed', 'paid']
            )
            
            order_count = completed_orders.count()
            total_spent_result = completed_orders.aggregate(total=Sum('total'))
            total_spent = total_spent_result.get('total') or Decimal('0')
            
            # Calculate experience points:
            # - 100 points per completed order
            # - 1 point per dollar spent (rounded to integer)
            points_from_orders = order_count * 100
            points_from_spent = int(float(total_spent))
            
            return points_from_orders + points_from_spent
        except Exception:
            # Return 0 if shop module not available or calculation fails
            return 0


class AddressSerializer(serializers.ModelSerializer):
    """Address serializer"""
    customer_id = serializers.IntegerField(write_only=True, required=False)
    
    class Meta:
        model = Address
        fields = [
            'id', 'customer_id', 'full_name', 'phone', 'email', 'company',
            'address_line1', 'address_line2',
            'city', 'state', 'postal_code', 'country',
            'latitude', 'longitude', 'notes',
            'is_default', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate(self, data):
        """
        Validate address data
        """
        # For partial updates (PATCH), only validate fields that are being updated
        # For full updates (PUT), ensure required fields are present
        if self.partial:
            # Partial update - only validate if field is being updated
            if 'address_line1' in data and not data.get('address_line1'):
                raise serializers.ValidationError({
                    'address_line1': 'This field cannot be empty'
                })
            if 'city' in data and not data.get('city'):
                raise serializers.ValidationError({
                    'city': 'This field cannot be empty'
                })
        else:
            # Full update - ensure required fields are present
            if not data.get('address_line1'):
                raise serializers.ValidationError({
                    'address_line1': 'This field is required'
                })
            if not data.get('city'):
                raise serializers.ValidationError({
                    'city': 'This field is required'
                })
        # Country is optional, no validation needed
        
        return data


class SettingsSerializer(serializers.ModelSerializer):
    """Settings serializer. On update, syncs custom_settings.general to model fields."""
    
    class Meta:
        model = Settings
        fields = [
            'id', 'site_name', 'site_description', 'logo', 'favicon',
            'default_language', 'supported_languages', 'default_currency',
            'default_timezone', 'contact_email', 'support_email',
            'contact_phone', 'facebook_url', 'twitter_url', 'instagram_url',
            'features', 'custom_settings', 'updated_at'
        ]
        read_only_fields = ['id', 'updated_at']

    def update(self, instance, validated_data):
        custom_settings = validated_data.pop('custom_settings', None)
        if custom_settings is not None and isinstance(custom_settings, dict):
            general = custom_settings.get('general') or {}
            sync_keys = [
                'site_name', 'site_description', 'default_language', 'default_currency',
                'default_timezone', 'contact_email', 'contact_phone',
                'facebook_url', 'twitter_url', 'instagram_url',
            ]
            for key in sync_keys:
                if hasattr(instance, key):
                    setattr(instance, key, general.get(key, getattr(instance, key, '')) or '')
            validated_data['custom_settings'] = custom_settings
        return super().update(instance, validated_data)
    
    def validate_supported_languages(self, value):
        """Validate supported languages is a list"""
        if not isinstance(value, list):
            raise serializers.ValidationError('Supported languages must be a list')
        return value
    
    def validate_features(self, value):
        """Validate features is a dict"""
        if not isinstance(value, dict):
            raise serializers.ValidationError('Features must be a dictionary')
        return value


def _get_backend_schema(backend_type):
    """Return backend class and its config_schema from registry."""
    from bfg.common.email_backends import get_backend
    try:
        backend_class = get_backend(backend_type)
        return backend_class, getattr(backend_class, 'config_schema', {})
    except KeyError:
        return None, {}


def _mask_sensitive_config(config, backend_type):
    """Return config copy with sensitive fields masked using backend SchemaConfig."""
    if not config or not isinstance(config, dict):
        return config or {}
    _, schema = _get_backend_schema(backend_type)
    out = dict(config)
    for key, field_schema in schema.items():
        if field_schema.get('sensitive') and key in out and out[key]:
            out[key] = '********'
    return out


def _validate_config_for_backend(backend_type, config):
    """Validate config using backend SchemaConfig (required fields, types)."""
    if not isinstance(config, dict):
        raise serializers.ValidationError({'config': 'Must be an object.'})
    backend_class, schema = _get_backend_schema(backend_type)
    if backend_class is None:
        raise serializers.ValidationError({'backend_type': f'Unknown backend: {backend_type}'})
    for key, field_schema in schema.items():
        if not field_schema.get('required'):
            continue
        if not config.get(key):
            raise serializers.ValidationError({'config': f'{key} is required for {backend_type}.'})
    if backend_type == 'smtp' and 'port' in config:
        try:
            int(config.get('port', 25))
        except (TypeError, ValueError):
            raise serializers.ValidationError({'config': 'SMTP port must be a number.'})


class EmailConfigSerializer(serializers.ModelSerializer):
    """EmailConfig serializer. Masks password/api_key on read; validates config by backend_type."""

    config = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = EmailConfig
        fields = ['id', 'name', 'backend_type', 'config', 'is_active', 'is_default', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret['config'] = _mask_sensitive_config(instance.config or {}, instance.backend_type)
        return ret

    def validate(self, data):
        backend_type = data.get('backend_type') or (self.instance.backend_type if self.instance else None)
        config = data.get('config')
        if config is not None and backend_type:
            _validate_config_for_backend(backend_type, config)
        return data

    def create(self, validated_data):
        config = validated_data.pop('config', {}) or {}
        instance = super().create(validated_data)
        instance.config = config
        instance.save(update_fields=['config'])
        return instance

    def update(self, instance, validated_data):
        if 'config' in validated_data:
            new_config = validated_data.pop('config') or {}
            existing = instance.config or {}
            _, schema = _get_backend_schema(instance.backend_type)
            for key, field_schema in schema.items():
                if field_schema.get('sensitive') and new_config.get(key) == '********':
                    new_config[key] = existing.get(key) or ''
            instance.config = new_config
        return super().update(instance, validated_data)


class CustomerSegmentSerializer(serializers.ModelSerializer):
    """Customer segment serializer"""
    customer_count = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomerSegment
        fields = [
            'id', 'name', 'query', 'is_active', 'customer_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_customer_count(self, obj):
        """Get number of customers matching this segment"""
        # This would need to be implemented based on query evaluation
        return obj.customers.count() if hasattr(obj, 'customers') else 0


class CustomerTagSerializer(serializers.ModelSerializer):
    """Customer tag serializer"""
    customer_count = serializers.IntegerField(
        source='customers.count', read_only=True
    )
    
    class Meta:
        model = CustomerTag
        fields = ['id', 'name', 'customer_count', 'created_at']
        read_only_fields = ['id', 'created_at']


class MeSerializer(serializers.ModelSerializer):
    """Me serializer - combines User and Customer info"""
    customer = CustomerDetailSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'phone',
            'avatar', 'language', 'timezone_name', 'customer', 'is_active'
        ]
        read_only_fields = ['id', 'is_active']
        extra_kwargs = {'avatar': {'required': False, 'allow_null': True}}

    def update(self, instance, validated_data):
        # Clear avatar when null (model may not have null=True on ImageField)
        if 'avatar' in validated_data and validated_data['avatar'] is None:
            if instance.avatar:
                instance.avatar.delete(save=False)
            validated_data['avatar'] = ''
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        """Add customer info to representation"""
        data = super().to_representation(instance)
        
        # Get customer for current workspace
        request = self.context.get('request')
        if request and hasattr(request, 'workspace'):
            from bfg.common.models import Customer
            from bfg.common.services import CustomerService
            
            service = CustomerService(
                workspace=request.workspace,
                user=request.user
            )
            customer = service.get_customer_by_user(instance, request.workspace)
            if customer:
                data['customer'] = CustomerDetailSerializer(customer, context=self.context).data
            else:
                data['customer'] = None
        
        return data


class ChangePasswordSerializer(serializers.Serializer):
    """Change password serializer"""
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, min_length=8)
    confirm_password = serializers.CharField(required=True, write_only=True)
    
    def validate(self, attrs):
        """Validate password change"""
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({
                'confirm_password': 'New password and confirm password do not match'
            })
        return attrs
    
    def validate_old_password(self, value):
        """Validate old password"""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Old password is incorrect')
        return value


class ResetPasswordSerializer(serializers.Serializer):
    """Reset password serializer - request password reset"""
    email = serializers.EmailField(required=True)
    
    def validate_email(self, value):
        """Validate email exists"""
        from bfg.common.models import User
        try:
            User.objects.get(email=value, is_active=True)
        except User.DoesNotExist:
            # Don't reveal if email exists for security
            pass
        return value


class UserPreferencesSerializer(serializers.ModelSerializer):
    """User preferences serializer"""
    
    class Meta:
        model = UserPreferences
        fields = [
            'email_notifications', 'sms_notifications', 'push_notifications',
            'notify_order_updates', 'notify_promotions', 'notify_product_updates',
            'notify_support_replies',
            'profile_visibility', 'show_email', 'show_phone',
            'theme', 'items_per_page', 'custom_preferences'
        ]
        read_only_fields = []


class MediaSerializer(serializers.ModelSerializer):
    """Media serializer"""
    file = serializers.SerializerMethodField()
    
    class Meta:
        model = Media
        fields = ['id', 'workspace', 'file', 'external_url', 'media_type', 'alt_text', 'width', 'height', 'uploaded_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_file(self, obj):
        """Get full file URL"""
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None


class MediaLinkSerializer(serializers.ModelSerializer):
    """Generic MediaLink serializer - references Media object"""
    # Include media fields for convenience
    file = serializers.SerializerMethodField()
    external_url = serializers.SerializerMethodField()
    media_type = serializers.SerializerMethodField()
    alt_text = serializers.SerializerMethodField()
    width = serializers.SerializerMethodField()
    height = serializers.SerializerMethodField()
    media_id = serializers.IntegerField(source='media.id', read_only=True)
    media = MediaSerializer(read_only=True)
    
    # Content object fields (for display)
    content_type_name = serializers.CharField(source='content_type.model', read_only=True)
    object_id_field = serializers.IntegerField(source='object_id', read_only=True)
    
    class Meta:
        model = MediaLink
        fields = [
            'id', 'media_id', 'media', 'media_type', 'file', 'external_url', 'alt_text',
            'width', 'height', 'position', 'description',
            'content_type_name', 'object_id_field',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_file(self, obj):
        """Get full file URL"""
        if obj.media and obj.media.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.media.file.url)
            return obj.media.file.url
        return None
    
    def get_external_url(self, obj):
        """Get external URL if media has one"""
        return obj.media.external_url if obj.media else None
    
    def get_media_type(self, obj):
        """Get media type"""
        return obj.media.media_type if obj.media else None
    
    def get_alt_text(self, obj):
        """Get alt text from media"""
        return obj.media.alt_text if obj.media else None
    
    def get_width(self, obj):
        """Get image width"""
        return obj.media.width if obj.media else None
    
    def get_height(self, obj):
        """Get image height"""
        return obj.media.height if obj.media else None
