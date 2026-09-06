"""Per-workspace social-login credentials.

Google ties an OAuth client to the domains it may render on and the URI it may
return to, and puts the client owner's name on the consent screen. A single
process-wide ``GOOGLE_CLIENT_ID`` can therefore only ever be correct for one
storefront — every other tenant's button dies at Google with ``invalid_client``
before it reaches us. These tests pin the parts of "one client per workspace"
that are easy to get subtly wrong:

* a half-filled provider must not be offered as a login button — the failure
  would otherwise happen at Google, where we cannot see it;
* two workspaces must never see each other's client, which is the entire point;
* re-saving an admin form must not overwrite the stored secret with the mask
  that was rendered in place of it.
"""

import pytest
from rest_framework.test import APIClient

from bfg.common.models import (
    SocialAuthConfig,
    StaffMember,
    StaffRole,
    User,
    Workspace,
    WorkspaceDomain,
)
from bfg.common.social_apps import resolve_social_configs, social_apps_for_workspace

LIST_URL = '/api/v1/social-auth-configs/'
PROVIDERS_URL = '/api/v1/social-auth-configs/providers/'
MASK = '********'


def rows(response):
    """The list payload, paginated or not."""
    body = response.json()
    return body['results'] if isinstance(body, dict) else body


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Geeker', slug='geeker', is_active=True)


@pytest.fixture
def other_workspace(db):
    return Workspace.objects.create(name='Yamei', slug='yamei', is_active=True)


def admin_client(workspace, username):
    user = User.objects.create_user(username=username, email=f'{username}@test.com', password='testpass123')
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    api = APIClient()
    api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


@pytest.fixture
def client(workspace):
    return admin_client(workspace, 'geeker-admin')


def google(workspace, client_id='geeker.apps.googleusercontent.com', **kwargs):
    return SocialAuthConfig.objects.create(
        workspace=workspace, provider='google', client_id=client_id,
        secret=kwargs.pop('secret', 'geeker-secret'), **kwargs
    )


def platform_google(client_id='platform.apps.googleusercontent.com', **kwargs):
    """The operator's shared client — a row belonging to no workspace."""
    return SocialAuthConfig.objects.create(
        workspace=None, provider='google', client_id=client_id,
        secret=kwargs.pop('secret', 'platform-secret'), **kwargs
    )


# --- what counts as a usable provider ---------------------------------------

def test_fully_configured_provider_is_offered(workspace):
    google(workspace)
    assert [app.provider for app in social_apps_for_workspace(workspace)] == ['google']


def test_provider_missing_a_credential_is_not_offered(workspace):
    """Apple signs its secret with a private key, so id+secret is not enough.

    Offering the button anyway moves the failure to Apple's domain, where
    neither we nor the shop owner can see why it broke.
    """
    SocialAuthConfig.objects.create(
        workspace=workspace, provider='apple', client_id='nz.co.geeker', secret='jwt',
    )
    assert social_apps_for_workspace(workspace) == []


def test_inactive_provider_is_not_offered(workspace):
    """Switching a provider off must not require clearing its credentials."""
    google(workspace, is_active=False)
    assert social_apps_for_workspace(workspace) == []


def test_apple_signing_key_travels_in_settings(workspace):
    """allauth 65 reads ``certificate_key`` from ``app.settings``, not the top level."""
    SocialAuthConfig.objects.create(
        workspace=workspace, provider='apple', client_id='nz.co.geeker',
        secret='jwt', key='KEYID123', settings={'certificate_key': '-----BEGIN PRIVATE KEY-----'},
    )
    app = social_apps_for_workspace(workspace)[0]
    assert app.settings['certificate_key'] == '-----BEGIN PRIVATE KEY-----'


def test_apps_are_not_persisted(workspace):
    """allauth drops the token FK for a pk-less app; allauth's own SocialApp
    table stays empty so a credential has exactly one home."""
    google(workspace)
    assert social_apps_for_workspace(workspace)[0].pk is None


# --- the point of the whole exercise ----------------------------------------

def test_each_workspace_gets_its_own_client(workspace, other_workspace):
    google(workspace, client_id='geeker.apps.googleusercontent.com')
    google(other_workspace, client_id='yamei.apps.googleusercontent.com')

    assert social_apps_for_workspace(workspace)[0].client_id == 'geeker.apps.googleusercontent.com'
    assert social_apps_for_workspace(other_workspace)[0].client_id == 'yamei.apps.googleusercontent.com'


def test_workspace_never_borrows_another_workspaces_client(workspace, other_workspace):
    """A neighbour's client is not a fallback — only the platform's is."""
    google(other_workspace)
    assert social_apps_for_workspace(workspace) == []


# --- the platform default ----------------------------------------------------

def test_platform_default_carries_a_workspace_with_no_client(workspace):
    """Most shops never register a client. The redirect flow always returns to
    our own API domain, so one shared client works for all of them."""
    platform_google()
    apps = social_apps_for_workspace(workspace)
    assert [app.client_id for app in apps] == ['platform.apps.googleusercontent.com']


