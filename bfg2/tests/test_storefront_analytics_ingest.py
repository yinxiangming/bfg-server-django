"""
The storefront analytics relay: what a caller is allowed to put into GA4.

This endpoint is unauthenticated by necessity — most storefront traffic is
anonymous — so everything it accepts, a stranger can send. The exposure is the
same one gtag.js already has (a measurement id is public, and anyone can post to
Google's collect endpoint with it), but two things still have to hold:

* a caller must not be able to invent revenue. `purchase` is reported from
  `order.paid` against the order record, so accepting it here would both let
  anyone post arbitrary money into the property and double-count every real sale;
* a caller must not be able to invent GA4 schema. A typo'd or hostile parameter
  name creates a custom dimension that cannot be deleted afterwards, so names are
  matched against GA4's own rules rather than passed through.

The rest pins the quiet parts: an unconfigured workspace must accept and discard
rather than error, and a caller must never be able to attribute their traffic to
somebody else's customer id.
"""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Settings, Workspace

COLLECT_URL = '/api/v1/store/analytics/collect/'


@pytest.fixture
def workspace(db):
    ws = Workspace.objects.create(name='Ingest WS', slug='ingest-ws', is_active=True)
    settings_obj, _ = Settings.objects.get_or_create(workspace=ws)
    settings_obj.custom_settings = {'analytics': {'google_analytics_id': 'G-TESTONLY01'}}
    settings_obj.save(update_fields=['custom_settings'])
    return ws


@pytest.fixture
def client(workspace):
    api = APIClient()
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


@pytest.fixture
def sent():
    """Capture what would have been queued, so tests assert on the GA4 payload."""
    with patch('bfg.shop.viewsets.storefront_analytics.track_many') as track:
        yield track


def post(client, events, client_id='55.66'):
    return client.post(COLLECT_URL, {'client_id': client_id, 'events': events}, format='json')


# --------------------------------------------------------------------------- happy path


def test_a_screen_view_reaches_ga4(client, workspace, sent):
    response = post(client, [{'name': 'screen_view', 'params': {'screen_name': 'Home'}}])

    assert response.status_code == 202
    ws_id, client_id, events = sent.call_args[0]
    assert ws_id == workspace.id
    assert client_id == '55.66'
    assert events == [{'name': 'screen_view', 'params': {'screen_name': 'Home'}}]


def test_items_survive_as_a_nested_list(client, sent):
    post(client, [{
        'name': 'add_to_cart',
        'params': {'currency': 'NZD', 'value': 12.5,
                   'items': [{'item_id': 'W-1', 'item_name': 'Widget', 'quantity': 2}]},
    }])

    _, _, events = sent.call_args[0]
    assert events[0]['params']['items'] == [
        {'item_id': 'W-1', 'item_name': 'Widget', 'quantity': 2}
    ]


# --------------------------------------------------------------------------- what is refused


def test_purchase_cannot_be_posted_by_a_client(client, sent):
    """Revenue comes from order.paid; accepting it here would let anyone mint money."""
    response = post(client, [{'name': 'purchase', 'params': {'value': 999999}}])

    assert response.status_code == 400
    sent.assert_not_called()


def test_an_unknown_event_name_is_refused(client, sent):
    response = post(client, [{'name': 'totally_made_up', 'params': {}}])

    assert response.status_code == 400
    sent.assert_not_called()


def test_parameter_names_that_would_create_junk_dimensions_are_dropped(client, sent):
    post(client, [{'name': 'search', 'params': {
        'search_term': 'widget',
        'Screen Name': 'nope',        # spaces and capitals
        '_leading': 'nope',           # must start with a letter
        'x' * 50: 'nope',             # over GA4's 40-char limit
    }}])

    _, _, events = sent.call_args[0]
    assert events[0]['params'] == {'search_term': 'widget'}


def test_long_string_values_are_truncated_not_rejected(client, sent):
    post(client, [{'name': 'search', 'params': {'search_term': 'x' * 500}}])

    _, _, events = sent.call_args[0]
    assert len(events[0]['params']['search_term']) == 100


def test_unserialisable_values_are_dropped(client, sent):
    post(client, [{'name': 'search', 'params': {
        'search_term': 'widget',
        'nested': {'not': 'allowed'},
        'listy': [1, 2, 3],
    }}])

    _, _, events = sent.call_args[0]
    assert events[0]['params'] == {'search_term': 'widget'}


def test_more_events_than_the_protocol_allows_is_refused(client, sent):
    response = post(client, [{'name': 'screen_view', 'params': {}} for _ in range(40)])

    assert response.status_code == 400
    sent.assert_not_called()


def test_a_client_id_is_required(client, sent):
    response = client.post(COLLECT_URL, {'events': [{'name': 'screen_view'}]}, format='json')

    assert response.status_code == 400
    sent.assert_not_called()


# --------------------------------------------------------------------------- identity


def test_an_anonymous_caller_gets_no_user_id(client, sent):
    post(client, [{'name': 'screen_view', 'params': {}}])

    assert sent.call_args.kwargs['user_id'] is None


def test_a_caller_cannot_attribute_traffic_to_another_customer(client, sent):
    """`user_id` is resolved from the request's own auth, never from the body."""
    post(client, [{'name': 'screen_view', 'params': {'user_id': 4242}}])

    assert sent.call_args.kwargs['user_id'] is None
    _, _, events = sent.call_args[0]
    # It may survive as a harmless custom parameter, but never as GA4 identity.
    assert 'user_id' not in str(sent.call_args.kwargs.get('user_id'))


def test_a_signed_in_shopper_is_reported_with_their_customer_id(workspace, sent):
    from bfg.common.models import Customer, User

    user = User.objects.create(username='ingest', email='ingest@example.com', is_active=True)
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)

    api = APIClient()
    api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    post(api, [{'name': 'screen_view', 'params': {}}])

    assert sent.call_args.kwargs['user_id'] == customer.id


# --------------------------------------------------------------------------- workspace gating


def test_a_workspace_without_ga4_accepts_and_discards(db):
    """Accepting is right: the client cannot fix it, and 4xx would just retry-loop."""
    ws = Workspace.objects.create(name='No GA4', slug='no-ga4', is_active=True)
    api = APIClient()
    api.credentials(HTTP_X_WORKSPACE_ID=str(ws.id))

    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay:
        response = post(api, [{'name': 'screen_view', 'params': {}}])

    assert response.status_code == 202
    delay.assert_not_called()


def test_a_request_with_no_resolvable_workspace_never_reaches_ga4(db):
    """
    Rejected by WorkspaceMiddleware with a 400 before the view runs — the view's own
    404 guard is a fallback for any path the middleware does not cover. Either way
    the point is that events cannot arrive without a tenant to attribute them to.
    """
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay:
        response = APIClient().post(
            COLLECT_URL, {'client_id': '1.2', 'events': [{'name': 'screen_view'}]}, format='json'
        )

    assert response.status_code == 400
    delay.assert_not_called()
