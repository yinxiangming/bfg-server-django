"""Customers see their own tickets, returns and account, not the shop's working notes.

The customer ticket endpoints served the staff view of a ticket. Its detail
carried internal notes -- messages staff mark as not for the customer -- with the
assignment history, its reasons, and the assigned agent's email and username;
the list named the assignee. Filing a ticket accepted a category belonging to
another workspace.

The customer block of ``/me/`` and of a customer's orders used the staff customer
serializer the same way, so it carried the shop's notes about that customer, the
credit limit set for them, and every active segment the workspace defines.

Staff and customers share the returns endpoint, and a customer could read the
note the shop keeps on their return.
"""

from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from bfg.common.models import Customer, CustomerSegment, StaffMember, StaffRole, User, Workspace
from bfg.shop.models import Order, Return, Store
from bfg.support.models import SupportTicket, SupportTicketMessage, TicketAssignment, TicketCategory

ME_TICKETS_URL = '/api/v1/me/tickets/'
STAFF_TICKETS_URL = '/api/v1/support/tickets/'
RETURNS_URL = '/api/v1/shop/returns/'

AGENT_USERNAME = 'sam-agent'
AGENT_EMAIL = 'sam.agent@shop.test'
PUBLIC_REPLY = 'We have opened a trace with the courier.'
INTERNAL_NOTE = 'Courier confirmed delivery, hold the refund'
ASSIGNMENT_REASON = 'Escalated for refund review'
CUSTOMER_NOTE = 'Chargeback risk, check before shipping'
SEGMENT_NAME = 'Watchlist'
RETURN_NOTE = 'Seal broken, refund less the restocking fee'


