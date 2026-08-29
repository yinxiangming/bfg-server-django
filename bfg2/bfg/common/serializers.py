"""
BFG Common Module Serializers

Serializers for common module models
"""

from rest_framework import serializers
from bfg.common.models import (
    Workspace, Customer, Address, User, StaffRole, StaffMember, Settings,
    CustomerSegment, CustomerTag, UserPreferences, Media, MediaLink, EmailConfig,
    APIKey, Invitation,
)
from django.conf import settings

# What counts as money the customer actually spent. Keyed on `payment_status`,
# not `status`: `Order.STATUS_CHOICES` has no "paid" or "completed" member, so
# the status-based tuple this replaces could only ever match "delivered" and
# ignored every paid order still in flight. Shared by the list serializer's
# `total_spent` and the detail serializer's `experience_points` so the two
# figures can never drift apart.
SPEND_PAYMENT_STATUS = 'paid'


class UserSerializer(serializers.ModelSerializer):
    """Basic user serializer"""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'phone', 'language', 'is_active']
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
    permissions_match_default = serializers.SerializerMethodField()

    class Meta:
        model = StaffRole
        fields = [
            'id', 'name', 'code', 'description',
            'permissions', 'default_permissions',
            'permissions_match_default',
            'owner_module',
            'is_system', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'is_system', 'default_permissions', 'owner_module',
            'permissions_match_default', 'created_at', 'updated_at',
        ]

    def get_permissions_match_default(self, obj: StaffRole) -> bool:
        if not obj.is_system or not obj.default_permissions:
            return False
        return obj.permissions == obj.default_permissions


class StaffMemberSerializer(serializers.ModelSerializer):
    """Staff member serializer"""
    user = UserSerializer(read_only=True)
    role = StaffRoleSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    role_id = serializers.IntegerField(write_only=True)
    joined_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = StaffMember
        fields = [
            'id', 'user', 'role', 'user_id', 'role_id',
            'is_active', 'joined_at', 'created_at'
        ]
        read_only_fields = ['id', 'joined_at', 'created_at']


