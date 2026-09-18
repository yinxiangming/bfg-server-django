"""
Tasks that event listeners queue wait for the transaction the event came from.

Services emit events inside ``transaction.atomic``, and listeners run there and
then. A task queued straight away can reach a worker before the commit: it finds
no order, retries and may give up, or it announces a change the transaction then
rolls back. Listeners queue through ``bfg.core.events.after_commit`` instead.
"""

from contextlib import suppress
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase

from bfg.common.models import Customer, User, Workspace
from bfg.finance.handlers import on_payment_completed, on_payment_failed
from bfg.shop.handlers import (
    on_order_cancelled,
    on_order_created,
    on_order_delivered,
    on_order_processing,
    on_order_refunded,
    on_order_shipped,
)
from bfg.shop.models import Order, Store
from bfg.shop.services import OrderService
from bfg.web.handlers import on_booking_created, on_booking_status_changed
from bfg.web.services.inquiry_service import InquiryService

WORKSPACE = SimpleNamespace(id=40)
ORDER = SimpleNamespace(id=41, order_number='ORD-41')
PAYMENT = SimpleNamespace(id=42, gateway_response={'error': 'Card declined'})
BOOKING = SimpleNamespace(id=43)

# listener, what its event carries, the task it queues, the arguments it queues it with
LISTENERS = [
    (on_order_created, {'order': ORDER},
     'bfg.shop.tasks.send_order_created_notification', (), {'workspace_id': 40, 'order_id': 41}),
    (on_order_processing, {'order': ORDER},
     'bfg.shop.tasks.send_order_processing_notification', (), {'workspace_id': 40, 'order_id': 41}),
    (on_order_shipped, {'order': ORDER},
     'bfg.shop.tasks.send_order_shipped_notification', (),
     {'workspace_id': 40, 'order_id': 41, 'consignment_id': None}),
    (on_order_delivered, {'order': ORDER},
     'bfg.shop.tasks.send_order_delivered_notification', (), {'workspace_id': 40, 'order_id': 41}),
    (on_order_cancelled, {'order': ORDER, 'reason': 'Out of stock'},
     'bfg.shop.tasks.send_order_cancelled_notification', (),
     {'workspace_id': 40, 'order_id': 41, 'reason': 'Out of stock'}),
    (on_order_refunded, {'order': ORDER, 'refund_amount': '42.50'},
     'bfg.shop.tasks.send_order_refunded_notification', (),
     {'workspace_id': 40, 'order_id': 41, 'refund_amount': '42.50'}),
    (on_payment_completed, {'payment': PAYMENT},
     'bfg.finance.tasks.send_payment_received_notification', (), {'workspace_id': 40, 'payment_id': 42}),
    (on_payment_failed, {'payment': PAYMENT},
     'bfg.finance.tasks.send_payment_failed_notification', (),
     {'workspace_id': 40, 'payment_id': 42, 'failure_reason': 'Card declined'}),
    (on_booking_created, {'booking': BOOKING},
     'bfg.web.tasks.notify_admin_new_booking', (43,), {}),
    (on_booking_status_changed, {'booking': BOOKING, 'old_status': 'pending', 'new_status': 'confirmed'},
     'bfg.web.tasks.notify_applicant_confirmed', (43,), {}),
    (on_booking_status_changed, {'booking': BOOKING, 'old_status': 'confirmed', 'new_status': 'cancelled'},
     'bfg.web.tasks.notify_admin_confirmed_cancelled', (43,), {}),
]


def emit(listener, data):
    listener({'workspace': WORKSPACE, 'user': None, 'data': data})