@pytest.fixture(autouse=True)
def _fresh_access_cache():
    """Workspace membership is cached per user id, and ids are reused between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Tickets WS', slug='tickets-ws', is_active=True)


def signed_in(user, workspace):
    # A session login, so the workspace middleware sees who is asking --
    # force_authenticate only reaches the view, after membership is decided.
    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


def listed(response):
    return response.data['results'] if isinstance(response.data, dict) else response.data


@pytest.fixture
def agent(workspace):
    user = User.objects.create_user(
        username=AGENT_USERNAME, email=AGENT_EMAIL, password='x', first_name='Sam', last_name='Agent',
    )
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return user


@pytest.fixture
def customer(workspace):
    user = User.objects.create_user(username='casey', email='casey@test.com', password='x')
    return Customer.objects.create(
        workspace=workspace, user=user, is_active=True, notes=CUSTOMER_NOTE, credit_limit=Decimal('500.00'),
    )


@pytest.fixture
def ticket(workspace, customer, agent):
    ticket = SupportTicket.objects.create(
        workspace=workspace, customer=customer, ticket_number='TKT-STAFF-DATA-1', subject='Parcel not received',
        description='Nothing arrived.', status='open', channel='web', assigned_to=agent,
    )
    SupportTicketMessage.objects.create(ticket=ticket, message=PUBLIC_REPLY, is_staff_reply=True, sender=agent)
    SupportTicketMessage.objects.create(
        ticket=ticket, message=INTERNAL_NOTE, is_staff_reply=True, is_internal=True, sender=agent,
    )
    TicketAssignment.objects.create(ticket=ticket, assigned_to=agent, assigned_by=agent, reason=ASSIGNMENT_REASON)
    return ticket


@pytest.fixture
def segment(workspace):
    return CustomerSegment.objects.create(workspace=workspace, name=SEGMENT_NAME, query={'orders': {'gte': 1}})


@pytest.fixture
def order(workspace, customer):
    # Store.objects is tenant-scoped and empty outside a request; look past the scope.
    store = Store.all_objects.filter(workspace=workspace).first() or Store.objects.create(
        workspace=workspace, name='Main', code='main', is_active=True,
    )
    return Order.objects.create(
        workspace=workspace, store=store, customer=customer, order_number='ORD-STAFF-DATA-1',
        subtotal=Decimal('10.00'), total=Decimal('10.00'),
    )


# --- tickets -------------------------------------------------------------------

def test_a_customer_does_not_see_internal_notes(workspace, customer, ticket):
    response = signed_in(customer.user, workspace).get(f'{ME_TICKETS_URL}{ticket.id}/')

    assert response.status_code == 200, response.data
    assert [message['message'] for message in response.data['messages']] == [PUBLIC_REPLY]
    assert response.data['messages_count'] == 1
    assert INTERNAL_NOTE not in response.content.decode()


def test_a_customer_does_not_see_who_holds_their_ticket_or_why(workspace, customer, ticket):
    response = signed_in(customer.user, workspace).get(f'{ME_TICKETS_URL}{ticket.id}/')

    assert response.status_code == 200, response.data
    for field in ('assigned_to', 'assigned_to_name', 'assigned_to_data', 'assignments', 'team'):
        assert field not in response.data
    body = response.content.decode()
    assert AGENT_EMAIL not in body
    assert AGENT_USERNAME not in body
    assert ASSIGNMENT_REASON not in body


def test_a_customer_sees_the_name_of_whoever_replied(workspace, customer, ticket):
    reply = signed_in(customer.user, workspace).get(f'{ME_TICKETS_URL}{ticket.id}/').data['messages'][0]

    assert reply['sender_name'] == 'Sam Agent'
    assert reply['is_staff_reply'] is True
    assert 'sender' not in reply
    assert 'is_internal' not in reply


def test_an_agent_without_a_name_is_not_named_by_their_username(workspace, customer, ticket, agent):
    agent.first_name = agent.last_name = ''
    agent.save()

    response = signed_in(customer.user, workspace).get(f'{ME_TICKETS_URL}{ticket.id}/')

    assert response.data['messages'][0]['sender_name'] is None
    assert AGENT_USERNAME not in response.content.decode()


def test_a_customer_ticket_list_does_not_name_the_assignee(workspace, customer, ticket):
    response = signed_in(customer.user, workspace).get(ME_TICKETS_URL)

    assert response.status_code == 200, response.data
    rows = listed(response)
    assert [row['id'] for row in rows] == [ticket.id]
    assert 'assigned_to' not in rows[0]
    assert 'assigned_to_name' not in rows[0]
    assert 'Sam Agent' not in response.content.decode()


def test_a_customer_cannot_file_a_ticket_under_another_workspaces_category(workspace, customer):
    elsewhere = Workspace.objects.create(name='Elsewhere', slug='elsewhere', is_active=True)
    foreign = TicketCategory.objects.create(workspace=elsewhere, name='Their category')
    own = TicketCategory.objects.create(workspace=workspace, name='Delivery')
    client = signed_in(customer.user, workspace)

    rejected = client.post(ME_TICKETS_URL, {'subject': 'Hello', 'description': 'Help', 'category': foreign.id}, format='json')
    accepted = client.post(ME_TICKETS_URL, {'subject': 'Hello', 'description': 'Help', 'category': own.id}, format='json')

    assert rejected.status_code == 400, rejected.data
    assert accepted.status_code == 201, accepted.data


def test_staff_still_see_the_whole_ticket(workspace, agent, ticket):
    response = signed_in(agent, workspace).get(f'{STAFF_TICKETS_URL}{ticket.id}/')

    assert response.status_code == 200, response.data
    assert {message['message'] for message in response.data['messages']} == {PUBLIC_REPLY, INTERNAL_NOTE}
    assert response.data['assignments'][0]['reason'] == ASSIGNMENT_REASON
    assert response.data['assigned_to_data']['email'] == AGENT_EMAIL


# --- the customer's own record ---------------------------------------------------

def assert_no_staff_view_of_the_customer(customer_data, body):
    for field in ('notes', 'credit_limit', 'segments'):
        assert field not in customer_data
    assert CUSTOMER_NOTE not in body
    assert SEGMENT_NAME not in body


def test_me_leaves_out_the_shops_notes_about_the_customer(workspace, customer, segment):
    response = signed_in(customer.user, workspace).get('/api/v1/me/')

    assert response.status_code == 200, response.data
    assert response.data['customer']['id'] == customer.id
    assert_no_staff_view_of_the_customer(response.data['customer'], response.content.decode())


def test_an_order_leaves_out_the_shops_notes_about_the_customer(workspace, customer, segment, order):
    response = signed_in(customer.user, workspace).get(f'/api/v1/me/orders/{order.id}/')

    assert response.status_code == 200, response.data
    assert response.data['customer']['id'] == customer.id
    assert_no_staff_view_of_the_customer(response.data['customer'], response.content.decode())


def test_staff_still_see_their_notes_on_the_customer(workspace, agent, customer, segment):
    response = signed_in(agent, workspace).get(f'/api/v1/customers/{customer.id}/')

    assert response.status_code == 200, response.data
    assert response.data['notes'] == CUSTOMER_NOTE
    assert Decimal(str(response.data['credit_limit'])) == Decimal('500.00')


# --- returns -------------------------------------------------------------------

@pytest.fixture
def customers_return(workspace, customer, order):
    return Return.objects.create(
        workspace=workspace, order=order, customer=customer, return_number='RET-STAFF-DATA-1',
        status='rejected', admin_note=RETURN_NOTE,
    )


def test_a_customer_does_not_see_the_shops_note_on_their_return(workspace, customer, customers_return):
    client = signed_in(customer.user, workspace)

    detail = client.get(f'{RETURNS_URL}{customers_return.id}/')
    listing = client.get(RETURNS_URL)

    assert detail.status_code == 200, detail.data
    assert listing.status_code == 200, listing.data
    rows = listed(listing)
    assert [row['id'] for row in rows] == [customers_return.id]
    assert 'admin_note' not in detail.data
    assert 'admin_note' not in rows[0]
    assert RETURN_NOTE not in detail.content.decode() + listing.content.decode()


def test_staff_still_see_their_note_on_a_return(workspace, agent, customers_return):
    response = signed_in(agent, workspace).get(f'{RETURNS_URL}{customers_return.id}/')

    assert response.status_code == 200, response.data
    assert response.data['admin_note'] == RETURN_NOTE
