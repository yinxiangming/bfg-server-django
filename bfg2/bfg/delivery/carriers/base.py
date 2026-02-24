"""
Base Carrier Plugin Interface

All carrier plugins must inherit from this base class
and implement the required methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from decimal import Decimal
from dataclasses import dataclass
from django.utils import timezone


@dataclass
class ShippingOption:
    """Shipping option/quote from carrier."""
    service_code: str
    service_name: str
    price: Decimal
    currency: str = 'NZD'
    estimated_days_min: int = 1
    estimated_days_max: int = 7
    carrier_service_id: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class ConsignmentResult:
    """Result of creating a consignment with carrier."""
    success: bool
    tracking_number: str = ''
    carrier_consignment_id: str = ''
    error: str = ''
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class LabelResult:
    """Result of getting shipping label."""
    success: bool
    label_url: str = ''
    label_data: bytes = b''  # PDF binary data
    label_format: str = 'pdf'
    error: str = ''


@dataclass
class BookingResult:
    """Result of booking a pickup."""
    success: bool
    booking_id: str = ''
    pickup_date: Optional[str] = None
    pickup_time: Optional[str] = None
    error: str = ''


@dataclass
class TrackingEventData:
    """A single tracking event."""
    event_time: str
    event_type: str
    description: str
    location: str = ''
    is_delivered: bool = False


@dataclass
class TrackingResult:
    """Result of tracking query."""
    success: bool
    tracking_number: str = ''
    status: str = ''
    events: List[TrackingEventData] = None
    is_delivered: bool = False
    error: str = ''
    
    def __post_init__(self):
        if self.events is None:
            self.events = []


class BaseCarrierPlugin(ABC):
    """
    Base class for all carrier plugins.
    
    Each plugin must implement the abstract methods to provide
    carrier integration functionality.
    """
    
    # Plugin metadata (must be set by subclass)
    carrier_type: str = None  # e.g., 'parcelport', 'nzpost'
    display_name: str = None  # e.g., 'ParcelPort', 'NZ Post'
    supported_countries: List[str] = ['NZ']  # ISO country codes
    
    def __init__(self, carrier):
        """
        Initialize carrier plugin.
        
        Args:
            carrier: Carrier model instance
        """
        if self.carrier_type is None:
            raise ValueError(f"{self.__class__.__name__} must set carrier_type")
        
        # Normalize carrier types for comparison (case-insensitive, strip whitespace)
        expected_type = self.carrier_type.lower().strip() if self.carrier_type else ''
        actual_type = carrier.carrier_type.lower().strip() if carrier.carrier_type else ''
        
        if actual_type and actual_type != expected_type:
            raise ValueError(
                f"Carrier type mismatch: expected '{self.carrier_type}', "
                f"got '{carrier.carrier_type}' (normalized: '{actual_type}' vs '{expected_type}')"
            )
        
        # If carrier has no type set, set it to match this plugin
        if not carrier.carrier_type:
            carrier.carrier_type = self.carrier_type
            carrier.save(update_fields=['carrier_type'])
        
        self.carrier = carrier
        self.config = carrier.get_active_config() or {}
        self._validate_config()
    
    def _validate_config(self):
        """
        Validate carrier configuration.
        Override in subclass to add custom validation.
        """
        pass
    
    # ========================================================================
    # Shipping Options / Quotes
    # ========================================================================
    
    @abstractmethod
    def get_shipping_options(
        self,
        sender_address: Dict[str, Any],
        recipient_address: Dict[str, Any],
        packages: List[Dict[str, Any]]
    ) -> List[ShippingOption]:
        """
        Get available shipping options and quotes.
        
        Args:
            sender_address: Sender address dict with keys:
                - name, company, line1, line2, city, state, postal_code, country, phone
            recipient_address: Recipient address dict (same structure)
            packages: List of package dicts with keys:
                - weight (kg), length, width, height (cm), description
        
        Returns:
            List[ShippingOption]: Available shipping options with prices
        """
        pass
    
    # ========================================================================
    # Consignment Management
    # ========================================================================
    
    @abstractmethod
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
        Create a consignment/shipment with the carrier.
        
        Args:
            sender_address: Sender address dict
            recipient_address: Recipient address dict
            packages: List of package dicts
            service_code: Selected service code from get_shipping_options
            reference: Optional reference number (e.g., order number)
            metadata: Optional additional metadata
        
        Returns:
            ConsignmentResult: Result with tracking_number if successful
        """
        pass
    
    def cancel_consignment(
        self,
        tracking_number: str
    ) -> ConsignmentResult:
        """
        Cancel/delete a consignment with the carrier.
        
        Args:
            tracking_number: Tracking number from create_consignment
        
        Returns:
            ConsignmentResult: Result indicating success or failure
        """
        # Default: not supported
        return ConsignmentResult(
            success=False,
            error='Consignment cancellation not supported by this carrier'
        )
    
    # ========================================================================
    # Labels
    # ========================================================================
    
    @abstractmethod
    def get_label(
        self,
        tracking_number: str,
        label_format: str = 'pdf'
    ) -> LabelResult:
        """
        Get shipping label for a consignment.
        
        Args:
            tracking_number: Tracking number from create_consignment
            label_format: Label format ('pdf', 'zpl', 'png')
        
        Returns:
            LabelResult: Label URL or binary data
        """
        pass
    
    # ========================================================================
    # Pickup Booking (Optional)
    # ========================================================================
    
    def book_pickup(
        self,
        tracking_numbers: List[str],
        pickup_date: str,
        pickup_time_from: Optional[str] = None,
        pickup_time_to: Optional[str] = None,
        instructions: Optional[str] = None
    ) -> BookingResult:
        """
        Book a pickup for consignments.
        
        Args:
            tracking_numbers: List of tracking numbers to pick up
            pickup_date: Requested pickup date (YYYY-MM-DD)
            pickup_time_from: Earliest pickup time (HH:MM)
            pickup_time_to: Latest pickup time (HH:MM)
            instructions: Special instructions for driver
        
        Returns:
            BookingResult: Booking confirmation
        """
        # Default: not supported
        return BookingResult(
            success=False,
            error='Pickup booking not supported by this carrier'
        )
    
    # ========================================================================
    # Tracking
    # ========================================================================
    
    def get_tracking(
        self,
        tracking_number: str
    ) -> TrackingResult:
        """
        Get tracking information for a consignment.
        
        Args:
            tracking_number: Tracking number to query
        
        Returns:
            TrackingResult: Tracking events and current status
        """
        # Default: not supported (use tracking_url_template instead)
        return TrackingResult(
            success=False,
            tracking_number=tracking_number,
            error='Tracking API not supported by this carrier'
        )
    
    # ========================================================================
    # Webhook Handling
    # ========================================================================
    
    def verify_webhook(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """
        Verify webhook signature.
        
        Args:
            payload: Raw webhook payload
            signature: Signature from webhook header
        
        Returns:
            bool: True if signature is valid
        """
        # Default: no verification
        return True
    
    def handle_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle webhook event from carrier.
        
        Args:
            event_type: Event type (e.g., 'tracking.updated')
            payload: Webhook payload data
        
        Returns:
            dict: Processing result
        """
        return {
            'success': True,
            'message': f'Event {event_type} acknowledged'
        }
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def get_config_schema(self) -> Dict[str, Any]:
        """
        Get configuration schema for this carrier.
        
        Returns:
            dict: Configuration schema for admin UI
                {
                    'api_key': {
                        'type': 'string',
                        'required': True,
                        'sensitive': True,
                        'description': '...'
                    },
                    ...
                }
        """
        return {}
    
    def get_tracking_url(self, tracking_number: str) -> Optional[str]:
        """
        Get public tracking URL for a consignment.
        
        Args:
            tracking_number: Tracking number
        
        Returns:
            str: Public tracking URL or None
        """
        if self.carrier.tracking_url_template:
            return self.carrier.tracking_url_template.replace(
                '{tracking_number}', tracking_number
            )
        return None
    
    def validate_address(
        self,
        address: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate an address with the carrier.
        
        Args:
            address: Address dict to validate
        
        Returns:
            dict: Validation result with suggested corrections
        """
        # Default: no validation
        return {
            'valid': True,
            'original': address,
            'suggested': None
        }