class ListenersQueueAfterCommitTests(TestCase):
    def test_each_listener_queues_its_task_once_the_transaction_commits(self):
        for listener, data, task_path, args, kwargs in LISTENERS:
            with self.subTest(task=task_path), patch(task_path) as task:
                with self.captureOnCommitCallbacks(execute=True):
                    emit(listener, data)
                    task.delay.assert_not_called()

                task.delay.assert_called_once_with(*args, **kwargs)

    def test_a_listener_whose_transaction_rolls_back_queues_nothing(self):
        for listener, data, task_path, _, _ in LISTENERS:
            with self.subTest(task=task_path), patch(task_path) as task:
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    with suppress(RuntimeError), transaction.atomic():
                        emit(listener, data)
                        raise RuntimeError('rolled back')

                self.assertEqual(callbacks, [])
                task.delay.assert_not_called()

    def test_a_broker_that_is_down_fails_neither_the_commit_nor_the_other_tasks(self):
        with patch('bfg.shop.tasks.send_order_created_notification') as created, \
             patch('bfg.finance.tasks.send_payment_received_notification') as received:
            created.delay.side_effect = ConnectionError('broker down')

            with self.captureOnCommitCallbacks(execute=True):
                emit(on_order_created, {'order': ORDER})
                emit(on_payment_completed, {'payment': PAYMENT})

            created.delay.assert_called_once()
            received.delay.assert_called_once_with(workspace_id=40, payment_id=42)

    def test_inquiry_notifications_wait_for_the_inquiry_to_commit(self):
        # create_inquiry saves the inquiry and schedules these in one transaction.
        site = SimpleNamespace(notification_config={
            'email': {'enabled': True, 'recipients': ['owner@example.test']},
            'webhook': {'enabled': True, 'url': 'https://hooks.example.test/inquiry'},
        })
        inquiry = SimpleNamespace(id=44, site=site)

        with patch('bfg.web.tasks.send_inquiry_email') as email, \
             patch('bfg.web.tasks.send_inquiry_webhook') as webhook:
            with self.captureOnCommitCallbacks(execute=True):
                InquiryService(workspace=WORKSPACE)._send_notifications(inquiry)
                email.delay.assert_not_called()
                webhook.delay.assert_not_called()

            email.delay.assert_called_once_with(44)
            webhook.delay.assert_called_once_with(44)

    def test_inquiry_email_is_queued_without_site_recipients(self):
        site = SimpleNamespace(notification_config={'email': {}})
        inquiry = SimpleNamespace(id=45, site=site)

        with patch('bfg.web.tasks.send_inquiry_email') as email:
            with self.captureOnCommitCallbacks(execute=True):
                InquiryService(workspace=WORKSPACE)._send_notifications(inquiry)
                email.delay.assert_not_called()

            email.delay.assert_called_once_with(45)


class OrderStatusChangeTests(TestCase):
    """The same through a service method that emits inside its own transaction."""

    @classmethod
    def setUpTestData(cls):
        cls.workspace = Workspace.objects.create(name='After commit', slug='after-commit')
        store = Store.objects.create(workspace=cls.workspace, name='Main', code='main', is_active=True)
        user = User.objects.create(username='after-commit-buyer', email='after-commit@example.test')
        customer = Customer.objects.create(workspace=cls.workspace, user=user, is_active=True)
        cls.order = Order.objects.create(
            workspace=cls.workspace, customer=customer, store=store, order_number='ORD-AFTER-COMMIT',
            subtotal=Decimal('40.00'), total=Decimal('42.50'),
        )

    def test_the_notification_is_queued_once_the_status_change_commits(self):
        with patch('bfg.shop.tasks.send_order_processing_notification') as task:
            with self.captureOnCommitCallbacks(execute=True):
                OrderService(workspace=self.workspace).update_order_status(self.order, 'processing')
                # Saved but not committed: a worker would still read the order as pending.
                task.delay.assert_not_called()

            task.delay.assert_called_once_with(workspace_id=self.workspace.id, order_id=self.order.id)

    def test_a_status_change_that_is_rolled_back_queues_nothing(self):
        with patch('bfg.shop.tasks.send_order_processing_notification') as task:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with suppress(RuntimeError), transaction.atomic():
                    OrderService(workspace=self.workspace).update_order_status(self.order, 'processing')
                    raise RuntimeError('the caller fails after the status change')

            self.assertEqual(callbacks, [])
            task.delay.assert_not_called()
