from decimal import Decimal

import pytest

from bfg.common.models import Customer, User, Workspace
from bfg.inbox.models import Message
from bfg.inbox.notification_templates import ensure_notification_templates
from bfg.shop import tasks
from bfg.shop.models import Order, Store

# The autouse fixture in conftest leaves no workspace bound to the thread, which is
# what a Celery worker sees: there, the tenant-scoped Order.objects returns nothing.

# task, extra arguments, template code it queues
ORDER_TASKS = [
    (tasks.send_order_created_notification, {}, 'order_created'),
    (tasks.send_order_processing_notification, {}, 'order_processing'),
    (tasks.send_order_shipped_notification, {}, 'order_shipped'),
    (tasks.send_order_delivered_notification, {}, 'order_delivered'),
    (tasks.send_order_cancelled_notification, {'reason': 'Out of stock'}, 'order_cancelled'),
    (tasks.send_order_refunded_notification, {'refund_amount': '42.50'}, 'order_refunded'),
]


def _order(slug):
    workspace = Workspace.objects.create(name=slug, slug=slug)
    store = Store.objects.create(workspace=workspace, name='Main', code='main', is_active=True)
    user = User.objects.create(username=f'{slug}-buyer', email=f'{slug}@example.test')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    order = Order.objects.create(
        workspace=workspace, customer=customer, store=store, order_number=f'ORD-{slug}',
        subtotal=Decimal('40.00'), total=Decimal('42.50'),
    )
    return workspace, order


@pytest.fixture
def queued(monkeypatch):
    from bfg.inbox.tasks import send_notification

    calls = []
    monkeypatch.setattr(send_notification, 'delay', lambda **kwargs: calls.append(kwargs))
    return calls


@pytest.mark.django_db
@pytest.mark.parametrize('task, extra, template_code', ORDER_TASKS)
def test_order_task_finds_its_order_with_no_workspace_bound(task, extra, template_code, queued):
    workspace, order = _order(f'task-{template_code}')

    task(workspace.id, order.id, **extra)

    assert [(call['template_code'], call['order_id'], call['customer_id']) for call in queued] == [
        (template_code, order.id, order.customer_id),
    ]
    assert queued[0]['context_data']['order_number'] == order.order_number


@pytest.mark.django_db
def test_order_task_does_not_reach_into_another_workspace(queued):
    _, order = _order('task-owner')
    other = Workspace.objects.create(name='task-other', slug='task-other')

    with pytest.raises(Order.DoesNotExist):
        tasks.send_order_created_notification(other.id, order.id)

    assert queued == []


@pytest.mark.django_db
def test_order_notification_lands_in_the_customer_inbox(monkeypatch):
    from bfg.inbox.tasks import send_notification

    # Run the inbox task in-process rather than publishing it to a broker.
    monkeypatch.setattr(send_notification, 'delay', lambda **kwargs: send_notification(**kwargs))
    workspace, order = _order('task-inbox')
    ensure_notification_templates(workspace)

    tasks.send_order_processing_notification(workspace.id, order.id)

    message = Message.all_objects.get(workspace=workspace)
    assert order.order_number in message.message
    assert message.recipients.filter(recipient=order.customer).exists()
