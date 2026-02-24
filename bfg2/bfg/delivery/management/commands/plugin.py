"""
Plugin Testing Command

Django management command to test carrier plugins.
Usage: python manage.py plugin carrier --test --name parcelport --account xxx --secret xxxx
"""

from django.core.management.base import CommandError
from django.core.management.base import BaseCommand
from decimal import Decimal
from bfg.delivery.models import Carrier
from bfg.delivery.carriers.loader import get_carrier_plugin, CarrierLoader
from bfg.common.models import Workspace


class Command(BaseCommand):
    help = 'Test carrier plugins with specified configuration'
    requires_system_checks = []
    
    def add_arguments(self, parser):
        # Subcommand: carrier
        subparsers = parser.add_subparsers(dest='subcommand', help='Plugin type to test')
        
        # Carrier subcommand
        carrier_parser = subparsers.add_parser('carrier', help='Test carrier plugin')
        carrier_parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='Carrier plugin name (e.g., parcelport, starshipit)',
        )
        carrier_parser.add_argument(
            '--test',
            action='store_true',
            help='Use test mode (default: use production/live mode)',
        )
        carrier_parser.add_argument(
            '--account',
            type=str,
            help='Account/username for authentication',
        )
        carrier_parser.add_argument(
            '--secret',
            type=str,
            help='Secret/password for authentication',
        )
        carrier_parser.add_argument(
            '--workspace',
            type=str,
            default=None,
            help='Workspace name (default: use first available workspace)',
        )
        carrier_parser.add_argument(
            '--use-existing',
            action='store_true',
            help='Use existing Carrier configuration from database instead of --account/--secret',
        )
    
    def handle(self, *args, **options):
        subcommand = options.get('subcommand')
        
        if subcommand == 'carrier':
            self.handle_carrier(*args, **options)
        else:
            raise CommandError('Please specify a subcommand: carrier')
    
    def handle_carrier(self, *args, **options):
        """Handle carrier plugin testing"""
        carrier_name = options['name']
        is_test = options['test']
        account = options.get('account')
        secret = options.get('secret')
        workspace_name = options.get('workspace')
        use_existing = options.get('use_existing', False)
        
        # Check if plugin exists
        plugin_info = CarrierLoader.get_plugin_info(carrier_name)
        if not plugin_info:
            available = ', '.join(CarrierLoader.list_available_plugins().keys())
            raise CommandError(
                f'Carrier plugin "{carrier_name}" not found. '
                f'Available plugins: {available}'
            )
        
        # Get workspace
        if workspace_name:
            try:
                workspace = Workspace.objects.get(name=workspace_name)
            except Workspace.DoesNotExist:
                raise CommandError(f'Workspace "{workspace_name}" does not exist')
        else:
            workspace = Workspace.objects.filter(is_active=True).first()
            if not workspace:
                raise CommandError('No active workspace found. Please create a workspace first.')
            self.stdout.write(self.style.WARNING(f'Using workspace: {workspace.name}'))
        
        # Get or create carrier configuration
        if use_existing:
            # Use existing Carrier from database
            try:
                carrier = Carrier.objects.get(
                    workspace=workspace,
                    carrier_type=carrier_name,
                    is_active=True
                )
                config = carrier.get_active_config()
                account = config.get('username') or config.get('account')
                secret = config.get('password') or config.get('secret')
                
                if not account or not secret:
                    raise CommandError(
                        f'Carrier configuration is incomplete. '
                        f'Please configure account and secret in the Carrier.'
                    )
                
                self.stdout.write(self.style.SUCCESS(f'Using existing Carrier: {carrier.name}'))
            except Carrier.DoesNotExist:
                raise CommandError(
                    f'Carrier "{carrier_name}" not found in workspace "{workspace.name}". '
                    f'Please create a Carrier first or use --account/--secret options.'
                )
            except Carrier.MultipleObjectsReturned:
                raise CommandError(
                    f'Multiple "{carrier_name}" carriers found. '
                    f'Please specify workspace or use --account/--secret options.'
                )
        else:
            # Use provided account/secret or create temporary carrier
            if not account or not secret:
                raise CommandError(
                    'Please provide --account and --secret, or use --use-existing to use database configuration'
                )
            
            # Create temporary carrier for testing
            carrier = Carrier(
                workspace=workspace,
                name=f"{plugin_info['display_name']} Test",
                code=f"{carrier_name.upper()}-TEST",
                carrier_type=carrier_name,
                is_test_mode=is_test,
            )
            
            # Set config based on plugin schema
            config = {}
            config_schema = plugin_info.get('config_schema', {})
            
            # Map account to appropriate field
            # Try common field names in order of preference
            account_fields = ['username', 'account', 'api_key', 'api_key_id']
            account_set = False
            for field in account_fields:
                if field in config_schema:
                    config[field] = account
                    account_set = True
                    break
            
            if not account_set:
                # Fallback: use first required field or 'username'
                required_fields = [k for k, v in config_schema.items() if v.get('required', False)]
                if required_fields:
                    config[required_fields[0]] = account
                else:
                    config['username'] = account  # Ultimate fallback
            
            # Map secret to appropriate field
            secret_fields = ['password', 'secret', 'api_secret', 'subscription_key']
            secret_set = False
            for field in secret_fields:
                if field in config_schema:
                    config[field] = secret
                    secret_set = True
                    break
            
            if not secret_set:
                # Fallback: use second required field or 'password'
                required_fields = [k for k, v in config_schema.items() if v.get('required', False)]
                if len(required_fields) > 1:
                    config[required_fields[1]] = secret
                elif required_fields:
                    # Only one required field, try common secret field names
                    for field in secret_fields:
                        if field in config_schema:
                            config[field] = secret
                            secret_set = True
                            break
                if not secret_set:
                    config['password'] = secret  # Ultimate fallback
            
            if is_test:
                carrier.test_config = config
            else:
                carrier.config = config
        
        # Display test information
        self.stdout.write(self.style.SUCCESS(f'Testing {plugin_info["display_name"]} Carrier Plugin'))
        self.stdout.write(f'Workspace: {workspace.name}')
        self.stdout.write(f'Carrier Type: {carrier_name}')
        self.stdout.write(f'Test Mode: {is_test}')
        self.stdout.write(f'Account: {account}')
        self.stdout.write('')
        
        # Get plugin instance
        plugin = get_carrier_plugin(carrier)
        if not plugin:
            raise CommandError(f'Failed to load {carrier_name} plugin')
        
        self.stdout.write(f'Plugin loaded: {plugin.__class__.__name__}')
        self.stdout.write(f'Display name: {plugin.display_name}')
        self.stdout.write(f'Base URL: {plugin.base_url}')
        self.stdout.write('')
        
        # Test authentication
        self.stdout.write('Testing authentication...')
        try:
            token = plugin._get_token()
            self.stdout.write(self.style.SUCCESS('✓ Authentication successful'))
            self.stdout.write(f'  Token: {token[:20]}...')
            self.stdout.write('')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Authentication failed: {e}'))
            self.stdout.write('')
            return
        
        # Test shipping options
        self.stdout.write('Testing shipping options...')
        sender_address = {
            'name': 'Test Sender',
            'company': 'Test Company',
            'line1': '123 Queen Street',
            'city': 'Auckland',
            'postal_code': '1010',
            'country': 'NZ',
            'phone': '021234567',
            'email': 'sender@test.com',
        }
        
        recipient_address = {
            'name': 'Test Recipient',
            'company': 'Test Company 2',
            'line1': '456 Ponsonby Road',
            'city': 'Auckland',
            'postal_code': '1021',
            'country': 'NZ',
            'phone': '029876543',
            'email': 'recipient@test.com',
        }
        
        packages = [
            {
                'weight': 1.5,
                'length': 20,
                'width': 15,
                'height': 10,
                'description': 'Test Package',
            }
        ]
        
        try:
            options = plugin.get_shipping_options(
                sender_address=sender_address,
                recipient_address=recipient_address,
                packages=packages
            )
            self.stdout.write(self.style.SUCCESS(f'✓ Shipping options retrieved: {len(options)} options'))
            for i, option in enumerate(options, 1):
                self.stdout.write(f'  {i}. {option.service_name} ({option.service_code})')
                self.stdout.write(f'     Price: ${option.price} {option.currency}')
                self.stdout.write(f'     Estimated days: {option.estimated_days_min}-{option.estimated_days_max}')
            self.stdout.write('')
            
            # Test creating consignment and getting label
            if options:
                selected_option = options[0]
                self.stdout.write('Testing consignment creation...')
                try:
                    # Prepare metadata from shipping option
                    extra_data = selected_option.extra_data or {}
                    quote_info = extra_data.get('quote', {})
                    metadata = {
                        'quoteRequestID': extra_data.get('quoteRequestID', ''),
                        'carrier_method_id': selected_option.carrier_service_id or quote_info.get('carrier_method_id', ''),
                        'carrier_method_code': selected_option.service_code,
                        'carrier_id': quote_info.get('carrier_id', ''),
                    }
                    
                    # Generate unique reference to avoid duplicate order errors
                    from datetime import datetime
                    unique_reference = f"TEST-ORDER-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    consignment_result = plugin.create_consignment(
                        sender_address=sender_address,
                        recipient_address=recipient_address,
                        packages=packages,
                        service_code=selected_option.service_code,
                        reference=unique_reference,
                        metadata=metadata
                    )
                    
                    if consignment_result.success:
                        tracking_number = consignment_result.tracking_number
                        carrier_consignment_id = consignment_result.carrier_consignment_id
                        self.stdout.write(self.style.SUCCESS(f'✓ Consignment created'))
                        self.stdout.write(f'  Tracking Number: {tracking_number or "N/A"}')
                        if carrier_consignment_id:
                            self.stdout.write(f'  Order ID: {carrier_consignment_id}')
                        self.stdout.write('')
                        
                        # Get label - use order_id/order_number if tracking_number is empty
                        # For Starshipit, we need order_number and service_code to get label
                        self.stdout.write('Testing label retrieval...')
                        label_identifier = tracking_number or carrier_consignment_id
                        if not label_identifier:
                            self.stdout.write(self.style.WARNING('  ⚠ No tracking number or order ID, skipping label retrieval'))
                        else:
                            # Try to get service_code from selected_option
                            service_code_for_label = selected_option.service_code if selected_option else None
                            # Try get_label with service_code and packages if method signature supports it
                            try:
                                # Try with service_code and packages
                                label_result = plugin.get_label(
                                    label_identifier, 
                                    service_code=service_code_for_label,
                                    packages=packages
                                )
                            except TypeError:
                                try:
                                    # Try with service_code only
                                    label_result = plugin.get_label(label_identifier, service_code=service_code_for_label)
                                except TypeError:
                                    # Method doesn't accept service_code parameter, try without it
                                    label_result = plugin.get_label(label_identifier)
                        
                        if label_result.success:
                            self.stdout.write(self.style.SUCCESS(f'✓ Label retrieved'))
                            self.stdout.write(f'  Label URL: {label_result.label_url}')
                            
                            # Download label
                            try:
                                import requests
                                label_response = requests.get(label_result.label_url, timeout=30)
                                if label_response.status_code == 200:
                                    label_size = len(label_response.content)
                                    self.stdout.write(self.style.SUCCESS(f'✓ Label downloaded: {label_size} bytes'))
                                    
                                    # Save label to file
                                    import os
                                    from datetime import datetime
                                    label_dir = '/tmp/parcelport_labels'
                                    os.makedirs(label_dir, exist_ok=True)
                                    label_filename = f'{label_dir}/label_{tracking_number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
                                    with open(label_filename, 'wb') as f:
                                        f.write(label_response.content)
                                    self.stdout.write(f'  Saved to: {label_filename}')
                                else:
                                    self.stdout.write(self.style.ERROR(f'✗ Failed to download label: HTTP {label_response.status_code}'))
                            except Exception as e:
                                self.stdout.write(self.style.ERROR(f'✗ Label download failed: {e}'))
                        else:
                            self.stdout.write(self.style.ERROR(f'✗ Label retrieval failed: {label_result.error}'))
                    else:
                        self.stdout.write(self.style.ERROR(f'✗ Consignment creation failed: {consignment_result.error}'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'✗ Consignment creation failed: {e}'))
                    import traceback
                    self.stdout.write(traceback.format_exc())
                self.stdout.write('')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Shipping options failed: {e}'))
            import traceback
            self.stdout.write(traceback.format_exc())
            self.stdout.write('')
        
        self.stdout.write(self.style.SUCCESS('Test completed!'))