def test_a_workspace_client_overrides_the_platform_default(workspace):
    platform_google()
    google(workspace, client_id='geeker.apps.googleusercontent.com')
    apps = social_apps_for_workspace(workspace)
    assert [app.client_id for app in apps] == ['geeker.apps.googleusercontent.com']


def test_switching_a_provider_off_is_not_a_fallback(workspace):
    """The Active switch has to mean something.

    Falling back to the platform client here would leave the button on the
    sign-in page after the shop deliberately turned it off.
    """
    platform_google()
    google(workspace, is_active=False)
    assert social_apps_for_workspace(workspace) == []


def test_a_half_filled_draft_still_falls_back(workspace):
    """Starting to type credentials must not take a working login away."""
    platform_google()
    SocialAuthConfig.objects.create(
        workspace=workspace, provider='google', client_id='half-typed', secret='',
    )
    apps = social_apps_for_workspace(workspace)
    assert [app.client_id for app in apps] == ['platform.apps.googleusercontent.com']


def test_an_unusable_platform_default_is_not_offered(workspace):
    platform_google(is_active=False)
    assert social_apps_for_workspace(workspace) == []


def test_a_request_with_no_workspace_gets_nothing(db):
    """Inherited by every workspace is not the same as available to anyone.

    Signing someone in without a tenant mints a token with no workspace claim,
    which the middleware rejects on the very next call.
    """
    platform_google()
    assert social_apps_for_workspace(None) == []
    assert resolve_social_configs(None) == {}


# --- admin API ---------------------------------------------------------------

def test_admin_can_store_credentials(client, workspace):
    response = client.post(LIST_URL, {
        'provider': 'google',
        'client_id': 'geeker.apps.googleusercontent.com',
        'secret': 'geeker-secret',
    }, format='json')
    assert response.status_code == 201, response.content
    assert response.json()['is_configured'] is True
    assert SocialAuthConfig.objects.get(workspace=workspace).secret == 'geeker-secret'


def test_secret_is_masked_on_read(client, workspace):
    google(workspace)
    row = rows(client.get(LIST_URL))[0]
    assert row['secret'] == MASK
    # The client id is published to the browser for One Tap, so masking it here
    # would hide nothing and stop an admin checking which client a shop is on.
    assert row['client_id'] == 'geeker.apps.googleusercontent.com'


def test_resaving_the_mask_keeps_the_stored_secret(client, workspace):
    """The admin edits the client id and saves the form as rendered.

    Taking the mask literally would write ``********`` into the credential and
    break the shop's login the next time someone signed in.
    """
    config = google(workspace)
    response = client.patch(f'{LIST_URL}{config.id}/', {
        'client_id': 'new.apps.googleusercontent.com',
        'secret': MASK,
    }, format='json')
    assert response.status_code == 200, response.content

    config.refresh_from_db()
    assert config.client_id == 'new.apps.googleusercontent.com'
    assert config.secret == 'geeker-secret'


def test_a_real_new_secret_replaces_the_old_one(client, workspace):
    config = google(workspace)
    client.patch(f'{LIST_URL}{config.id}/', {'secret': 'rotated'}, format='json')
    config.refresh_from_db()
    assert config.secret == 'rotated'


def test_activating_without_a_required_credential_is_rejected(client):
    response = client.post(LIST_URL, {
        'provider': 'apple',
        'client_id': 'nz.co.geeker',
        'secret': 'jwt',
    }, format='json')
    assert response.status_code == 400
    body = response.json()
    assert 'key' in body and 'certificate_key' in body


def test_an_inactive_draft_may_be_incomplete(client):
    """Half-filled is fine as long as nobody is being shown the button."""
    response = client.post(LIST_URL, {
        'provider': 'apple',
        'client_id': 'nz.co.geeker',
        'is_active': False,
    }, format='json')
    assert response.status_code == 201, response.content
    assert response.json()['is_configured'] is False


def test_duplicate_provider_is_a_field_error_not_a_crash(client, workspace):
    google(workspace)
    response = client.post(LIST_URL, {
        'provider': 'google',
        'client_id': 'second.apps.googleusercontent.com',
        'secret': 'x',
    }, format='json')
    assert response.status_code == 400
    assert 'provider' in response.json()


def test_an_admin_cannot_see_another_workspaces_credentials(client, workspace, other_workspace):
    google(workspace, client_id='geeker.apps.googleusercontent.com')
    google(other_workspace, client_id='yamei.apps.googleusercontent.com')

    listed = {row['client_id'] for row in rows(client.get(LIST_URL))}
    assert listed == {'geeker.apps.googleusercontent.com'}


