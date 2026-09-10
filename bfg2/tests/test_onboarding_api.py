"""
The setup wizard over HTTP.

The checklist is readable by any staff member — the dashboard block renders the
progress bar for everyone — but applying a template rewrites the workspace's
currency and publishes public pages, so writes are admin-only.
"""

import pytest
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, User, Workspace

STATUS_URL = '/api/v1/onboarding/status/'
OPTIONS_URL = '/api/v1/onboarding/options/'
PREVIEW_URL = '/api/v1/onboarding/preview/'
APPLY_URL = '/api/v1/onboarding/apply/'
SKIP_URL = '/api/v1/onboarding/skip/'
DISMISS_URL = '/api/v1/onboarding/dismiss/'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Wizard WS', slug='wizard-ws', is_active=True)


def make_client(workspace, username, role_code):
    user = User.objects.create_user(username=username, email=f'{username}@test.com', password='testpass123')
    role, _ = StaffRole.objects.get_or_create(
        workspace=workspace, code=role_code, defaults={'name': role_code.title(), 'is_system': True}
    )
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    api = APIClient()
    api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


@pytest.fixture
def admin_client(workspace):
    return make_client(workspace, 'wizard-admin', 'admin')


@pytest.fixture
def staff_client(workspace):
    return make_client(workspace, 'wizard-staff', 'support')


def test_status_lists_every_step_with_a_percentage(admin_client):
    body = admin_client.get(STATUS_URL).json()

    assert 0 <= body['percent'] <= 100
    assert body['required_total'] > 0
    assert all('items' in step for step in body['steps'])


def test_options_offers_countries_and_industries(admin_client):
    body = admin_client.get(OPTIONS_URL).json()

    codes = {country['code'] for country in body['countries']}
    assert {'NZ', 'CN', 'US'} <= codes
    assert body['defaults']['industry']
    # Both languages of every label, so the client renders in the operator's own.
    assert all('name_zh' in industry for industry in body['industries'])


def test_a_non_admin_staff_member_can_read_but_not_apply(staff_client):
    assert staff_client.get(STATUS_URL).status_code == 200
    assert staff_client.post(APPLY_URL, {'country': 'NZ', 'industry': 'fashion'}, format='json').status_code == 403


def test_an_anonymous_request_gets_nothing(workspace):
    api = APIClient()
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))

    assert api.get(STATUS_URL).status_code in (401, 403)


def test_apply_returns_the_recomputed_status_so_the_ui_need_not_refetch(admin_client):
    body = admin_client.post(APPLY_URL, {'country': 'NZ', 'industry': 'fashion'}, format='json').json()

    assert body['country']['code'] == 'NZ'
    assert any(change['action'] == 'create' for change in body['changes'])
    assert body['status']['percent'] > 0


def test_preview_does_not_change_the_percentage(admin_client):
    before = admin_client.get(STATUS_URL).json()['percent']

    admin_client.post(PREVIEW_URL, {'country': 'NZ', 'industry': 'fashion'}, format='json')

    assert admin_client.get(STATUS_URL).json()['percent'] == before


def test_skipping_an_unknown_item_is_rejected(admin_client):
    response = admin_client.post(SKIP_URL, {'item': 'not.a.real.item'}, format='json')

    assert response.status_code == 400


def test_dismiss_is_remembered(admin_client):
    admin_client.post(DISMISS_URL, {'dismissed': True}, format='json')

    assert admin_client.get(STATUS_URL).json()['state']['dismissed'] is True


def test_country_is_readable_and_writable_through_the_settings_api(admin_client, workspace):
    """It drives tax defaults and the address format, but was on neither the
    serializer's field list nor the service's allowed_fields — so the admin had
    no way to set it and no way to see what it was."""
    from bfg.common.models import Settings

    body = admin_client.get('/api/v1/settings/').json()
    row = body['results'][0] if isinstance(body, dict) and 'results' in body else (
        body[0] if isinstance(body, list) else body
    )
    assert 'country' in row

    settings_id = Settings.objects.get(workspace=workspace).id
    response = admin_client.patch(f'/api/v1/settings/{settings_id}/', {'country': 'NZ'}, format='json')

    assert response.status_code == 200
    assert Settings.objects.get(workspace=workspace).country == 'NZ'


def test_the_country_list_is_the_one_the_wizard_uses(admin_client):
    """Two country tables would disagree the first time either was extended."""
    countries = admin_client.get('/api/v1/countries/').json()
    codes = {c['code'] for c in countries}

    assert len(codes) > 10
    assert {'NZ', 'CN', 'GB'} <= codes
    assert all('name' in c and 'name_zh' in c for c in countries)
