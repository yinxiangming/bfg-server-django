"""
BFG Common Module API Views

ViewSets for common module
"""

import importlib

from django.apps import apps
from django.db.models.deletion import ProtectedError
from rest_framework import viewsets, status, mixins
from rest_framework.exceptions import APIException
from rest_framework.filters import SearchFilter
from rest_framework.views import APIView
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff, IsOwnerOrStaff
from bfg.common.models import Workspace, Customer, Address, CustomerSegment, CustomerTag, User, UserPreferences, StaffRole, EmailConfig
from bfg.common.serializers import (
    WorkspaceSerializer,
    CustomerListSerializer,
    CustomerDetailSerializer,
    AddressSerializer,
    SettingsSerializer,
    EmailConfigSerializer,
    CustomerSegmentSerializer,
    CustomerTagSerializer,
    MeSerializer,
    ChangePasswordSerializer,
    ResetPasswordSerializer,
    UserPreferencesSerializer,
    StaffRoleSerializer,
)
from bfg.common.services import WorkspaceService, CustomerService, AddressService
from bfg.common.utils import get_required_workspace

# Strip known footer menu name prefixes (e.g. "footer-", localized equivalents)
FOOTER_MENU_NAME_PREFIXES = ('footer-')


def _strip_footer_menu_name_prefix(name: str) -> str:
    for prefix in FOOTER_MENU_NAME_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.title()


class WorkspaceViewSet(viewsets.ModelViewSet):
    """
    Workspace management ViewSet
    
    Only admins can create/update/delete workspaces
    Superusers can create workspaces without being staff
    """
    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_permissions(self):
        """Set permissions based on action"""
        if self.action == 'create':
            # For create, only allow superuser or first workspace creation
            # We'll check in perform_create if user is superuser or if this is first workspace
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return super().get_permissions()
    
    def get_queryset(self):
        """Get workspaces for current user"""
        user = self.request.user
        
        # Superusers can see all workspaces
        if user.is_superuser:
            return Workspace.objects.filter(is_active=True)
        
        # Get workspaces where user is a staff member
        from bfg.common.models import StaffMember
        staff_workspaces = StaffMember.objects.filter(
            user=user,
            is_active=True
        ).values_list('workspace_id', flat=True)
        
        return Workspace.objects.filter(
            id__in=staff_workspaces,
            is_active=True
        )
    
    def perform_create(self, serializer):
        """Create workspace using service"""
        user = self.request.user
        
        # Allow superuser to create workspace
        if user.is_superuser:
            pass
        # Allow if this is the first workspace (system initialization)
        elif Workspace.objects.count() == 0:
            pass
        # For non-superusers with existing workspaces, check if they're admin
        else:
            from bfg.core.permissions import IsWorkspaceAdmin
            if not IsWorkspaceAdmin().has_permission(self.request, self):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "Only superusers can create workspaces, or this must be the first workspace in the system"
                )
        
        service = WorkspaceService(user=self.request.user)
        workspace = service.create_workspace(
            name=serializer.validated_data['name'],
            slug=serializer.validated_data.get('slug'),
            owner_user=self.request.user,
            **{k: v for k, v in serializer.validated_data.items() if k not in ['name', 'slug']}
        )
        serializer.instance = workspace


