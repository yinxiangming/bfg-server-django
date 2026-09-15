"""
BFG Event Dispatcher

Event dispatch system for inter-module communication
"""

import logging
from typing import Callable, Dict, List

from django.db import transaction
from django.dispatch import Signal

logger = logging.getLogger(__name__)


# Define system event signals
workspace_created = Signal()
customer_created = Signal()
product_created = Signal()
order_created = Signal()
order_paid = Signal()
order_shipped = Signal()
order_ready_for_pickup = Signal()
order_delivered = Signal()
payment_confirmed = Signal()
payment_failed = Signal()
consignment_status_changed = Signal()


def after_commit(func: Callable, *args, **kwargs) -> None:
    """Call ``func(*args, **kwargs)`` once the current transaction has committed.

    Listeners run inside the transaction their event was emitted in, and a task
    queued from there can reach a worker before that transaction commits: the row
    it loads is not there yet, or it still reads the state from before the
    change. When the transaction rolls back the call never happens; outside a
    transaction it happens straight away.

    Whatever ``func`` raises is logged rather than raised. The data is committed
    by then, and a failed call must not stop the others waiting on the same commit.
    """
    def call():
        try:
            func(*args, **kwargs)
        except Exception:
            logger.exception('Error calling %r after commit', func)

    transaction.on_commit(call)


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
            'order.ready_for_pickup': order_ready_for_pickup,
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

        Listeners run synchronously, inside whatever transaction the emitter
        holds. A listener that queues a task, or reports the event anywhere
        outside the database, does so through ``after_commit``.
        
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
            callback: Callback function, or the callback a wrapping listener was
                registered for (``bfg.common.extensions.listen_for``)
        """
        listeners = self.listeners.get(event_name, [])
        for registered in listeners:
            if registered == callback or getattr(registered, '__wrapped__', None) == callback:
                listeners.remove(registered)
                return


# Global event dispatcher instance
global_dispatcher = EventDispatcher()
