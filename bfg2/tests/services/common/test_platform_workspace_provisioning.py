"""
Workspaces created through the platform API on a standalone platform.

``POST /api/v1/platform/workspaces/`` creates the workspace and, standalone, queues
the ``provision_workspace`` task for the rest. (Embedded, the request provisions the
workspace itself; see ``tests/services/platform/test_workspace_creation.py``.) The
test settings would run that task eagerly, inside the request, but a worker runs it
later with no workspace bound to the thread. So ``.delay`` is captured here and the
task is called directly once the thread is clear.
"""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.middleware import get_current_workspace, set_current_workspace
from bfg.common.models import Settings, Workspace
from bfg.inbox.models import MessageTemplate
from bfg.inbox.notification_templates import NOTIFICATION_CODES
from bfg.platform.models import WorkspaceOperation
from bfg.platform.services.ownership import assign_workspace_owner
from bfg.platform.services.provision_service import provision_workspace

User = get_user_model()


@pytest.fixture(autouse=True)
def standalone(settings):
    settings.PLATFORM_EMBEDDED = False


@pytest.fixture
def queued(monkeypatch):
    """The ``provision_workspace.delay`` calls a create makes, captured instead of sent.

    Patched where ``create_owned_workspace`` looks the task up. The task is a proxy
    to the current Celery app's copy of it, and the app a request runs under need not
    be the one current when this fixture runs.
    """
    from bfg.platform.services import workspace_creation

    calls = []
    monkeypatch.setattr(
        workspace_creation, 'provision_workspace', SimpleNamespace(delay=lambda **kwargs: calls.append(kwargs)),
    )
    return calls


def create_through_api(slug):
    owner = User.objects.create_user(username=f'{slug}-owner', password='x')
    # Only an account that already owns or administers a workspace may create one.
    assign_workspace_owner(Workspace.objects.create(name=f'{slug} first', slug=f'{slug}-first'), owner)
    api = APIClient()
    api.force_authenticate(user=owner)
    response = api.post('/api/v1/platform/workspaces/', {'name': slug.title(), 'slug': slug}, format='json')
    assert response.status_code == 201, response.data
    return Workspace.objects.get(slug=slug)


def run_queued(queued):
    """Run the queued tasks as a worker would, with no workspace bound."""
    set_current_workspace(None)
    assert get_current_workspace() is None
    return [provision_workspace(**kwargs) for kwargs in queued]


@pytest.mark.django_db
def test_provisioning_gives_the_workspace_its_notification_templates(queued):
    workspace = create_through_api('api-shop')
    # The request leaves them to the task.
    assert not MessageTemplate.objects.filter(workspace=workspace).exists()

    [result] = run_queued(queued)

    templates = MessageTemplate.objects.filter(workspace=workspace)
    assert sorted(templates.values_list('code', flat=True)) == sorted(NOTIFICATION_CODES)
    # Nothing in this flow sets a locale, so they are written in the settings defaults.
    assert set(templates.values_list('language', flat=True)) == {'en'}
    assert result['notification_templates'] == list(NOTIFICATION_CODES)
    assert WorkspaceOperation.objects.get(workspace=workspace).status == 'completed'


@pytest.mark.django_db
def test_provisioning_writes_them_in_the_workspace_language_and_currency(queued):
    workspace = create_through_api('api-shop-zh')
    Settings.objects.filter(workspace=workspace).update(default_language='zh-hans', default_currency='NZD')

    run_queued(queued)

    templates = MessageTemplate.objects.filter(workspace=workspace)
    assert set(templates.values_list('language', flat=True)) == {'zh-hans'}
    assert '合计 NZ$' in templates.get(code='order_created').app_message_body


@pytest.mark.django_db
def test_a_retried_task_adds_no_second_set(queued):
    workspace = create_through_api('api-shop-retry')

    run_queued(queued)
    [retry] = run_queued(queued)

    assert retry['notification_templates'] == []
    assert MessageTemplate.objects.filter(workspace=workspace).count() == len(NOTIFICATION_CODES)
