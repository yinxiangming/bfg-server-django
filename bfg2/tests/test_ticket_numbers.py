"""Ticket numbers.

``ticket_number`` is unique across every workspace. A ticket staff open carries
the workspace id in its number, but one a customer opened from their account was
numbered ``TKT-<date>-<n>``, with ``n`` counted in its own workspace -- so the
second shop to take a customer ticket on a given day collided with the first,
and the customer's request failed.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from bfg.common.models import Customer, StaffMember, StaffRole, User, Workspace
from bfg.support.models import SupportTicket

ME_TICKETS_URL = '/api/v1/me/tickets/'
STAFF_TICKETS_URL = '/api/v1/support/tickets/'


@pytest.fixture(autouse=True)
def _fresh_access_cache():
    """Workspace membership is cached per user id, and ids are reused between tests."""
    cache.clear()
    yield
    cache.clear()


def make_workspace(slug):
    return Workspace.objects.create(name=slug, slug=slug, is_active=True)


def signed_in(user, workspace):
    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


def customer_of(workspace):
    user = User.objects.create_user(
        username=f'shopper-{workspace.slug}', email=f'shopper-{workspace.slug}@test.com', password='x',
    )
    return Customer.objects.create(workspace=workspace, user=user, is_active=True)


def staff_of(workspace):
    user = User.objects.create_user(
        username=f'staff-{workspace.slug}', email=f'staff-{workspace.slug}@test.com', password='x',
    )
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return signed_in(user, workspace)


def open_from_account(customer, subject):
    response = signed_in(customer.user, customer.workspace).post(
        ME_TICKETS_URL, {'subject': subject, 'description': 'Where is my parcel?'}, format='json',
    )
    assert response.status_code == 201, response.data
    # The create response echoes the form without the number. SupportTicket.objects is
    # tenant-scoped and empty outside a request; look past the scope.
    return SupportTicket.all_objects.get(workspace=customer.workspace, subject=subject).ticket_number


def test_customers_of_two_shops_open_tickets_on_the_same_day(db):
    first_shop, second_shop = make_workspace('first-shop'), make_workspace('second-shop')

    first = open_from_account(customer_of(first_shop), 'Parcel from the first shop')
    second = open_from_account(customer_of(second_shop), 'Parcel from the second shop')

    assert first != second


def test_staff_and_customer_tickets_share_one_sequence_in_a_shop(db):
    shop = make_workspace('one-shop')
    customer = customer_of(shop)
    from_account = open_from_account(customer, 'Asked from the account page')

    response = staff_of(shop).post(
        STAFF_TICKETS_URL,
        {'subject': 'Taken by phone', 'description': 'Called about a refund', 'customer': customer.id},
        format='json',
    )

    assert response.status_code == 201, response.data
    prefix, sequence = from_account.rsplit('-', 1)
    assert response.data['ticket_number'] == f'{prefix}-{int(sequence) + 1:04d}'
