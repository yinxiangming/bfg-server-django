"""The admin's view of the category tree.

The catalogue's language is a property of the data, not of the person editing
it: a New Zealand shop selling to a Chinese-speaking audience keeps Chinese
categories and staff who read the admin in English. Every assertion here is
about not conflating the two.
"""

import pytest
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, User, Workspace
from bfg.shop.models import ProductCategory

LIST_URL = '/api/v1/shop/products/categories/'


def detail_url(category):
    return f'{LIST_URL}{category.id}/'


def names(response):
    """Names in listing order. The endpoint paginates when a page size is
    configured and returns a bare list when it is not."""
    body = response.json()
    rows = body['results'] if isinstance(body, dict) else body
    return [row['name'] for row in rows]


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Category WS', slug='category-ws', is_active=True)


@pytest.fixture
def client(db, workspace):
    user = User.objects.create_user(username='cat-admin', email='cat@test.com', password='testpass123')
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    api = APIClient()
    api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


def make_category(workspace, name, slug, language='zh-hans', **kwargs):
    return ProductCategory.objects.create(
        workspace=workspace, name=name, slug=slug, language=language, **kwargs
    )


def test_detail_is_not_filtered_by_language(client, workspace):
    """The bug this file was written for.

    The clients send no `lang` on a detail request — there is nothing to send,
    since the row's language is what they are asking to find out. `lang` used to
    default to English for every action, so a wholly Chinese catalogue answered
    404 to "open this category", and the admin could neither edit nor delete it.
    """
    category = make_category(workspace, '正在开团', 'group-buy-open')

    response = client.get(detail_url(category))

    assert response.status_code == 200, response.data
    assert response.data['name'] == '正在开团'


def test_a_category_can_be_saved_without_naming_its_language(client, workspace):
    category = make_category(workspace, '临期特价', 'clearance')

    response = client.patch(detail_url(category), {'name': '临期清仓'}, format='json')

    assert response.status_code == 200, response.data
    category.refresh_from_db()
    assert category.name == '临期清仓'


def test_a_category_can_be_deleted_without_naming_its_language(client, workspace):
    category = make_category(workspace, '月饼专区', 'mooncakes')

    response = client.delete(detail_url(category))

    assert response.status_code == 204, getattr(response, 'data', None)
    assert not ProductCategory.objects.filter(id=category.id).exists()


def test_list_falls_back_to_what_the_workspace_actually_has(client, workspace):
    """An English admin over a Chinese catalogue used to see an empty table,
    which reads as "this shop has no categories" rather than "none in English"."""
    make_category(workspace, '养生保健', 'health-wellness')

    assert names(client.get(LIST_URL, {'lang': 'en'})) == ['养生保健']


def test_list_prefers_the_requested_language_when_it_has_rows(client, workspace):
    make_category(workspace, '养生保健', 'health-wellness')
    make_category(workspace, 'Health', 'health', language='en')

    assert names(client.get(LIST_URL, {'lang': 'en'})) == ['Health']


def test_inactive_categories_stay_listed(client, workspace):
    """Switching one off in the admin must not remove the switch."""
    make_category(workspace, '拼团已结束', 'group-buy-closed', is_active=False)
    make_category(workspace, '正在开团', 'group-buy-open', is_active=True)

    assert set(names(client.get(LIST_URL, {'lang': 'zh-hans'}))) == {'拼团已结束', '正在开团'}


def test_is_active_narrows_the_list_when_asked(client, workspace):
    make_category(workspace, '拼团已结束', 'group-buy-closed', is_active=False)
    make_category(workspace, '正在开团', 'group-buy-open', is_active=True)

    assert names(client.get(LIST_URL, {'lang': 'zh-hans', 'is_active': 'true'})) == ['正在开团']


def test_another_workspace_stays_out_of_reach(client, db):
    """The language filter never was the tenancy boundary; the workspace is."""
    other = Workspace.objects.create(name='Other WS', slug='other-ws', is_active=True)
    theirs = make_category(other, '别人家的', 'not-yours')

    assert client.get(detail_url(theirs)).status_code == 404