class InvitationSerializer(serializers.ModelSerializer):
    """Read serializer for staff invitations (admin view)."""
    role = StaffRoleSerializer(read_only=True)
    role_id = serializers.IntegerField(write_only=True, required=False)
    invited_by = UserSerializer(read_only=True)
    accepted_by = UserSerializer(read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = [
            'id', 'uuid', 'email', 'role', 'role_id', 'status',
            'invited_by', 'accepted_by',
            'expires_at', 'accepted_at', 'revoked_at',
            'message', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'uuid', 'status', 'invited_by', 'accepted_by',
            'expires_at', 'accepted_at', 'revoked_at',
            'created_at', 'updated_at',
        ]

    def get_status(self, obj: Invitation) -> str:
        return obj.effective_status()


class InvitationCreateSerializer(serializers.Serializer):
    """Write serializer for invite creation. Accepts a single email or a list."""
    email = serializers.EmailField(required=False)
    emails = serializers.ListField(
        child=serializers.EmailField(), required=False, max_length=100
    )
    role_id = serializers.IntegerField(required=True)
    expiry_hours = serializers.IntegerField(
        required=False, min_value=1, max_value=24 * 14
    )
    message = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        emails = attrs.get('emails') or []
        single = attrs.get('email')
        if single:
            emails = [*emails, single]
        emails = [e.strip().lower() for e in emails if e and e.strip()]
        # de-dupe while preserving order
        seen = set()
        deduped = []
        for e in emails:
            if e not in seen:
                seen.add(e)
                deduped.append(e)
        if not deduped:
            raise serializers.ValidationError({"email": "Provide at least one email."})
        if len(deduped) > 100:
            raise serializers.ValidationError(
                {"emails": "Cannot invite more than 100 recipients in one request."}
            )
        attrs['_emails'] = deduped
        return attrs


class InvitationPreviewSerializer(serializers.Serializer):
    """Public preview shown on the accept page before login/signup."""
    workspace = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    email = serializers.EmailField()
    invited_by = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    expires_at = serializers.DateTimeField()
    message = serializers.CharField()

    def get_workspace(self, obj: Invitation):
        return {"id": obj.workspace_id, "name": obj.workspace.name, "slug": obj.workspace.slug}

    def get_role(self, obj: Invitation):
        return {"id": obj.role_id, "name": obj.role.name, "code": obj.role.code}

    def get_invited_by(self, obj: Invitation):
        if not obj.invited_by:
            return None
        full = obj.invited_by.get_full_name() or obj.invited_by.email
        return {"id": obj.invited_by_id, "name": full, "email": obj.invited_by.email}

    def get_status(self, obj: Invitation):
        return obj.effective_status()


class CustomerListSerializer(serializers.ModelSerializer):
    """Customer list serializer (concise)"""
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    user_email = serializers.SerializerMethodField()
    last_login = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'workspace', 'user', 'user_id', 'user_email', 'customer_number',
            'company_name', 'tax_number', 'credit_limit', 'balance',
            'is_active', 'is_verified', 'created_at', 'last_login', 'total_spent'
        ]
        read_only_fields = ['id', 'workspace', 'customer_number', 'created_at']
    
    def get_user_email(self, obj):
        """Get user email for display"""
        return obj.user.email if obj.user else None

    def get_last_login(self, obj):
        """Last time this customer signed in (admin list column)."""
        return obj.user.last_login if obj.user else None

    def get_total_spent(self, obj):
        """Money spent across orders whose payment reached ``SPEND_PAYMENT_STATUS``.

        ``CustomerViewSet`` annotates this on the list queryset; the fallback
        below keeps the serializer correct (just slower) if it is ever used on
        an un-annotated queryset.
        """
        annotated = getattr(obj, 'total_spent', None)
        if annotated is not None:
            return annotated
        from decimal import Decimal

        from django.db.models import Sum

        from bfg.shop.models import Order

        total = Order.objects.filter(
            customer=obj,
            workspace=obj.workspace,
            payment_status=SPEND_PAYMENT_STATUS,
        ).aggregate(total=Sum('total'))['total']
        return total or Decimal('0')


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Customer detail serializer (full)"""
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    segments = serializers.SerializerMethodField()
    experience_points = serializers.SerializerMethodField()
    addresses = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = [
            'id', 'workspace', 'user', 'user_id', 'customer_number',
            'company_name', 'tax_number', 'credit_limit', 'balance',
            'is_active', 'is_verified', 'verified_at', 'notes',
            'segments', 'experience_points', 'addresses', 'created_at', 'updated_at'
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
                payment_status=SPEND_PAYMENT_STATUS
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

    def get_addresses(self, obj):
        """Addresses linked to this customer (GenericRelation)."""
        # AddressSerializer is defined below in this module
        return AddressSerializer(
            obj.addresses.all().order_by('-is_default', '-created_at'),
            many=True,
        ).data


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
            'id', 'workspace_id', 'site_name', 'site_description', 'logo', 'favicon',
            'default_language', 'supported_languages', 'default_currency',
            'default_timezone', 'contact_email', 'support_email',
            'contact_phone', 'facebook_url', 'twitter_url', 'instagram_url',
            'features', 'custom_settings', 'updated_at'
        ]
        read_only_fields = ['id', 'workspace_id', 'updated_at']

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
            'avatar', 'language', 'timezone_name', 'customer', 'is_active',
            'is_staff', 'is_superuser'
        ]
        read_only_fields = ['id', 'is_active', 'is_staff', 'is_superuser']
        extra_kwargs = {'avatar': {'required': False, 'allow_null': True}}

    def update(self, instance, validated_data):
        # Clear avatar when null (model may not have null=True on ImageField)
        if 'avatar' in validated_data and validated_data['avatar'] is None:
            if instance.avatar:
                instance.avatar.delete(save=False)
            validated_data['avatar'] = ''
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        """Add customer and staff_member info to representation"""
        data = super().to_representation(instance)

        request = self.context.get('request')
        if request and hasattr(request, 'workspace'):
            from bfg.common.models import Customer, StaffMember
            from bfg.common.services import CustomerService

            # Customer info
            service = CustomerService(
                workspace=request.workspace,
                user=request.user
            )
            customer = service.get_customer_by_user(instance, request.workspace)
            if customer:
                data['customer'] = CustomerDetailSerializer(customer, context=self.context).data
            else:
                data['customer'] = None

            # Staff member + role + permissions for current workspace
            try:
                staff = StaffMember.all_objects.select_related('role').get(
                    workspace=request.workspace,
                    user=instance,
                    is_active=True
                )
                data['staff_member'] = {
                    'id': staff.id,
                    'is_active': staff.is_active,
                    'role': {
                        'id': staff.role.id,
                        'code': staff.role.code,
                        'name': staff.role.name,
                        'permissions': staff.role.permissions,
                    },
                }
            except StaffMember.DoesNotExist:
                data['staff_member'] = None

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


def media_file_url_for_serializer(media_obj, request=None):
    """
    Build media file URL from stored file.name so it matches DB path.
    Using file.url can yield upload-style paths (e.g. 1/products/xxx) when
    the DB stores seed path (seed_images/store/xxx); building from name avoids that.
    """
    if not media_obj:
        return None
    if not media_obj.file or not media_obj.file.name:
        # Media imported from elsewhere carries no local file at all — the asset
        # lives on a CDN and `external_url` is the only address it has. Returning
        # None here blanked every legacy image across the admin (2281 of 2284
        # media rows on the wxstore workspace). `signed_media_url` below has
        # always fallen back this way; this one simply forgot to.
        return media_obj.external_url or None
    # Join on the boundary only. The old `.replace('//', '/')` also collapsed the
    # `//` in an absolute MEDIA_URL, turning `https://cdn/...` into `https:/cdn/...`
    # — harmless while MEDIA_URL was the relative `/media/`, fatal once it points
    # at S3/CloudFront.
    base = f"{settings.MEDIA_URL.rstrip('/')}/{media_obj.file.name.lstrip('/')}"
    if request:
        # Absolute URLs are returned unchanged; only relative ones get the host.
        return request.build_absolute_uri(base)
    return base


def signed_media_url(media_obj, request=None):
    """URL for a Media object, signed + short-lived when the media is sensitive.

    Public media keeps the existing CDN-friendly unsigned URL. Sensitive media
    (Media.is_sensitive) on S3 is served from the private bucket via a presigned
    expiring URL so the object is not world-readable; locally it falls back to the
    normal media URL. Use this in any serializer/endpoint that exposes package
    photos, POD, customs documents or payment proofs (WI-393).
    """
    if not media_obj or not media_obj.file or not media_obj.file.name:
        return media_obj.external_url if media_obj else None
    if getattr(media_obj, 'is_sensitive', False) and getattr(settings, 'USE_S3_MEDIA', False):
        from bfg.common.storage import private_media_storage
        url = private_media_storage().url(media_obj.file.name)
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url
    return media_file_url_for_serializer(media_obj, request)


class MediaSerializer(serializers.ModelSerializer):
    """Media serializer"""
    file = serializers.SerializerMethodField()
    
    class Meta:
        model = Media
        fields = ['id', 'workspace', 'file', 'external_url', 'media_type', 'alt_text', 'width', 'height', 'uploaded_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_file(self, obj):
        """Get full file URL from stored path (so seed_images/store/... stays correct)."""
        request = self.context.get('request')
        return media_file_url_for_serializer(obj, request)


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
        """Get full file URL from stored path (so seed_images/store/... stays correct)."""
        if obj.media:
            request = self.context.get('request')
            return media_file_url_for_serializer(obj.media, request)
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


# ── API Key Serializers ───────────────────────────────────────────

class APIKeySerializer(serializers.ModelSerializer):
    """Read serializer — never exposes the secret."""
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = APIKey
        fields = [
            'id', 'name', 'prefix', 'is_active',
            'created_by', 'created_by_name',
            'last_used_at', 'expires_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'prefix', 'created_by', 'created_by_name',
            'last_used_at', 'created_at', 'updated_at',
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None


class APIKeyCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for key creation.

    The response includes ``api_key`` (prefix) and ``api_secret`` (plain text)
    which are **only** shown once.
    """
    api_key = serializers.CharField(source='prefix', read_only=True)
    api_secret = serializers.CharField(read_only=True)

    class Meta:
        model = APIKey
        fields = ['id', 'name', 'expires_at', 'api_key', 'api_secret', 'created_at']
        read_only_fields = ['id', 'api_key', 'api_secret', 'created_at']