class CustomerViewSet(viewsets.ModelViewSet):
    """
    Customer management ViewSet
    
    Staff can view all customers, customers can only view/update themselves
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter]
    search_fields = [
        'user__first_name',
        'user__last_name',
        'user__email',
        'user__phone',
        'company_name',
        'customer_number'
    ]
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'retrieve':
            return CustomerDetailSerializer
        return CustomerListSerializer
    
    def get_queryset(self):
        """Get customers based on permissions"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
        
        user = self.request.user
        
        # Superuser or staff can see all customers
        from bfg.common.models import StaffMember
        is_staff = user.is_superuser or StaffMember.objects.filter(
            workspace=workspace,
            user=user,
            is_active=True
        ).exists()
        
        if is_staff:
            return Customer.objects.filter(
                workspace=workspace
            ).select_related('user')
        
        # Customers can only see themselves
        return Customer.objects.filter(
            workspace=workspace,
            user=user
        ).select_related('user')
    
    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            return [IsAuthenticated()]
        elif self.action in ['update', 'partial_update']:
            return [IsAuthenticated(), IsOwnerOrStaff()]
        else:
            return [IsAuthenticated(), IsWorkspaceStaff()]
    
    def perform_create(self, serializer):
        """Create customer using service"""
        service = CustomerService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        customer = service.create_customer(
            user=self.request.user,
            workspace=self.request.workspace,
            **serializer.validated_data
        )
        serializer.instance = customer
    
    @action(detail=True, methods=['get'], url_path='wallet')
    def wallet(self, request, pk=None):
        """Get customer wallet information"""
        customer = self.get_object()
        service = CustomerService(
            workspace=request.workspace,
            user=request.user
        )
        wallet_data = service.get_wallet(customer)
        return Response(wallet_data)
    
    @action(detail=True, methods=['post'], url_path='wallet/topup')
    def wallet_topup(self, request, pk=None):
        """Top up customer wallet"""
        customer = self.get_object()
        amount = request.data.get('amount')
        note = request.data.get('note', 'Manual top-up by admin')
        
        if not amount:
            return Response({'error': 'Amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        service = CustomerService(
            workspace=request.workspace,
            user=request.user
        )
        
        try:
            wallet_data = service.topup_wallet(customer, amount, note, request.user)
            return Response(wallet_data)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], url_path='wallet/transactions')
    def wallet_transactions(self, request, pk=None):
        """Get customer wallet transactions with pagination"""
        customer = self.get_object()
        
        # Check if finance module is available
        try:
            from bfg.finance.models import Transaction
            from bfg.finance.serializers import TransactionSerializer
        except ImportError:
            # Return empty list if finance module not available
            return Response({
                'count': 0,
                'next': None,
                'previous': None,
                'results': []
            })
        
        # Get pagination parameters
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        
        # Get transactions for customer
        queryset = Transaction.objects.filter(
            customer=customer,
            workspace=request.workspace
        ).select_related('currency', 'payment', 'invoice', 'created_by').order_by('-created_at')
        
        # Calculate pagination
        total = queryset.count()
        start = (page - 1) * page_size
        end = start + page_size
        
        transactions = queryset[start:end]
        serializer = TransactionSerializer(transactions, many=True)
        
        return Response({
            'count': total,
            'next': f'{request.path}?page={page + 1}&page_size={page_size}' if end < total else None,
            'previous': f'{request.path}?page={page - 1}&page_size={page_size}' if page > 1 else None,
            'results': serializer.data
        })
    
    @action(detail=True, methods=['get'], url_path='messages')
    def messages(self, request, pk=None):
        """Get customer messages (inbox)"""
        customer = self.get_object()
        
        # Check if inbox module is available
        try:
            from bfg.inbox.models import MessageRecipient
            from bfg.inbox.serializers import MessageRecipientSerializer
        except ImportError:
            # Return empty list if inbox module not available
            return Response({
                'count': 0,
                'next': None,
                'previous': None,
                'results': []
            })
        
        # Get pagination parameters
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        
        # Get messages for customer
        queryset = MessageRecipient.objects.filter(
            recipient=customer,
            is_deleted=False
        ).select_related('message', 'message__sender', 'recipient').order_by('-delivered_at')
        
        # Calculate pagination
        total = queryset.count()
        start = (page - 1) * page_size
        end = start + page_size
        
        message_recipients = queryset[start:end]
        serializer = MessageRecipientSerializer(message_recipients, many=True, context={'request': request})
        
        return Response({
            'count': total,
            'next': f'{request.path}?page={page + 1}&page_size={page_size}' if end < total else None,
            'previous': f'{request.path}?page={page - 1}&page_size={page_size}' if page > 1 else None,
            'results': serializer.data
        })
    
    @action(detail=True, methods=['post'], url_path='send-message')
    def send_message(self, request, pk=None):
        """Send message to customer"""
        customer = self.get_object()
        
        # Check if inbox module is available
        try:
            from bfg.inbox.services import MessageService
        except ImportError:
            return Response(
                {'detail': 'Inbox module is not available'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        subject = request.data.get('subject')
        message_content = request.data.get('message')
        
        if not subject or not message_content:
            return Response(
                {'detail': 'subject and message are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Send message using MessageService
        service = MessageService(
            workspace=request.workspace,
            user=request.user
        )
        
        try:
            msg = service.send_message(
                recipients=[customer],
                subject=subject,
                message=message_content,
                message_type='message'
            )
            
            from bfg.inbox.serializers import MessageSerializer
            serializer = MessageSerializer(msg, context={'request': request})
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AddressViewSet(viewsets.ModelViewSet):
    """
    Address management ViewSet
    
    Users can only access addresses attached to their own objects
    """
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]
    
    def get_queryset(self):
        """Get addresses for current workspace"""
        workspace = self.request.workspace
        user = self.request.user
        
        # Staff members can access all addresses in workspace
        is_staff = getattr(self.request, 'is_staff_member', False) or user.is_superuser
        
        queryset = Address.objects.filter(workspace=workspace)
        
        if is_staff:
            # Staff can see all addresses, optionally filter by customer if provided
            customer_id = self.request.query_params.get('customer')
            if customer_id:
                from bfg.common.models import Customer
                from django.contrib.contenttypes.models import ContentType
                
                customer = Customer.objects.filter(
                    id=customer_id,
                    workspace=workspace
                ).first()
                
                if customer:
                    content_type = ContentType.objects.get_for_model(Customer)
                    queryset = queryset.filter(
                        content_type=content_type,
                        object_id=customer.id
                    )
                else:
                    queryset = queryset.none()
            # If no customer filter, staff can see all addresses
        else:
            # If not staff, filter to user's own addresses (via Customer)
            from bfg.common.models import Customer
            from django.contrib.contenttypes.models import ContentType
            
            customer = Customer.objects.filter(
                workspace=workspace,
                user=user
            ).first()
            
            if customer:
                content_type = ContentType.objects.get_for_model(Customer)
                queryset = queryset.filter(
                    content_type=content_type,
                    object_id=customer.id
                )
            else:
                queryset = queryset.none()
        
        return queryset.order_by('-is_default', '-created_at')
    
    def perform_create(self, serializer):
        """Create address using service"""
        from bfg.common.models import Customer
        from bfg.common.services import AddressService
        from rest_framework.exceptions import ValidationError
        
        # Staff members can create addresses without customer link (for warehouses, stores, etc.)
        is_staff = getattr(self.request, 'is_staff_member', False)
        
        service = AddressService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        if is_staff:
            # Staff can create standalone addresses
            
            # Check if creating for a specific customer (from serializer or request data)
            customer_id = serializer.validated_data.pop('customer_id', None) or self.request.data.get('customer_id')
            if customer_id:
                try:
                    customer = Customer.objects.get(
                        id=customer_id,
                        workspace=self.request.workspace
                    )
                    content_object = customer
                except Customer.DoesNotExist:
                    raise ValidationError({'customer_id': f'Customer with id {customer_id} not found.'})
            else:
                # Create without content_object for system addresses
                content_object = None
        else:
            # Regular users must have a customer profile
            # Check if customer_id is provided in request
            customer_id = serializer.validated_data.pop('customer_id', None) or self.request.data.get('customer_id')
            
            if customer_id:
                # If customer_id is provided, use it
                try:
                    customer = Customer.objects.get(
                        id=customer_id,
                        workspace=self.request.workspace
                    )
                    content_object = customer
                except Customer.DoesNotExist:
                    raise ValidationError({'customer_id': f'Customer with id {customer_id} not found.'})
            else:
                # Try to get customer from current user
                try:
                    customer = Customer.objects.get(
                        workspace=self.request.workspace,
                        user=self.request.user
                    )
                    content_object = customer
                except Customer.DoesNotExist:
                    raise ValidationError({
                        'customer_id': 'Customer profile not found. Please provide a customer_id or ensure you have a customer profile.'
                    })
        
        if content_object:
            address = service.create_address(
                content_object=content_object,
                **serializer.validated_data
            )
        else:
            # Create address directly without GenericForeignKey
            from bfg.common.models import Address
            address = Address.objects.create(
                workspace=self.request.workspace,
                **serializer.validated_data
            )
        
        serializer.instance = address

    
    def perform_update(self, serializer):
        """Update address using service"""
        service = AddressService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        address = service.update_address(
            serializer.instance,
            **serializer.validated_data
        )
        serializer.instance = address
    
    def perform_destroy(self, instance):
        """Delete address using service"""
        service = AddressService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        service.delete_address(instance)
    
    @action(detail=False, methods=['get'])
    def default(self, request):
        """Get default address for current user"""
        from bfg.common.models import Customer
        
        customer = Customer.objects.get(
            workspace=request.workspace,
            user=request.user
        )
        
        service = AddressService(
            workspace=request.workspace,
            user=request.user
        )
        
        address = service.get_default_address(customer)
        
        if not address:
            return Response(
                {'detail': 'No default address found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(address)
        return Response(serializer.data)


class SettingsViewSet(viewsets.ModelViewSet):
    """
    Workspace settings management ViewSet
    
    Only admins can update settings
    """
    serializer_class = SettingsSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    http_method_names = ['get', 'put', 'patch']  # No create/delete
    
    def get_queryset(self):
        """Get settings for current workspace"""
        from bfg.common.models import Settings
        return Settings.objects.filter(workspace=self.request.workspace)
    
    def get_object(self):
        """Get or create settings for current workspace"""
        from bfg.common.services import SettingsService
        
        service = SettingsService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        return service.get_or_create_settings(self.request.workspace)
    
    def perform_update(self, serializer):
        """Update settings using service; invalidate storefront config cache."""
        from django.core.cache import cache
        from bfg.common.services import SettingsService

        service = SettingsService(
            workspace=self.request.workspace,
            user=self.request.user
        )

        settings = service.update_settings(
            serializer.instance,
            **serializer.validated_data
        )
        serializer.instance = settings
        # Invalidate storefront config cache so footer/header reflect new settings
        wid = getattr(settings.workspace, 'id', None) or getattr(settings, 'workspace_id', None)
        if wid is not None:
            for lang in ('en', 'zh-hans', 'zh-hant'):
                cache.delete(f"storefront_config:{wid}:{lang}")
    
    @action(detail=False, methods=['post'])
    def enable_feature(self, request):
        """
        Enable a feature
        
        POST /api/v1/settings/enable_feature/
        Body: {"feature": "shop"}
        """
        from bfg.common.services import SettingsService
        
        feature_name = request.data.get('feature')
        if not feature_name:
            return Response(
                {'detail': 'Feature name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = SettingsService(
            workspace=request.workspace,
            user=request.user
        )
        
        settings = service.get_or_create_settings(request.workspace)
        settings = service.enable_feature(settings, feature_name)
        
        serializer = self.get_serializer(settings)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def disable_feature(self, request):
        """
        Disable a feature

        POST /api/v1/settings/disable_feature/
        Body: {"feature": "shop"}
        """
        from bfg.common.services import SettingsService

        feature_name = request.data.get('feature')
        if not feature_name:
            return Response(
                {'detail': 'Feature name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = SettingsService(
            workspace=request.workspace,
            user=request.user
        )

        settings = service.get_or_create_settings(request.workspace)
        settings = service.disable_feature(settings, feature_name)

        serializer = self.get_serializer(settings)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def storefront(self, request):
        """
        Public read-only storefront config: sanitized Settings + header/footer menus.
        GET /api/v1/settings/storefront/?lang=en
        Cached by workspace (and optional lang).
        """
        from django.core.cache import cache
        from bfg.common.models import Settings
        from bfg.common.services import SettingsService

        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return Response(
                {'detail': 'No workspace available'},
                status=status.HTTP_404_NOT_FOUND
            )

        lang = request.query_params.get('lang', 'en')
        cache_key = f"storefront_config:{workspace.id}:{lang}"
        STOREFRONT_CONFIG_TTL = 60 * 60  # 1 hour

        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        service = SettingsService(workspace=workspace, user=request.user)
        settings_obj = service.get_or_create_settings(workspace)

        general_custom = (settings_obj.custom_settings or {}).get('general') or {}
        storefront_ui = (settings_obj.custom_settings or {}).get('storefront_ui') or {}
        default_header_options = {
            'show_search': True,
            'show_cart': True,
            'show_language_switcher': True,
            'show_style_selector': True,
            'show_login': True,
        }
        header_options = storefront_ui.get('header_options')
        if isinstance(header_options, dict):
            default_header_options = {**default_header_options, **header_options}
        payload = {
            'site_name': settings_obj.site_name or general_custom.get('site_name', '') or '',
            'site_description': settings_obj.site_description or general_custom.get('site_description', '') or '',
            'contact_email': settings_obj.contact_email or general_custom.get('contact_email', '') or '',
            'support_email': settings_obj.support_email or '',
            'contact_phone': settings_obj.contact_phone or general_custom.get('contact_phone', '') or '',
            'facebook_url': settings_obj.facebook_url or '',
            'twitter_url': settings_obj.twitter_url or '',
            'instagram_url': settings_obj.instagram_url or '',
            'default_currency': settings_obj.default_currency or 'NZD',
            'top_bar_announcement': general_custom.get('top_bar_announcement', ''),
            'footer_copyright': general_custom.get('footer_copyright', ''),
            'site_announcement': general_custom.get('site_announcement', ''),
            'footer_contact': general_custom.get('footer_contact', ''),
            'header_menus': [],
            'footer_menus': [],
            'footer_menu_groups': [],
            'theme': storefront_ui.get('theme') or 'store',
            'header': storefront_ui.get('header'),
            'footer': storefront_ui.get('footer'),
            'header_options': default_header_options,
        }

        try:
            from bfg.web.models import Menu

            def add_menu_items(queryset, only_if_empty_header=False, only_if_empty_footer=False, add_footer_groups=True):
                for menu in queryset.prefetch_related('items').order_by('name'):
                    items = [
                        {
                            'title': item.title,
                            'url': item.url,
                            'order': item.order,
                            'open_in_new_tab': item.open_in_new_tab,
                        }
                        for item in menu.items.filter(is_active=True).order_by('order')
                    ]
                    if menu.location == 'header' and (not only_if_empty_header or not payload['header_menus']):
                        payload['header_menus'].extend(items)
                    elif menu.location == 'footer':
                        if not only_if_empty_footer or not payload['footer_menus']:
                            payload['footer_menus'].extend(items)
                        if add_footer_groups:
                            payload['footer_menu_groups'].append({
                                'slug': menu.slug,
                                'name': _strip_footer_menu_name_prefix(menu.name),
                                'items': items,
                            })

            # Prefer menus for requested language
            qs = Menu.objects.filter(
                workspace=workspace,
                location__in=['header', 'footer'],
                is_active=True,
                language=lang,
            )
            add_menu_items(qs)
            # Fallback when requested lang has no menus: try other languages (en, zh-hans)
            if not payload['header_menus'] and not payload['footer_menu_groups']:
                for fallback_lang in ('en', 'zh-hans'):
                    if fallback_lang == lang:
                        continue
                    fallback_qs = Menu.objects.filter(
                        workspace=workspace,
                        location__in=['header', 'footer'],
                        is_active=True,
                        language=fallback_lang,
                    )
                    if fallback_qs.exists():
                        add_menu_items(fallback_qs)
                        break
            if lang != 'en':
                fallback_qs = Menu.objects.filter(
                    workspace=workspace,
                    location__in=['header', 'footer'],
                    is_active=True,
                    language='en',
                )
                add_menu_items(fallback_qs, only_if_empty_header=True, only_if_empty_footer=True, add_footer_groups=False)

            payload['header_menus'].sort(key=lambda x: x['order'])
            payload['footer_menus'].sort(key=lambda x: x['order'])
            # Stable order for footer groups: product, resources, company, legal
            _footer_slug_order = ('footer-product', 'footer-resources', 'footer-company', 'footer-legal')
            payload['footer_menu_groups'].sort(
                key=lambda g: (_footer_slug_order.index(g['slug']) if g.get('slug') in _footer_slug_order else 999, g.get('slug') or ''),
            )
        except (ImportError, AttributeError):
            pass

        # Prefer bfg.web Site for site_name (Site title), then Settings
        try:
            from bfg.web.models import Site
            site = Site.objects.filter(workspace=workspace, is_active=True).order_by('-is_default').select_related('theme').first()
            if site:
                site_display_name = (getattr(site, 'name', None) or getattr(site, 'site_title', None) or '').strip()
                if site_display_name:
                    payload['site_name'] = site_display_name
                if not payload.get('site_description') and getattr(site, 'site_description', None):
                    payload['site_description'] = site.site_description
                if not storefront_ui.get('theme') and site.theme_id and site.theme:
                    tp = (site.theme.template_path or '').strip()
                    if tp == 'themes/website':
                        payload['theme'] = 'website'
                    elif tp == 'themes/default' or not tp:
                        payload['theme'] = 'store'
                payload['default_language'] = getattr(site, 'default_language', None) or 'zh-hans'
        except (ImportError, AttributeError):
            pass
        if 'default_language' not in payload:
            payload['default_language'] = 'zh-hans'

        cache.set(cache_key, payload, STOREFRONT_CONFIG_TTL)
        return Response(payload)

    @action(detail=False, methods=['get'])
    def options(self, request):
        """
        Get all configurable entity options for Settings autocomplete fields

        GET /api/v1/settings/options/
        Returns options for stores, sales channels, currencies, payment gateways, etc.
        """
        workspace = request.workspace

        options = {}

        # Try to import and get options from each module
        try:
            # Store options
            from bfg.shop.models import Store, SalesChannel
            from bfg.shop.serializers import StoreSerializer, SalesChannelSerializer

            options['stores'] = StoreSerializer(
                Store.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
            options['sales_channels'] = SalesChannelSerializer(
                SalesChannel.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
        except (ImportError, AttributeError):
            options['stores'] = []
            options['sales_channels'] = []

        try:
            # Finance options
            from bfg.finance.models import Currency, PaymentGateway, TaxRate, Brand
            from bfg.finance.serializers import (
                CurrencySerializer, PaymentGatewaySerializer, TaxRateSerializer, BrandSerializer
            )
            from bfg.finance.gateways.loader import gateway_supports_client

            options['currencies'] = CurrencySerializer(
                Currency.objects.filter(is_active=True),
                many=True
            ).data
            gateways_qs = PaymentGateway.objects.filter(workspace=workspace, is_active=True)
            client = (request.query_params.get('client') or '').strip().lower()
            if client:
                gateways_qs = [g for g in gateways_qs if gateway_supports_client(g.gateway_type, client)]
            else:
                gateways_qs = list(gateways_qs)
            options['payment_gateways'] = PaymentGatewaySerializer(gateways_qs, many=True).data
            options['tax_rates'] = TaxRateSerializer(
                TaxRate.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
            options['brands'] = BrandSerializer(
                Brand.objects.filter(workspace=workspace),
                many=True
            ).data
        except (ImportError, AttributeError):
            options['currencies'] = []
            options['payment_gateways'] = []
            options['tax_rates'] = []
            options['brands'] = []

        try:
            # Delivery options
            from bfg.delivery.models import Warehouse, Carrier, PackagingType
            from bfg.delivery.serializers import (
                WarehouseSerializer, CarrierSerializer, PackagingTypeSerializer
            )

            options['warehouses'] = WarehouseSerializer(
                Warehouse.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
            options['carriers'] = CarrierSerializer(
                Carrier.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
            options['packaging_types'] = PackagingTypeSerializer(
                PackagingType.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
        except (ImportError, AttributeError):
            options['warehouses'] = []
            options['carriers'] = []
            options['packaging_types'] = []

        try:
            # Marketing options
            from bfg.marketing.models import ReferralProgram
            from bfg.marketing.serializers import ReferralProgramSerializer

            options['referral_programs'] = ReferralProgramSerializer(
                ReferralProgram.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
        except (ImportError, AttributeError):
            options['referral_programs'] = []

        try:
            # Web options
            from bfg.web.models import Site, Theme
            from bfg.web.serializers import SiteSerializer, ThemeSerializer

            options['sites'] = SiteSerializer(
                Site.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
            options['themes'] = ThemeSerializer(
                Theme.objects.filter(workspace=workspace, is_active=True),
                many=True
            ).data
        except (ImportError, AttributeError):
            options['sites'] = []
            options['themes'] = []

        return Response(options)


class EmailConfigViewSet(viewsets.ModelViewSet):
    """Workspace email config CRUD + set_default + send_test."""
    serializer_class = EmailConfigSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]

    def get_queryset(self):
        return EmailConfig.objects.filter(workspace=self.request.workspace)

    def perform_create(self, serializer):
        serializer.save(workspace=self.request.workspace)

    @action(detail=False, methods=['get'], url_path='backend_types')
    def backend_types(self, request):
        """List available backend types and config schema for UI."""
        from bfg.common.email_backends import list_backend_types
        return Response(list_backend_types())

    @action(detail=True, methods=['post'], url_path='set_default')
    def set_default(self, request, pk=None):
        """Set this config as the default for the workspace."""
        config = self.get_object()
        EmailConfig.objects.filter(workspace=config.workspace).update(is_default=False)
        config.is_default = True
        config.save(update_fields=['is_default'])
        serializer = self.get_serializer(config)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='send_test')
    def send_test(self, request, pk=None):
        """Send a test email using this config (to= in body)."""
        config = self.get_object()
        to_email = (request.data.get('to') or '').strip()
        if not to_email or '@' not in to_email:
            return Response(
                {'detail': 'Valid "to" email is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        from bfg.common.email_backends import get_backend
        backend_class = get_backend(config.backend_type)
        backend = backend_class()
        try:
            backend.send(
                to_list=[to_email],
                subject='Test email from PackGo',
                body_plain='This is a test email. If you received this, your email config is working.',
                body_html=None,
                from_email=config.config.get('from_email'),
                config=config.config,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response({'detail': 'Test email sent successfully'})


class UserViewSet(viewsets.ModelViewSet):
    """
    User management ViewSet
    """
    from bfg.common.serializers import UserSerializer
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Users can only see themselves unless admin"""
        user = self.request.user
        if user.is_staff or user.is_superuser:
            from bfg.common.models import User
            return User.objects.all()
        from bfg.common.models import User
        return User.objects.filter(id=user.id)


class MeViewSet(viewsets.GenericViewSet):
    """
    Me ViewSet - unified API for current user's personal information
    
    GET /api/v1/me/ - Get current user info
    PUT /api/v1/me/ - Update current user info
    PATCH /api/v1/me/ - Partial update current user info
    """
    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = None
    
    def get_object(self):
        """Get current user"""
        return self.request.user
    
    def retrieve(self, request, *args, **kwargs):
        """Get current user info - GET /api/v1/me/"""
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        """Update current user info - PUT /api/v1/me/"""
        user = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    
    def partial_update(self, request, *args, **kwargs):
        """Partial update current user info - PATCH /api/v1/me/"""
        user = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='avatar')
    def avatar_upload(self, request):
        """Upload avatar - POST /api/v1/me/avatar/. Accepts multipart file under key 'avatar' (e.g. miniprogram Taro.uploadFile)."""
        user = self.get_object()
        file = request.FILES.get('avatar')
        if not file:
            return Response({'detail': 'Missing file under key "avatar".'}, status=400)
        user.avatar = file
        user.save(update_fields=['avatar'])
        serializer = self.get_serializer(user)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """Change password
        
        POST /api/v1/me/change-password/
        Body: {
            "old_password": "old_password",
            "new_password": "new_password",
            "confirm_password": "new_password"
        }
        """
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        return Response({'detail': 'Password changed successfully'})
    
    @action(detail=False, methods=['post'])
    def reset_password(self, request):
        """Request password reset (sends email)
        
        POST /api/v1/me/reset-password/
        Body: {
            "email": "user@example.com"
        }
        
        Uses django-allauth's password reset functionality.
        """
        serializer = ResetPasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        
        try:
            # Try to import allauth password reset
            from allauth.account.forms import ResetPasswordForm
            
            # Use allauth's password reset form
            form = ResetPasswordForm({'email': email})
            if form.is_valid():
                try:
                    form.save(request=request)
                except Exception:
                    # If allauth URLs are not configured, fall back to Django's form
                    pass
                # Return success without revealing if email exists
                return Response({
                    'detail': 'If the email exists, a password reset link has been sent.'
                })
            else:
                # Form validation failed, but don't reveal details
                return Response({
                    'detail': 'If the email exists, a password reset link has been sent.'
                })
        except (ImportError, Exception):
            # Fallback if allauth is not installed or configured
            from django.contrib.auth.forms import PasswordResetForm
            form = PasswordResetForm({'email': email})
            if form.is_valid():
                try:
                    form.save(
                        request=request,
                        use_https=request.is_secure(),
                        email_template_name='registration/password_reset_email.html',
                        subject_template_name='registration/password_reset_subject.txt',
                    )
                except Exception:
                    # If email backend is not configured, just return success
                    pass
            return Response({
                'detail': 'If the email exists, a password reset link has been sent.'
            })


class MeAddressViewSet(viewsets.ModelViewSet):
    """
    Me Address ViewSet - current user's addresses
    
    GET /api/v1/me/addresses/ - List addresses
    POST /api/v1/me/addresses/ - Create address
    GET /api/v1/me/addresses/{id}/ - Get address
    PATCH /api/v1/me/addresses/{id}/ - Update address
    DELETE /api/v1/me/addresses/{id}/ - Delete address
    GET /api/v1/me/addresses/default/ - Get default address
    """
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get addresses for current customer"""
        from bfg.common.models import Customer
        from bfg.common.services import CustomerService
        from django.contrib.contenttypes.models import ContentType
        
        # Get required workspace (ensures workspace is set, prevents cross-workspace access)
        workspace = get_required_workspace(self.request)
        
        # Find customer for this workspace and user
        service = CustomerService(
            workspace=workspace,
            user=self.request.user
        )
        customer = service.get_customer_by_user(self.request.user, workspace)
        
        if not customer:
            return Address.objects.none()
        
        # Use customer.workspace (more reliable than request.workspace)
        customer_type = ContentType.objects.get_for_model(Customer)
        
        return Address.objects.filter(
            workspace=customer.workspace,  # Use customer's workspace
            content_type=customer_type,
            object_id=customer.id
        ).order_by('-is_default', '-created_at')
    
    def perform_create(self, serializer):
        """Create address for current customer"""
        from bfg.common.models import Customer
        from bfg.common.services import CustomerService
        from django.contrib.contenttypes.models import ContentType
        
        # Get required workspace (ensures workspace is set, prevents cross-workspace access)
        workspace = get_required_workspace(self.request)
        
        # Get or create customer for this workspace and user
        service = CustomerService(
            workspace=workspace,
            user=self.request.user
        )
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        # Use customer.workspace (more reliable than request.workspace)
        customer_type = ContentType.objects.get_for_model(Customer)
        
        serializer.save(
            workspace=customer.workspace,  # Use customer's workspace
            content_type=customer_type,
            object_id=customer.id
        )

    def perform_destroy(self, instance):
        """Delete address; return 409 when referenced by orders or consignments."""
        try:
            instance.delete()
        except ProtectedError:
            exc = APIException(
                detail="Cannot delete this address because it is used by orders or consignments."
            )
            exc.status_code = status.HTTP_409_CONFLICT
            raise exc

    @action(detail=False, methods=['get'])
    def default(self, request):
        """Get default address"""
        queryset = self.get_queryset().filter(is_default=True).first()
        if not queryset:
            return Response(
                {'detail': 'No default address found'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(queryset)
        return Response(serializer.data)


class MeSettingsViewSet(viewsets.GenericViewSet,
                        mixins.RetrieveModelMixin,
                        mixins.UpdateModelMixin):
    """
    Me Settings ViewSet - current user's preferences
    
    GET /api/v1/me/settings/ - Get preferences
    PUT /api/v1/me/settings/ - Update preferences
    PATCH /api/v1/me/settings/ - Partial update preferences
    """
    serializer_class = UserPreferencesSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = None
    
    def get_object(self):
        """Get or create preferences for current user"""
        preferences, _ = UserPreferences.objects.get_or_create(user=self.request.user)
        return preferences
    
    def retrieve(self, request, *args, **kwargs):
        """Get current user's preferences - GET /api/v1/me/settings/"""
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        """Update current user's preferences - PUT /api/v1/me/settings/"""
        preferences = self.get_object()
        serializer = self.get_serializer(preferences, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    
    def partial_update(self, request, *args, **kwargs):
        """Partial update current user's preferences - PATCH /api/v1/me/settings/"""
        preferences = self.get_object()
        serializer = self.get_serializer(preferences, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MeOrdersViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Me Orders ViewSet - alias for /api/store/orders/
    
    GET /api/v1/me/orders/ - List current user's orders
    GET /api/v1/me/orders/{id}/ - Get order details
    POST /api/v1/me/orders/{id}/cancel/ - Cancel order
    
    This is an alias that delegates to StorefrontOrderViewSet
    """
    from bfg.shop.viewsets.storefront import StorefrontOrderViewSet
    from bfg.shop.serializers.storefront import StorefrontOrderSerializer
    
    serializer_class = StorefrontOrderSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get orders for current customer - delegate to StorefrontOrderViewSet"""
        from bfg.shop.viewsets.storefront import StorefrontOrderViewSet
        from bfg.common.models import Customer
        
        # Get required workspace (ensures workspace is set, prevents cross-workspace access)
        workspace = get_required_workspace(self.request)
        
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        # Use the same logic as StorefrontOrderViewSet
        from bfg.shop.models import Order, OrderItem
        from django.db.models import Prefetch

        items_prefetch = OrderItem.objects.select_related('product')
        queryset = Order.objects.filter(
            workspace=customer.workspace,  # Use customer's workspace
            customer=customer
        ).select_related(
            'customer', 'customer__user', 'store', 'shipping_address', 'billing_address'
        ).prefetch_related(Prefetch('items', queryset=items_prefetch))
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel order - delegate to StorefrontOrderViewSet logic"""
        from bfg.shop.viewsets.storefront import StorefrontOrderViewSet
        from bfg.shop.services import OrderService
        from bfg.common.models import Customer
        from rest_framework.exceptions import PermissionDenied
        
        order = self.get_object()
        reason = request.data.get('reason', '')
        
        # Get required workspace (ensures workspace is set, prevents cross-workspace access)
        workspace = get_required_workspace(request)
        
        # Verify order belongs to customer
        customer, _ = Customer.objects.get_or_create(
            user=request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        if order.customer != customer:
            raise PermissionDenied("Order does not belong to current customer")
        
        service = OrderService(
            workspace=customer.workspace,  # Use customer's workspace
            user=request.user
        )
        
        order = service.cancel_order(order, reason)
        serializer = self.get_serializer(order)
        return Response(serializer.data)


class MePaymentMethodViewSet(viewsets.ModelViewSet):
    """
    Me Payment Method ViewSet - current user's payment methods
    
    GET /api/v1/me/payment-methods/ - List payment methods
    POST /api/v1/me/payment-methods/ - Create payment method
    GET /api/v1/me/payment-methods/{id}/ - Get payment method
    PATCH /api/v1/me/payment-methods/{id}/ - Update payment method
    DELETE /api/v1/me/payment-methods/{id}/ - Delete payment method
    """
    from bfg.finance.serializers import PaymentMethodSerializer
    
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get payment methods for current customer"""
        from bfg.finance.models import PaymentMethod
        from bfg.common.models import Customer
        
        # Get required workspace
        workspace = get_required_workspace(self.request)
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        queryset = PaymentMethod.objects.filter(
            customer=customer,
            workspace=workspace
        ).select_related('customer', 'gateway').order_by('-is_default', '-created_at')
        
        return queryset
    
    def perform_create(self, serializer):
        """Create payment method for current customer"""
        from bfg.common.models import Customer
        from bfg.common.models import Address
        
        # Get required workspace
        workspace = get_required_workspace(self.request)
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        # Get billing address if provided
        billing_address = None
        billing_address_id = serializer.validated_data.pop('billing_address_id', None)
        if billing_address_id:
            billing_address = Address.objects.filter(
                id=billing_address_id,
                workspace=workspace
            ).first()
            if not billing_address:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({
                    'billing_address_id': f'Address with id {billing_address_id} not found.'
                })
        
        # Ensure only one default payment method per customer
        if serializer.validated_data.get('is_default'):
            from bfg.finance.models import PaymentMethod
            PaymentMethod.objects.filter(
                customer=customer,
                is_default=True
            ).update(is_default=False)
        
        # Set workspace and customer
        gateway = serializer.validated_data.get('gateway')
        if not gateway:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'gateway': 'Gateway is required'})
        
        # Check if gateway supports plugin system and payment_method_data is provided
        gateway_payment_method_data = serializer.validated_data.pop('gateway_payment_method_data', None)
        if not gateway_payment_method_data:
            # Legacy support: check for stripe_payment_method_data
            gateway_payment_method_data = serializer.validated_data.pop('stripe_payment_method_data', None)
            if gateway_payment_method_data:
                # Convert to new format
                gateway_payment_method_data = {'payment_method_id': gateway_payment_method_data.get('payment_method_id')}
        
        if gateway_payment_method_data:
            from bfg.finance.gateways.loader import get_gateway_plugin
            
            plugin = get_gateway_plugin(gateway)
            if plugin:
                # Extract payment_method_id from data
                payment_method_id = gateway_payment_method_data.get('payment_method_id')
                
                if payment_method_id:
                    # Create/attach PaymentMethod in gateway
                    gateway_pm = plugin.create_payment_method(
                        customer,
                        {'payment_method_id': payment_method_id}
                    )
                    
                    # Save to BFG PaymentMethod model
                    set_as_default = serializer.validated_data.get('is_default', False)
                    payment_method_data = {'set_as_default': set_as_default}
                    payment_method = plugin.save_payment_method(
                        customer,
                        gateway_pm.id if isinstance(gateway_pm, dict) else gateway_pm.get('id', payment_method_id),
                        payment_method_data
                    )
                    
                    # Set billing address if provided
                    if billing_address:
                        payment_method.billing_address = billing_address
                        payment_method.save()
                    
                    serializer.instance = payment_method
                    return
        
        # For other gateways or manual creation, generate gateway_token if not provided
        # NOTE: For Stripe gateway, gateway_token should be a valid PaymentMethod ID (pm_...)
        # This fallback is only for non-Stripe gateways or when gateway plugin is not available
        if 'gateway_token' not in serializer.validated_data or not serializer.validated_data.get('gateway_token'):
            # Check if this is a Stripe gateway - if so, don't generate fake token
            if gateway.gateway_type == 'stripe':
                from rest_framework.exceptions import ValidationError
                raise ValidationError({
                    'gateway': 'Stripe payment methods must be created through Stripe integration. '
                              'Please provide stripe_payment_method_data with a valid PaymentMethod ID.'
                })
            # For other gateways, generate a token
            from django.utils.crypto import get_random_string
            serializer.validated_data['gateway_token'] = f'token_{customer.id}_{get_random_string(10)}'
        
        serializer.save(
            customer=customer,
            workspace=workspace,
            billing_address=billing_address
        )
    
    def perform_update(self, serializer):
        """Update payment method"""
        from bfg.common.models import Address
        
        # Get required workspace
        workspace = get_required_workspace(self.request)
        
        # Get billing address if provided
        billing_address_id = serializer.validated_data.pop('billing_address_id', None)
        if billing_address_id is not None:
            if billing_address_id:
                billing_address = Address.objects.filter(
                    id=billing_address_id,
                    workspace=workspace
                ).first()
                if not billing_address:
                    from rest_framework.exceptions import ValidationError
                    raise ValidationError({
                        'billing_address_id': f'Address with id {billing_address_id} not found.'
                    })
            else:
                billing_address = None
            serializer.validated_data['billing_address'] = billing_address
        
        # Ensure only one default payment method per customer
        if serializer.validated_data.get('is_default'):
            from bfg.finance.models import PaymentMethod
            PaymentMethod.objects.filter(
                customer=serializer.instance.customer,
                is_default=True
            ).exclude(pk=serializer.instance.pk).update(is_default=False)
        
        serializer.save()
    
    def perform_destroy(self, instance):
        """Delete payment method - verify it belongs to current customer"""
        from bfg.common.models import Customer
        
        # Get required workspace
        workspace = get_required_workspace(self.request)
        
        # Verify payment method belongs to current customer
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        if instance.customer != customer:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Payment method does not belong to current customer")
        
        instance.delete()


class MePaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Me Payment ViewSet - current user's payment history (read-only)
    
    GET /api/v1/me/payments/ - List payments
    GET /api/v1/me/payments/{id}/ - Get payment details
    POST /api/v1/me/payments/{id}/send/ - Send payment receipt to customer email
    """
    from bfg.finance.serializers import PaymentSerializer
    
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get payments for current customer"""
        from bfg.finance.models import Payment
        from bfg.common.models import Customer
        
        # Get required workspace
        workspace = get_required_workspace(self.request)
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        queryset = Payment.objects.filter(
            customer=customer,
            workspace=workspace
        ).select_related('customer', 'gateway', 'currency', 'order', 'invoice', 'payment_method').order_by('-created_at')
        
        # Filter by order_id if provided
        order_id = self.request.query_params.get('order_id')
        if order_id:
            try:
                queryset = queryset.filter(order_id=int(order_id))
            except (ValueError, TypeError):
                pass  # Ignore invalid order_id
        
        # Filter by status if provided
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Send payment receipt to customer email"""
        from bfg.inbox.services import MessageService
        
        payment = self.get_object()
        workspace = get_required_workspace(request)
        
        # Send via message service
        message_service = MessageService(workspace=workspace, user=request.user)
        try:
            # Send message with payment details
            message_service.send_message(
                recipients=[payment.customer],
                subject=f"Payment Receipt {payment.payment_number}",
                message=f"Payment receipt for {payment.payment_number}. Amount: {payment.amount} {payment.currency.code}. Status: {payment.get_status_display()}.",
                message_type='payment_receipt',
                send_email=True,
            )
            
            return Response({
                'status': 'sent',
                'message': f'Payment receipt {payment.payment_number} has been sent to {payment.customer.user.email}'
            })
        except Exception as e:
            return Response(
                {'error': f'Failed to send payment receipt: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MeInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Me Invoice ViewSet - current user's invoices (read-only)
    
    GET /api/v1/me/invoices/ - List invoices
    GET /api/v1/me/invoices/{id}/ - Get invoice details
    POST /api/v1/me/invoices/{id}/send/ - Send invoice to customer email
    GET /api/v1/me/invoices/{id}/download/ - Download invoice PDF
    """
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        """Use detail serializer for retrieve, list serializer for list"""
        from bfg.finance.serializers import InvoiceDetailSerializer, InvoiceListSerializer
        if self.action == 'retrieve':
            return InvoiceDetailSerializer
        return InvoiceListSerializer
    
    def get_queryset(self):
        """Get invoices for current customer"""
        from bfg.finance.models import Invoice
        from bfg.common.models import Customer
        
        # Get required workspace
        workspace = get_required_workspace(self.request)
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        queryset = Invoice.objects.filter(
            customer=customer,
            workspace=workspace
        ).select_related('customer', 'currency', 'order', 'brand').prefetch_related('items').order_by('-issue_date')
        
        # Filter by order_id if provided
        order_id = self.request.query_params.get('order_id')
        if order_id:
            try:
                queryset = queryset.filter(order_id=int(order_id))
            except (ValueError, TypeError):
                pass  # Ignore invalid order_id
        
        # Filter by status if provided
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Send invoice to customer email"""
        from django.http import HttpResponse
        from bfg.finance.services import InvoiceService
        from bfg.inbox.services import MessageService
        
        invoice = self.get_object()
        workspace = get_required_workspace(request)
        
        # Generate PDF
        service = InvoiceService(workspace=workspace, user=request.user)
        pdf_content = service.generate_pdf(invoice)
        
        # Send via message service
        message_service = MessageService(workspace=workspace, user=request.user)
        try:
            # Send message with PDF attachment
            message_service.send_message(
                recipients=[invoice.customer],
                subject=f"Invoice {invoice.invoice_number}",
                message=f"Please find attached invoice {invoice.invoice_number} for your order.",
                message_type='invoice',
                send_email=True,
            )
            
            # Mark invoice as sent
            service.send_invoice(invoice)
            
            return Response({
                'status': 'sent',
                'message': f'Invoice {invoice.invoice_number} has been sent to {invoice.customer.user.email}'
            })
        except Exception as e:
            return Response(
                {'error': f'Failed to send invoice: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download invoice as PDF"""
        from django.http import HttpResponse
        from bfg.finance.services import InvoiceService
        from bfg.finance.models import Invoice
        from bfg.common.models import Customer
        from rest_framework.exceptions import NotFound, PermissionDenied
        
        # Get invoice and verify it belongs to current user
        workspace = get_required_workspace(request)
        
        # Get or create customer
        customer, _ = Customer.objects.get_or_create(
            user=request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )
        
        try:
            invoice = Invoice.objects.select_related('brand', 'customer', 'currency').get(
                pk=pk,
                customer=customer,
                workspace=workspace
            )
        except Invoice.DoesNotExist:
            raise NotFound("Invoice not found")
        
        # Verify access
        if invoice.customer.user != request.user:
            raise PermissionDenied("You don't have permission to access this invoice")
        
        service = InvoiceService(workspace=workspace, user=request.user)
        pdf_content = service.generate_pdf(invoice)
        
        response = HttpResponse(pdf_content, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
        return response


class OptionsView(APIView):
    """
    Provide cached option lists for select fields.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return Response({})

        # Collect options from registered modules
        options = {}
        for module_path in self.get_option_providers():
            try:
                module = __import__(module_path, fromlist=['get_options'])
                if hasattr(module, 'get_options'):
                    module_options = module.get_options(workspace)
                    if isinstance(module_options, dict):
                        options.update(module_options)
            except Exception as exc:
                # Fail gracefully; log for debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("Failed to load options from %s: %s", module_path, exc)

        return Response(options)

    def get_option_providers(self):
        """
        Dynamically discover option providers from installed bfg.* apps.
        Looks for <app>.options with a get_options(workspace) function.
        """
        providers = []
        for app_config in apps.get_app_configs():
            module_path = f"{app_config.name}.options"
            try:
                module = importlib.import_module(module_path)
                if hasattr(module, 'get_options'):
                    providers.append(module_path)
            except ImportError:
                continue
        return providers


class CustomerSegmentViewSet(viewsets.ModelViewSet):
    """Customer segment management ViewSet"""
    serializer_class = CustomerSegmentSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get customer segments for current workspace"""
        queryset = CustomerSegment.objects.filter(
            workspace=self.request.workspace
        )
        
        # Filter by active status if provided
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        return queryset.order_by('name')
    
    def perform_create(self, serializer):
        """Create segment with workspace"""
        serializer.save(workspace=self.request.workspace)


class CustomerTagViewSet(viewsets.ModelViewSet):
    """Customer tag management ViewSet"""
    serializer_class = CustomerTagSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get customer tags for current workspace"""
        return CustomerTag.objects.filter(
            workspace=self.request.workspace
        ).prefetch_related('customers').order_by('name')
    
    def perform_create(self, serializer):
        """Create tag with workspace"""
        serializer.save(workspace=self.request.workspace)
    
    @action(detail=True, methods=['post'])
    def tag_customers(self, request, pk=None):
        """Tag multiple customers"""
        tag = self.get_object()
        customer_ids = request.data.get('customer_ids', [])
        
        if not customer_ids:
            return Response(
                {'detail': 'customer_ids is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        customers = Customer.objects.filter(
            id__in=customer_ids,
            workspace=request.workspace
        )
        
        tag.customers.add(*customers)
        
        return Response({
            'success': True,
            'tagged_count': len(customer_ids),
            'total_customers': tag.customers.count()
        })
    
    @action(detail=True, methods=['post'])
    def untag_customers(self, request, pk=None):
        """Untag multiple customers"""
        tag = self.get_object()
        customer_ids = request.data.get('customer_ids', [])
        
        if not customer_ids:
            return Response(
                {'detail': 'customer_ids is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        customers = Customer.objects.filter(
            id__in=customer_ids,
            workspace=request.workspace
        )
        
        tag.customers.remove(*customers)
        
        return Response({
            'success': True,
            'untagged_count': len(customer_ids),
            'total_customers': tag.customers.count()
        })


from bfg.common.seed_data import COUNTRY_LIST


class StaffRoleViewSet(viewsets.ModelViewSet):
    """Staff role management ViewSet"""
    serializer_class = StaffRoleSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get staff roles for current workspace"""
        return StaffRole.objects.filter(
            workspace=self.request.workspace
        ).order_by('name')
    
    def perform_create(self, serializer):
        """Create role with workspace"""
        data = serializer.validated_data
        # Generate code from name if not provided
        if 'code' not in data or not data['code']:
            from django.utils.text import slugify
            code = slugify(data['name']).upper().replace('-', '_')
            # Ensure uniqueness within workspace
            base_code = code
            counter = 1
            while StaffRole.objects.filter(workspace=self.request.workspace, code=code).exists():
                code = f"{base_code}_{counter}"
                counter += 1
            serializer.save(workspace=self.request.workspace, code=code)
        else:
            serializer.save(workspace=self.request.workspace)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def countries_list(request):
    """
    Get list of countries (ISO 3166-1 alpha-2 codes)
    Returns list of {code, name} objects
    """
    return Response(COUNTRY_LIST)
