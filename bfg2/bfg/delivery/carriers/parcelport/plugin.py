"""
ParcelPort Carrier Plugin

Integration with ParcelPort API for New Zealand shipping.
API Documentation: https://github.com/ParcelPort/ParcelPort.API
"""

import requests
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime, timedelta

from bfg.delivery.carriers.base import (
    BaseCarrierPlugin,
    ShippingOption,
    ConsignmentResult,
    LabelResult,
    BookingResult,
    TrackingResult,
    TrackingEventData,
)

logger = logging.getLogger(__name__)


class ParcelPortCarrier(BaseCarrierPlugin):
    """
    ParcelPort shipping carrier plugin.
    
    Supports:
    - Shipping options/quotes
    - Consignment creation
    - Label generation
    - Pickup booking
    - Tracking
    """
    
    carrier_type = 'parcelport'
    display_name = 'ParcelPort'
    supported_countries = ['NZ', 'AU']
    
    # API endpoints
    LIVE_URL = 'https://api.parcelport.co.nz'
    TEST_URL = 'https://apitest.parcelport.co.nz'
    
    def __init__(self, carrier):
        super().__init__(carrier)
        self._token = None
        self._token_expires = None
        self._client_id = None
    
    def _validate_config(self):
        """Validate ParcelPort configuration."""
        required_fields = ['username', 'password']
        for field in required_fields:
            if not self.config.get(field):
                raise ValueError(f"ParcelPort {field} not configured")
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Get ParcelPort configuration schema."""
        return {
            'username': {
                'type': 'string',
                'required': True,
                'description': 'ParcelPort API username',
                'sensitive': False,
            },
            'password': {
                'type': 'string',
                'required': True,
                'description': 'ParcelPort API password',
                'sensitive': True,
            },
            'client_id': {
                'type': 'string',
                'required': False,
                'description': 'Optional client ID for sub-accounts',
                'sensitive': False,
            },
            'default_pickup_option': {
                'type': 'integer',
                'required': False,
                'description': 'Default pickup option: 0=book now, 1=schedule later',
                'default': 0,
                'sensitive': False,
            },
        }
    
    @property
    def base_url(self) -> str:
        """Get base URL based on test mode."""
        return self.TEST_URL if self.carrier.is_test_mode else self.LIVE_URL
    
    def _get_token(self) -> str:
        """
        Get or refresh authentication token.
        Token expires in 30 minutes.
        """
        # Check if we have a valid token
        if self._token and self._token_expires:
            if datetime.now() < self._token_expires:
                return self._token
        
        # Request new token
        url = f"{self.base_url}/token"
        data = {
            'username': self.config['username'],
            'password': self.config['password'],
            'grant_type': 'password',
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        try:
            response = requests.post(url, data=data, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # Check for error response format
            if not result.get('isSuccess', True):
                errors = result.get('errors', ['Authentication failed'])
                error_msg = '; '.join(errors) if isinstance(errors, list) else str(errors)
                raise ValueError(f"ParcelPort authentication failed: {error_msg}")
            
            # Check for standard OAuth token format
            if 'access_token' not in result:
                raise ValueError("ParcelPort API response missing access_token field")
            
            self._token = result['access_token']
            # Save client_id from token response
            self._client_id = result.get('client_id')
            # Token expires in 30 minutes, refresh 5 minutes early
            expires_in = result.get('expires_in', 1799)
            self._token_expires = datetime.now() + timedelta(seconds=expires_in - 300)
            
            logger.info(f"ParcelPort: Authentication successful, client_id: {self._client_id}")
            if not self._client_id:
                logger.warning("ParcelPort: No client_id in token response. Some API calls may fail.")
            
            return self._token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"ParcelPort auth failed: {e}")
            raise ValueError(f"ParcelPort authentication failed: {e}")
        except KeyError as e:
            logger.error(f"ParcelPort auth response missing field: {e}")
            raise ValueError(f"ParcelPort authentication failed: Missing field {e}")
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make authenticated API request."""
        token = self._get_token()
        
        url = f"{self.base_url}{endpoint}"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        
        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                params=params,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"ParcelPort API error: {e}")
            raise
    
    def _format_address(self, address: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format address for ParcelPort API.
        
        ParcelPort API requires:
        - address_body: unit number + street number + street name
        - address_city: city
        - address_country: country code (e.g., "NZ")
        - address_postcode: postcode
        - address_number: street number
        - address_street: street name
        - address_suburb: suburb
        """
        line1 = address.get('line1', '')
        # Try to extract street number and street name from line1
        # Simple parsing: assume format like "123 Queen Street" or "12 Pitt Street"
        import re
        match = re.match(r'^(\d+)\s+(.+)$', line1)
        if match:
            address_number = match.group(1)
            address_street = match.group(2)
        else:
            address_number = ''
            address_street = line1
        
        # Keep postal_code as string to preserve leading zeros (e.g., "0630" not 630)
        # ParcelPort API requires 4-digit postcode format: ^\d{4}$
        address_postcode = address.get('postal_code', '')
        
        result = {
            'address_body': line1,  # Full address line
            'address_city': address.get('city', ''),
            'address_country': address.get('country', 'NZ'),
            'address_postcode': address_postcode,
            'address_number': address_number,
            'address_street': address_street,
            'address_suburb': address.get('line2', '') or address.get('city', ''),  # Use line2 or city as suburb
        }
        
        # Add coordinates if available (required by some carriers like postHaste, castleParcels)
        latitude = address.get('latitude')
        longitude = address.get('longitude')
        if latitude is not None and longitude is not None:
            result['address_latitude'] = float(latitude)
            result['address_longitude'] = float(longitude)
        
        return result
    
    def _format_packages(self, packages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format packages for ParcelPort API.
        
        ParcelPort API requires:
        - length, width, height (cm)
        - weight (kg)
        - volume (optional)
        - kind (optional, default 0, 1 if using satchel)
        - group_id (optional, satchel code if using satchel)
        """
        formatted = []
        for pkg in packages:
            formatted.append({
                'length': float(pkg.get('length', 10)),
                'width': float(pkg.get('width', 10)),
                'height': float(pkg.get('height', 10)),
                'weight': float(pkg.get('weight', 1)),
                'volume': float(pkg.get('length', 10) * pkg.get('width', 10) * pkg.get('height', 10) / 1000000),  # Convert to m³
                'kind': pkg.get('kind', 0),
                'group_id': pkg.get('group_id'),
                'cust_ref': pkg.get('description', 'Package'),
            })
        return formatted
    
    # ========================================================================
    # Shipping Options / Quotes
    # ========================================================================
    
    def get_shipping_options(
        self,
        sender_address: Dict[str, Any],
        recipient_address: Dict[str, Any],
        packages: List[Dict[str, Any]]
    ) -> List[ShippingOption]:
        """
        Get shipping options from ParcelPort.
        
        API endpoint: POST /api/1.0/shippingoptions?client_id={client_id}
        """
        try:
            logger.info(f"ParcelPort: Getting shipping options for {len(packages)} packages")
            logger.info(f"ParcelPort: Base URL: {self.base_url} (test_mode: {self.carrier.is_test_mode})")
            logger.debug(f"Sender address: {sender_address.get('name')}, {sender_address.get('city')}, {sender_address.get('country')}")
            logger.debug(f"Recipient address: {recipient_address.get('name')}, {recipient_address.get('city')}, {recipient_address.get('country')}")
            
            # Ensure we have a token and client_id before making the request
            self._get_token()
            
            data = {
                'parcels': self._format_packages(packages),
                'PickupAddress': self._format_address(sender_address),
                'DeliveryAddress': self._format_address(recipient_address),
            }
            
            logger.debug(f"ParcelPort request data: {data}")
            
            # Get client_id from token response or config (client_id is REQUIRED for shippingoptions)
            client_id = self._client_id or self.config.get('client_id')
            
            if not client_id:
                logger.error("ParcelPort: client_id is required but not available. Token response may not have included it.")
                raise ValueError("ParcelPort client_id not available. Please check API credentials or configure client_id manually.")
            
            endpoint = f'/api/1.0/shippingoptions?client_id={client_id}'
            
            logger.info(f"ParcelPort: Calling {self.base_url}{endpoint}")
            result = self._make_request('POST', endpoint, data=data)
            
            logger.debug(f"ParcelPort response: {result}")
            
            options = []
            # Parse response format: quotes array with quoteDetails
            quotes = result.get('quotes', [])
            logger.info(f"ParcelPort: Found {len(quotes)} quotes in response")
            
            if not quotes:
                logger.warning(f"ParcelPort: No quotes returned. Response: {result}")
            
            for quote in quotes:
                quote_type = quote.get('quoteType', {})
                quote_details = quote.get('quoteDetails', [])
                logger.debug(f"Processing quote with {len(quote_details)} details")
                
                for quote_detail in quote_details:
                    quote_info = quote_detail.get('quote', {})
                    package_details = quote_info.get('packageDetails', {})
                    
                    # Extract price
                    total_price = package_details.get('total_price', 0)
                    if not total_price:
                        total_price = package_details.get('price_net', 0)
                    
                    # Extract delivery days from carrier_method_desc or estimate
                    method_desc = quote_info.get('carrier_method_desc', '')
                    min_days = quote_info.get('min_delivery_target', 1)
                    max_days = quote_info.get('max_delivery_target', 7)
                    
                    options.append(ShippingOption(
                        service_code=quote_info.get('carrier_method_code', ''),
                        service_name=quote_info.get('carrier_method_name', ''),
                        price=Decimal(str(total_price)),
                        currency='NZD',
                        estimated_days_min=int(min_days) if min_days else 1,
                        estimated_days_max=int(max_days) if max_days else 7,
                        carrier_service_id=quote_info.get('carrier_method_id'),
                        extra_data={
                            'quoteRequestID': result.get('quoteRequestID'),
                            'quote': quote_info,
                            'quoteType': quote_type,
                        },
                    ))
            
            logger.info(f"ParcelPort: Returning {len(options)} shipping options")
            return options
            
        except Exception as e:
            logger.error(f"ParcelPort get_shipping_options error: {e}", exc_info=True)
            # Re-raise to let caller handle it
            raise
    
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
        """
        Create a consignment with ParcelPort.
        
        API endpoint: PUT /api/1.0/consignment?client_id={client_id}
        
        Note: metadata should contain:
        - QuoteRequestID: Required, from shipping options
        - carrier_method_id: Required, from shipping options
        - carrier_method_code: Required, from shipping options
        - carrier_id: Optional, from shipping options
        """
        try:
            # Format addresses with additional fields for consignment
            pickup_addr = self._format_address(sender_address)
            pickup_addr['email'] = sender_address.get('email', '')
            pickup_addr['company_name'] = sender_address.get('company', '')
            pickup_addr['contact_name'] = sender_address.get('name', '')
            pickup_addr['phone'] = sender_address.get('phone', '')
            
            delivery_addr = self._format_address(recipient_address)
            delivery_addr['email'] = recipient_address.get('email', '')
            delivery_addr['company_name'] = recipient_address.get('company', '')
            delivery_addr['contact_name'] = recipient_address.get('name', '')
            delivery_addr['phone'] = recipient_address.get('phone', '')
            
            data = {
                'parcels': self._format_packages(packages),
                'PickupAddress': pickup_addr,
                'DeliveryAddress': delivery_addr,
                'email_to_recipient': 1,
                'authority_to_leave': 0,
                'is_signature': 0,
            }
            
            # Add required fields from metadata (should come from shipping option)
            if metadata:
                data['QuoteRequestID'] = metadata.get('quoteRequestID', '')
                data['carrier_method_id'] = metadata.get('carrier_method_id', '')
                data['carrier_method_code'] = metadata.get('carrier_method_code', service_code)
                data['carrier_id'] = metadata.get('carrier_id', '')
                if 'authority_to_leave' in metadata:
                    data['authority_to_leave'] = metadata.get('authority_to_leave', 0)
                if 'is_signature' in metadata:
                    data['is_signature'] = metadata.get('is_signature', 0)
            else:
                # Fallback if metadata not provided
                data['carrier_method_code'] = service_code
            
            # Add booking info from metadata or config
            # Priority: metadata > carrier config > default (0)
            default_from_config = self.config.get('default_pickup_option', 0)
            pickup_option = default_from_config  # 0 = book now, 1 = schedule later
            if metadata and 'pickup_option' in metadata:
                pickup_option = metadata.get('pickup_option', default_from_config)
            elif metadata and 'booking' in metadata:
                booking = metadata.get('booking', {})
                pickup_option = booking.get('pickup_option', default_from_config)
            
            data['booking'] = {
                'pickup_option': pickup_option,
            }
            
            if metadata and 'booking' in metadata:
                booking = metadata.get('booking', {})
                if 'instructions' in booking:
                    data['booking']['instructions'] = booking.get('instructions')
            
            # Get client_id
            client_id = self._client_id or self.config.get('client_id')
            endpoint = '/api/1.0/consignment'
            if client_id:
                endpoint = f'{endpoint}?client_id={client_id}'
            
            logger.info(f"ParcelPort: Creating consignment with endpoint: {self.base_url}{endpoint}")
            logger.debug(f"ParcelPort: Request data: {data}")
            logger.debug(f"ParcelPort: Metadata received: {metadata}")
            
            result = self._make_request('PUT', endpoint, data=data)
            
            # Parse response
            consignment_ref = ''
            if result.get('consignmentRef') and isinstance(result.get('consignmentRef'), list):
                consignment_ref = result.get('consignmentRef')[0]
            elif isinstance(result.get('consignmentRef'), str):
                consignment_ref = result.get('consignmentRef')
            
            return ConsignmentResult(
                success=result.get('isSuccess', True),
                tracking_number=consignment_ref,
                carrier_consignment_id=consignment_ref,
                extra_data=result,
            )
            
        except requests.exceptions.HTTPError as e:
            error_msg = str(e)
            try:
                error_data = e.response.json()
                error_msg = error_data.get('message') or error_data.get('errorMessage', str(e))
            except:
                pass
            
            logger.error(f"ParcelPort create_consignment error: {error_msg}")
            return ConsignmentResult(
                success=False,
                error=error_msg,
            )
        except Exception as e:
            logger.error(f"ParcelPort create_consignment error: {e}")
            return ConsignmentResult(
                success=False,
                error=str(e),
            )
    
    # ========================================================================
    # Consignment Cancellation
    # ========================================================================
    
    def cancel_consignment(
        self,
        tracking_number: str
    ) -> ConsignmentResult:
        """
        Cancel a consignment with ParcelPort.
        
        Note: ParcelPort API does not support cancelling/deleting consignments via API.
        According to the official API documentation (https://github.com/ParcelPort/ParcelPort.API),
        there is no DELETE endpoint for consignments. Only creation (PUT) is supported.
        
        To cancel a consignment, you may need to contact ParcelPort support directly.
        """
        logger.warning(
            f"ParcelPort: Cancellation requested for consignment {tracking_number}, "
            "but ParcelPort API does not support this operation. "
            "Please contact ParcelPort support to cancel consignments."
        )
        return ConsignmentResult(
            success=False,
            tracking_number=tracking_number,
            error="ParcelPort API does not support cancelling consignments via API. "
                  "Please contact ParcelPort support directly to cancel consignments.",
        )
    
    # ========================================================================
    # Labels
    # ========================================================================
    
    def get_label(
        self,
        tracking_number: str,
        label_format: str = 'pdf'
    ) -> LabelResult:
        """
        Get shipping label from ParcelPort.
        
        API endpoint: GET /api/1.0/labels?client_id={client_id}&consignmentRef={consignmentRef}
        """
        try:
            # Ensure we have a token and client_id before making the request
            self._get_token()
            
            # Get client_id from token response or config
            client_id = self._client_id or self.config.get('client_id')
            
            if not client_id:
                logger.error("ParcelPort: client_id is required but not available. Token response may not have included it.")
                return LabelResult(
                    success=False,
                    error="ParcelPort client_id not available. Please check API credentials or configure client_id manually.",
                )
            
            endpoint = f'/api/1.0/labels?client_id={client_id}&consignmentRef={tracking_number}'
            
            result = self._make_request('GET', endpoint)
            
            label_url = result.get('url', '')
            
            if not label_url:
                return LabelResult(
                    success=False,
                    error=result.get('message', 'No label URL returned'),
                )
            
            return LabelResult(
                success=result.get('success', True),
                label_url=label_url,
                label_format=label_format,
            )
            
        except Exception as e:
            logger.error(f"ParcelPort get_label error: {e}")
            return LabelResult(
                success=False,
                error=str(e),
            )
    
    # ========================================================================
    # Pickup Booking
    # ========================================================================
    
    def book_pickup(
        self,
        tracking_numbers: List[str],
        pickup_date: str,
        pickup_time_from: Optional[str] = None,
        pickup_time_to: Optional[str] = None,
        instructions: Optional[str] = None
    ) -> BookingResult:
        """Book a pickup with ParcelPort."""
        try:
            data = {
                'TrackingNumbers': tracking_numbers,
                'PickupDate': pickup_date,
            }
            
            if pickup_time_from:
                data['PickupTimeFrom'] = pickup_time_from
            if pickup_time_to:
                data['PickupTimeTo'] = pickup_time_to
            if instructions:
                data['Instructions'] = instructions
            
            result = self._make_request('POST', '/api/1.0/bookings', data=data)
            
            return BookingResult(
                success=True,
                booking_id=result.get('BookingId', ''),
                pickup_date=result.get('PickupDate'),
                pickup_time=result.get('PickupTime'),
            )
            
        except Exception as e:
            logger.error(f"ParcelPort book_pickup error: {e}")
            return BookingResult(
                success=False,
                error=str(e),
            )
    
    # ========================================================================
    # Tracking
    # ========================================================================
    
    def get_tracking(
        self,
        tracking_number: str
    ) -> TrackingResult:
        """Get tracking information from ParcelPort."""
        try:
            params = {
                'TrackingNumber': tracking_number,
            }
            
            result = self._make_request('GET', '/api/1.0/tracking', params=params)
            
            events = []
            for event in result.get('Events', []):
                events.append(TrackingEventData(
                    event_time=event.get('DateTime', ''),
                    event_type=event.get('EventType', ''),
                    description=event.get('Description', ''),
                    location=event.get('Location', ''),
                    is_delivered=event.get('IsDelivered', False),
                ))
            
            # Check if delivered
            is_delivered = any(e.is_delivered for e in events)
            
            return TrackingResult(
                success=True,
                tracking_number=tracking_number,
                status=result.get('Status', ''),
                events=events,
                is_delivered=is_delivered,
            )
            
        except Exception as e:
            logger.error(f"ParcelPort get_tracking error: {e}")
            return TrackingResult(
                success=False,
                tracking_number=tracking_number,
                error=str(e),
            )
    
    # ========================================================================
    # Webhook Handling
    # ========================================================================
    
    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle ParcelPort webhook events."""
        logger.info(f"ParcelPort webhook: {event_type}")
        
        if event_type == 'tracking.updated':
            tracking_number = payload.get('TrackingNumber')
            status = payload.get('Status')
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
