# -*- coding: utf-8 -*-
"""
Event handlers for web (booking) module.
Listen to booking events and trigger async notification tasks.
"""

import logging
from bfg.core.events import global_dispatcher

logger = logging.getLogger(__name__)


def on_booking_created(event_data):
    """
    Handle booking.created event.
    Notify admin group (email + inbox).
    """
    try:
        data = event_data.get('data') or {}
        booking = data.get('booking')
        if not booking:
            return
        from bfg.web.tasks import notify_admin_new_booking
        notify_admin_new_booking.delay(booking.id)
        logger.info("Triggered admin notification for new booking %s", booking.id)
    except Exception as e:
        logger.error("Error handling booking.created event: %s", e, exc_info=True)


def on_booking_status_changed(event_data):
    """
    Handle booking.status_changed event.
    Notify applicant when confirmed; notify admin when confirmed booking is cancelled.
    """
    try:
        data = event_data.get('data') or {}
        booking = data.get('booking')
        old_status = data.get('old_status')
        new_status = data.get('new_status')
        if not booking or new_status is None:
            return
        from bfg.web.tasks import (
            notify_applicant_confirmed,
            notify_admin_confirmed_cancelled,
        )
        if new_status == 'confirmed':
            notify_applicant_confirmed.delay(booking.id)
            logger.info("Triggered applicant confirmed notification for booking %s", booking.id)
        elif old_status == 'confirmed' and new_status == 'cancelled':
            notify_admin_confirmed_cancelled.delay(booking.id)
            logger.info("Triggered admin cancelled notification for booking %s", booking.id)
    except Exception as e:
        logger.error("Error handling booking.status_changed event: %s", e, exc_info=True)


def register_event_handlers():
    """Register booking event handlers."""
    global_dispatcher.listen('booking.created', on_booking_created)
    global_dispatcher.listen('booking.status_changed', on_booking_status_changed)
    logger.info("Registered web booking event handlers")


register_event_handlers()