def test_providers_endpoint_spells_out_the_console_values(client, workspace):
    """Registering the client fails invisibly when an origin or the redirect
    URI is one character off, so the exact strings are served, not documented."""
    WorkspaceDomain.objects.create(
        workspace=workspace, hostname='geeker.co.nz', kind=WorkspaceDomain.KIND_CUSTOM,
    )
    entries = {row['id']: row for row in client.get(PROVIDERS_URL).json()}

    assert entries['google']['redirect_uri'].endswith('/api/v1/auth/google/callback/')
    assert entries['google']['javascript_origins'] == ['https://geeker.co.nz']
    assert entries['apple']['required_fields'] == ['client_id', 'secret', 'key', 'certificate_key']


# --- tracing a request back to its tenant ------------------------------------

class FakeSession(dict):
    """Just enough session for the resolution helpers."""
    modified = False


def request_for(host, session=None, workspace_header=None):
    """A request shaped like the ones the social-login views actually see."""
    from django.test import RequestFactory

    headers = {}
    if workspace_header is not None:
        headers['X-Workspace-ID'] = str(workspace_header)
    request = RequestFactory().get('/api/v1/auth/google/callback/', headers=headers)
    request.META['HTTP_X_FORWARDED_HOST'] = host
    request.session = FakeSession(session or {})
    return request


def domain(workspace, hostname):
    return WorkspaceDomain.objects.create(
        workspace=workspace, hostname=hostname, kind=WorkspaceDomain.KIND_CUSTOM,
    )


def test_workspace_comes_from_the_storefront_host(workspace, other_workspace):
    from bfg.common.social_apps import resolve_social_workspace

    domain(workspace, 'geeker.co.nz')
    domain(other_workspace, 'yamei.co.nz')

    assert resolve_social_workspace(request_for('geeker.co.nz')) == workspace
    assert resolve_social_workspace(request_for('yamei.co.nz')) == other_workspace


def test_login_start_pins_the_workspace_for_the_callback(workspace):
    """The callback is a redirect from Google to *our* domain.

    By then the request carries no storefront host and no tenant header, so
    resolution has to fall back to what login start wrote into the session —
    otherwise the code would be exchanged against the wrong shop's client.
    """
    from bfg.common.social_apps import (
        SOCIAL_WORKSPACE_KEY,
        remember_social_workspace,
        resolve_social_workspace,
    )

    domain(workspace, 'geeker.co.nz')

    start = request_for('geeker.co.nz')
    assert remember_social_workspace(start) == workspace
    assert start.session[SOCIAL_WORKSPACE_KEY] == workspace.id

    # Same session, but now arriving from Google on the API's own hostname.
    callback = request_for('api.surlex.co.nz', session=dict(start.session))
    assert resolve_social_workspace(callback) == workspace


def test_a_pinned_workspace_that_vanished_falls_back_to_the_host(workspace):
    """A deleted workspace must not strand the request on a stale id."""
    from bfg.common.social_apps import SOCIAL_WORKSPACE_KEY, resolve_social_workspace

    domain(workspace, 'geeker.co.nz')
    request = request_for('geeker.co.nz', session={SOCIAL_WORKSPACE_KEY: 999999})
    assert resolve_social_workspace(request) == workspace


def test_an_unknown_host_resolves_to_nothing(db):
    """Better no login button than one signed with a neighbour's client."""
    from bfg.common.social_apps import resolve_social_workspace

    assert resolve_social_workspace(request_for('not-a-tenant.example')) is None


# --- the platform default is the operator's, not the shop's ------------------

def test_the_platform_default_is_invisible_to_a_workspace_admin(client, workspace):
    """A tenant inherits the shared client but must never read its secret,
    and must not be able to edit or delete the row every other shop rides on."""
    default = platform_google()

    assert rows(client.get(LIST_URL)) == []
    assert client.get(f'{LIST_URL}{default.id}/').status_code == 404
    assert client.patch(f'{LIST_URL}{default.id}/', {'client_id': 'x'}, format='json').status_code == 404
    assert client.delete(f'{LIST_URL}{default.id}/').status_code == 404
    default.refresh_from_db()
    assert default.client_id == 'platform.apps.googleusercontent.com'


def test_providers_endpoint_says_where_the_client_came_from(client, workspace):
    """Otherwise the admin sees an empty table while Google sign-in plainly
    works, with nothing to explain why."""
    platform_google()
    entries = {row['id']: row for row in client.get(PROVIDERS_URL).json()}
    assert entries['google']['platform_default_available'] is True
    assert entries['google']['inherited_from_platform'] is True
    assert entries['facebook']['platform_default_available'] is False

    google(workspace)
    entries = {row['id']: row for row in client.get(PROVIDERS_URL).json()}
    assert entries['google']['platform_default_available'] is True
    assert entries['google']['inherited_from_platform'] is False


def test_a_workspace_row_does_not_collide_with_the_platform_row(client, workspace):
    """Both are 'google'; only one of them belongs to this workspace."""
    platform_google()
    response = client.post(LIST_URL, {
        'provider': 'google',
        'client_id': 'geeker.apps.googleusercontent.com',
        'secret': 'geeker-secret',
    }, format='json')
    assert response.status_code == 201, response.content
