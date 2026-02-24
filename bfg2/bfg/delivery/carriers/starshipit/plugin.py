"""
Starshipit Carrier Plugin

Integration with Starshipit API for shipping.
API Documentation: https://api-docs.starshipit.com
"""

import requests
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal

from bfg.delivery.carriers.base import (
    BaseCarrierPlugin,
    ShippingOption,
    ConsignmentResult,
    LabelResult,
    TrackingResult,
    TrackingEventData,
)

logger = logging.getLogger(__name__)


class StarshipitCarrier(BaseCarrierPlugin):
    """
    Starshipit shipping carrier plugin.
    
    Supports:
    - Shipping options/quotes
    - Consignment creation
    - Label generation
    - Address validation
    """
    
    carrier_type = 'starshipit'
    display_name = 'Starshipit'
    supported_countries = ['NZ', 'AU']
    
    # API base URL
    API_BASE_URL = 'https://api.starshipit.com'
    
    def __init__(self, carrier):
        super().__init__(carrier)
    
    @property
    def base_url(self) -> str:
        """Get base URL for API requests."""
        return self.API_BASE_URL
    
    def _get_token(self) -> str:
        """
        Get authentication token (for compatibility with test command).
        Starshipit uses API key authentication, so this returns a placeholder.
        """
        return f"API Key: {self.config.get('api_key', '')[:10]}..."
    
    def _validate_config(self):
        """Validate Starshipit configuration."""
        required_fields = ['api_key', 'subscription_key']
        for field in required_fields:
            if not self.config.get(field):
                raise ValueError(f"Starshipit {field} not configured")
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Get Starshipit configuration schema."""
        return {
            'api_key': {
                'type': 'string',
                'required': True,
                'description': 'Starshipit API Key (StarShipIT-Api-Key)',
                'sensitive': True,
            },
            'subscription_key': {
                'type': 'string',
                'required': True,
                'description': 'Starshipit Subscription Key (Ocp-Apim-Subscription-Key)',
                'sensitive': True,
            },
        }
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers with authentication."""
        return {
            'StarShipIT-Api-Key': self.config['api_key'],
            'Ocp-Apim-Subscription-Key': self.config['subscription_key'],
            'Content-Type': 'application/json',
        }
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make authenticated API request."""
        url = f"{self.API_BASE_URL}{endpoint}"
        headers = self._get_headers()
        
        try:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Starshipit API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    logger.error(f"Starshipit API error response: {error_data}")
                except:
                    pass
            raise
    
    def _format_address(self, address: Dict[str, Any]) -> Dict[str, Any]:
        """Format address for Starshipit API."""
        return {
            'street': address.get('line1', ''),
            'suburb': address.get('line2', '') or address.get('suburb', ''),
            'city': address.get('city', ''),
            'post_code': address.get('postal_code', ''),
            'country': address.get('country', 'NZ'),
        }
    
    # ========================================================================
    # Address Validation
    # ========================================================================
    
    def validate_address(
        self,
        address: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate an address with Starshipit."""
        try:
            params = self._format_address(address)
            result = self._make_request('GET', '/api/address/validate', params=params)
            
            if result.get('success') and result.get('valid'):
                return {
                    'valid': True,
                    'original': address,
                    'suggested': result.get('address'),
                }
            else:
                return {
                    'valid': False,
                    'original': address,
                    'suggested': result.get('address'),
                }
                
        except Exception as e:
            logger.error(f"Starshipit validate_address error: {e}")
            return {
                'valid': True,  # Default to valid if validation fails
                'original': address,
                'suggested': None,
            }
    
    # ========================================================================
    # Shipping Options / Quotes
    # ========================================================================
    
    def get_shipping_options(
        self,
        sender_address: Dict[str, Any],
        recipient_address: Dict[str, Any],
        packages: List[Dict[str, Any]]
    ) -> List[ShippingOption]:
        """Get shipping options from Starshipit."""
        try:
            # Build request body for POST /api/rates
            request_body = {
                'destination': {
                    'street': recipient_address.get('line1', ''),
                    'suburb': recipient_address.get('line2', '') or recipient_address.get('suburb', ''),
                    'city': recipient_address.get('city', ''),
                    'state': recipient_address.get('state', ''),
                    'post_code': recipient_address.get('postal_code', ''),
                    'country_code': recipient_address.get('country', 'NZ'),
                },
                'sender': {
                    'street': sender_address.get('line1', ''),
                    'suburb': sender_address.get('line2', '') or sender_address.get('suburb', ''),
                    'city': sender_address.get('city', ''),
                    'state': sender_address.get('state', ''),
                    'post_code': sender_address.get('postal_code', ''),
                    'country_code': sender_address.get('country', 'NZ'),
                },
                'packages': [],
            }
            
            # Add packages
            # Note: Starshipit API expects dimensions in meters, not centimeters
            for pkg in packages:
                package_data = {
                    'weight': float(pkg.get('weight', 1)),
                }
                # Convert cm to meters (divide by 100)
                if pkg.get('length'):
                    package_data['length'] = float(pkg.get('length', 10)) / 100.0
                if pkg.get('width'):
                    package_data['width'] = float(pkg.get('width', 10)) / 100.0
                if pkg.get('height'):
                    package_data['height'] = float(pkg.get('height', 10)) / 100.0
                request_body['packages'].append(package_data)
            
            result = self._make_request('POST', '/api/rates', json_data=request_body)
            
            options = []
            # Starshipit API may return rates directly or in a nested structure
            rates = result.get('rates', [])
            if not rates and isinstance(result, list):
                rates = result
            
            for rate in rates:
                # Handle different response formats
                service_code = rate.get('service_code') or rate.get('carrier_service_code') or rate.get('code', '')
                service_name = rate.get('service_name') or rate.get('carrier_service_name') or rate.get('name', '')
                price = rate.get('price') or rate.get('cost') or rate.get('total', 0)
                
                options.append(ShippingOption(
                    service_code=service_code,
                    service_name=service_name,
                    price=Decimal(str(price)),
                    currency=rate.get('currency', 'NZD'),
                    estimated_days_min=rate.get('estimated_days_min') or rate.get('min_days', 1),
                    estimated_days_max=rate.get('estimated_days_max') or rate.get('max_days', 7),
                    carrier_service_id=rate.get('carrier_service_id') or rate.get('service_id'),
                    extra_data=rate,
                ))
            
            return options
            
        except Exception as e:
            logger.error(f"Starshipit get_shipping_options error: {e}")
            return []
    
    # ========================================================================
    # Consignment Management
    # ========================================================================
    
    def create_consignment(
        self,
        sender_address: Dict[str, Any],
        recipient_address: Dict[str, Any],
        packages: List[Dict[str, Any]],
        service_code: str,
        reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConsignmentResult:
        """Create a consignment with Starshipit."""
        try:
            # Build order JSON (structure based on reference implementation)
            order_json = self._build_order_json(
                sender_address=sender_address,
                recipient_address=recipient_address,
                packages=packages,
                service_code=service_code,
                reference=reference,
                metadata=metadata
            )
            
            result = self._make_request('POST', '/api/orders', json_data=order_json)
            
            # Log full response for debugging
            logger.debug(f"Starshipit create_consignment response: {result}")
            
            # Starshipit API returns order in different formats
            # Check for order in result or result['Order']
            order = result.get('Order') or result.get('order') or result
            
            # Check for errors first
            errors = result.get('errors', [])
            if errors:
                # Check if it's a duplicate order error (which might still have order data)
                is_duplicate = any(
                    'Order Exists' in str(err.get('message', '')) or 
                    'Duplicate order' in str(err.get('message', '')) or
                    'already exists' in str(err.get('message', '')).lower()
                    for err in errors
                )
                
                # If duplicate, try to get existing order info from response or use reference
                if is_duplicate:
                    # Try to extract order info from error details or use reference as order_number
                    order_id = None
                    if order and (order.get('order_id') or order.get('id')):
                        order_id = order.get('order_id') or order.get('id')
                    else:
                        # Use reference as order_number (Starshipit uses order_number to identify orders)
                        reference = order_json.get('Order', {}).get('order_number') or order_json.get('Order', {}).get('reference')
                        if reference:
                            order_id = reference
                    
                    if order_id:
                        tracking_number = (
                            (order or {}).get('tracking_number') if isinstance(order, dict) else None or 
                            (order or {}).get('tracking') if isinstance(order, dict) else None or 
                            (order or {}).get('consignment_number') if isinstance(order, dict) else None or
                            ''
                        )
                        # Store service_code in extra_data
                        extra_data = order.copy() if isinstance(order, dict) else {'order_number': order_id}
                        # Get service_code from order_json if available
                        order_data = order_json.get('Order', {})
                        if service_code:
                            extra_data['carrier_service_code'] = service_code
                        if order_id:
                            extra_data['order_id'] = order_id
                        return ConsignmentResult(
                            success=True,
                            tracking_number=tracking_number,
                            carrier_consignment_id=str(order_id),
                            extra_data=extra_data,
                        )
                
                # Real error
                error_msg = self._extract_error_message(result)
                return ConsignmentResult(
                    success=False,
                    error=error_msg,
                )
            
            # Check for success
            if result.get('success') or order.get('order_id') or order.get('id'):
                # Extract tracking number and order ID
                tracking_number = (
                    order.get('tracking_number') or 
                    order.get('tracking') or 
                    order.get('consignment_number') or
                    ''
                )
                order_id = (
                    order.get('order_id') or 
                    order.get('id') or
                    order.get('order_number') or
                    ''
                )
                
                # Store service_code and order_id in extra_data for later use in get_label
                extra_data = order.copy() if isinstance(order, dict) else {}
                if service_code:
                    extra_data['carrier_service_code'] = service_code
                if order_id:
                    extra_data['order_id'] = order_id
                
                return ConsignmentResult(
                    success=True,
                    tracking_number=tracking_number,
                    carrier_consignment_id=str(order_id),
                    extra_data=extra_data,
                )
            else:
                error_msg = self._extract_error_message(result)
                return ConsignmentResult(
                    success=False,
                    error=error_msg,
                )
                
        except requests.exceptions.HTTPError as e:
            error_msg = str(e)
            try:
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_data = e.response.json()
                        error_msg = self._extract_error_message(error_data)
                        logger.error(f"Starshipit API error response: {error_data}")
                    except:
                        error_msg = f"{e.response.status_code}: {e.response.text[:200]}"
                        logger.error(f"Starshipit API error: {error_msg}")
            except Exception as ex:
                logger.error(f"Error parsing error response: {ex}")
            
            logger.error(f"Starshipit create_consignment error: {error_msg}")
            return ConsignmentResult(
                success=False,
                error=error_msg,
            )
        except Exception as e:
            logger.error(f"Starshipit create_consignment error: {e}")
            return ConsignmentResult(
                success=False,
                error=str(e),
            )
    
    def _build_order_json(
        self,
        sender_address: Dict[str, Any],
        recipient_address: Dict[str, Any],
        packages: List[Dict[str, Any]],
        service_code: str,
        reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build order JSON for Starshipit API."""
        from datetime import datetime
        
        # Build order structure according to Starshipit API
        order_data = {
            'order_number': reference or f"ORDER-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'destination': {
                'name': recipient_address.get('name', ''),
                'email': recipient_address.get('email', ''),
                'company': recipient_address.get('company', ''),
                'phone': recipient_address.get('phone', ''),
                'street': recipient_address.get('line1', ''),
                'suburb': recipient_address.get('line2', '') or recipient_address.get('suburb', ''),
                'city': recipient_address.get('city', ''),
                'state': recipient_address.get('state', ''),
                'post_code': recipient_address.get('postal_code', ''),
                'country': recipient_address.get('country', 'NZ'),
            },
            'sender': {
                'name': sender_address.get('name', ''),
                'email': sender_address.get('email', ''),
                'company': sender_address.get('company', ''),
                'phone': sender_address.get('phone', ''),
                'street': sender_address.get('line1', ''),
                'suburb': sender_address.get('line2', '') or sender_address.get('suburb', ''),
                'city': sender_address.get('city', ''),
                'state': sender_address.get('state', ''),
                'post_code': sender_address.get('postal_code', ''),
                'country': sender_address.get('country', 'NZ'),
            },
            'packages': [],
        }
        
        # Add carrier service code
        if service_code:
            order_data['carrier_service_code'] = service_code
        
        # Add reference if provided
        if reference:
            order_data['reference'] = reference
        
        # Add packages
        # Note: Starshipit API expects dimensions in meters for orders
        # But some endpoints may expect cm - we'll use meters for order creation
        for pkg in packages:
            package_data = {
                'weight': float(pkg.get('weight', 1)),
            }
            # Convert cm to meters (divide by 100) for order creation
            # Input dimensions are assumed to be in cm
            if pkg.get('length'):
                length_cm = float(pkg.get('length', 10))
                package_data['length'] = length_cm / 100.0  # Convert to meters
            if pkg.get('width'):
                width_cm = float(pkg.get('width', 10))
                package_data['width'] = width_cm / 100.0  # Convert to meters
            if pkg.get('height'):
                height_cm = float(pkg.get('height', 10))
                package_data['height'] = height_cm / 100.0  # Convert to meters
            order_data['packages'].append(package_data)
        
        # Add metadata if provided
        if metadata:
            order_data.update(metadata)
        
        # Wrap in Order object (Starshipit API format)
        return {'Order': order_data}
    
    def _extract_error_message(self, result: Dict[str, Any]) -> str:
        """Extract error message from API response."""
        if 'errors' in result and isinstance(result['errors'], list):
            error_messages = []
            for error in result['errors']:
                if isinstance(error, dict):
                    msg = error.get('message', '')
                    details = error.get('details', '')
                    if details:
                        error_messages.append(f"{msg}: {details}")
                    else:
                        error_messages.append(msg)
                else:
                    error_messages.append(str(error))
            return '; '.join(error_messages)
        return result.get('message', 'Unknown error')
    
    # ========================================================================
    # Labels
    # ========================================================================
    
    def get_label(
        self,
        tracking_number: str,
        label_format: str = 'pdf',
        service_code: Optional[str] = None,
        packages: Optional[List[Dict[str, Any]]] = None
    ) -> LabelResult:
        """
        Get shipping label from Starshipit.
        
        According to Starshipit API, print_label returns:
        - labels: array of base64-encoded PDF label data
        - tracking_numbers: array of tracking numbers
        - carrier_name: carrier name
        
        Args:
            tracking_number: Order ID or order number
            label_format: Label format (default: 'pdf')
            service_code: Optional carrier service code (if not provided, will try to get from order)
        """
        try:
            import base64
            
            # According to reference code, print_label needs order_id and carrier_service_code
            # tracking_number might be order_id (integer) or order_number (string)
            json_data = {
                'reprint': False,
            }
            
            # Try to determine if it's order_id (integer) or order_number (string)
            try:
                order_id_int = int(tracking_number)
                json_data['order_id'] = order_id_int
            except ValueError:
                # Not a number, use order_number
                json_data['order_number'] = tracking_number
            
            # Add carrier_service_code if provided
            # According to reference implementation, this is required
            if service_code:
                json_data['carrier_service_code'] = service_code
            else:
                # Log warning if service_code is not provided
                logger.warning("carrier_service_code not provided to get_label, API may require it")
            
            # Add parcel_details if packages are provided
            # Starshipit API requires parcel_details with dimensions in cm when creating shipment
            # Structure: parcel_details[0].dimensions.height_cm
            if packages:
                parcel_details = []
                for pkg in packages:
                    dimensions = {}
                    # Dimensions should be in cm for parcel_details
                    if pkg.get('length'):
                        dimensions['length_cm'] = float(pkg.get('length', 10))
                    if pkg.get('width'):
                        dimensions['width_cm'] = float(pkg.get('width', 10))
                    if pkg.get('height'):
                        dimensions['height_cm'] = float(pkg.get('height', 10))
                    
                    parcel_detail = {
                        'weight': float(pkg.get('weight', 1)),
                    }
                    if dimensions:
                        parcel_detail['dimensions'] = dimensions
                    parcel_details.append(parcel_detail)
                
                if parcel_details:
                    json_data['parcel_details'] = parcel_details
            
            logger.debug(f"Starshipit get_label request: {json_data}")
            result = self._make_request('POST', '/api/orders/shipment', json_data=json_data)
            logger.debug(f"Starshipit get_label response: {result}")
            
            # Check result using same method as reference implementation
            if self._check_result(result):
                # Starshipit returns labels as base64-encoded strings in 'labels' array
                labels = result.get('labels', [])
                if labels and len(labels) > 0:
                    # Decode first label (base64 to bytes)
                    try:
                        label_bytes = base64.b64decode(labels[0])
                        return LabelResult(
                            success=True,
                            label_data=label_bytes,
                            label_format=label_format,
                        )
                    except Exception as decode_error:
                        logger.error(f"Failed to decode label data: {decode_error}")
                        return LabelResult(
                            success=False,
                            error=f'Failed to decode label data: {decode_error}',
                        )
                else:
                    # Check for label_url as fallback
                    label_url = result.get('label_url', '')
                    if label_url:
                        return LabelResult(
                            success=True,
                            label_url=label_url,
                            label_format=label_format,
                        )
                    return LabelResult(
                        success=False,
                        error='No labels in response',
                    )
            else:
                error_msg = self._extract_error_message(result)
                return LabelResult(
                    success=False,
                    error=error_msg,
                )
                
        except Exception as e:
            logger.error(f"Starshipit get_label error: {e}")
            return LabelResult(
                success=False,
                error=str(e),
            )
    
    def _check_result(self, result: Dict[str, Any]) -> bool:
        """Check if API result is successful (same as reference implementation)."""
        return 'success' in result and result['success']
    
    # ========================================================================
    # Webhook Handling
    # ========================================================================
    
    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle Starshipit webhook events."""
        logger.info(f"Starshipit webhook: {event_type}")
        
        if event_type == 'tracking.updated':
            tracking_number = payload.get('tracking_number')
            status = payload.get('status')
            return {
                'success': True,
                'tracking_number': tracking_number,
                'status': status,
                'message': 'Tracking update processed',
            }
        
        return {
            'success': True,
            'message': f'Event {event_type} acknowledged',
        }
