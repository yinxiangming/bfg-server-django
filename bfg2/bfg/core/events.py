"""
BFG Event Dispatcher

Event dispatch system for inter-module communication
"""

from typing import Callable, Dict, List
from django.dispatch import Signal


# Define system event signals
workspace_created = Signal()
customer_created = Signal()
product_created = Signal()
order_created = Signal()
order_paid = Signal()
order_shipped = Signal()
order_delivered = Signal()
payment_confirmed = Signal()
payment_failed = Signal()
consignment_status_changed = Signal()


class EventDispatcher:
    """
    Event Dispatcher
    
    Used for registering and dispatching business events
    """
    
    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = {}
        self._signal_map = {
            'workspace.created': workspace_created,
            'customer.created': customer_created,
            'product.created': product_created,
            'order.created': order_created,
            'order.paid': order_paid,
            'order.shipped': order_shipped,
            'order.delivered': order_delivered,
            'payment.confirmed': payment_confirmed,
            'payment.failed': payment_failed,
            'consignment.status_changed': consignment_status_changed,
        }
    
    def listen(self, event_name: str, callback: Callable):
        """
        Register event listener
        
        Args:
            event_name: Event name (e.g., 'order.created')
            callback: Callback function
        """
        if event_name not in self.listeners:
            self.listeners[event_name] = []
        self.listeners[event_name].append(callback)
    
    def dispatch(self, event_name: str, data: dict):
        """
        Dispatch event
        
        Args:
            event_name: Event name
            data: Event data
        """
        # Call directly registered listeners
        if event_name in self.listeners:
            for callback in self.listeners[event_name]:
                try:
                    callback(data)
                except Exception as e:
                    # Log error but don't interrupt other listeners
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error in event listener for {event_name}: {e}")
        
        # Send Django Signal
        signal = self._get_signal(event_name)
        if signal:
            try:
                signal.send(sender=None, **data)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error sending signal for {event_name}: {e}")
    
    def _get_signal(self, event_name: str):
        """Get corresponding Django Signal"""
        return self._signal_map.get(event_name)
    
    def remove_listener(self, event_name: str, callback: Callable):
        """
        Remove event listener
        
        Args:
            event_name: Event name
            callback: Callback function
        """
        if event_name in self.listeners:
            try:
                self.listeners[event_name].remove(callback)
            except ValueError:
                pass


# Global event dispatcher instance
global_dispatcher = EventDispatcher()
