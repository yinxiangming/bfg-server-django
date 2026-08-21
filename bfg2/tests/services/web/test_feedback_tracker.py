"""Feedback issue-tracker backend selection + Azure DevOps payload construction.

Pure unit tests: the tracker helpers are called directly with env monkeypatched and
requests.post faked, so no DB / workspace / HTTP is needed.
"""
import json

import pytest

from bfg.web import views


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_tracker_env(monkeypatch):
    for key in (
        'FEEDBACK_TRACKER',
        'AZURE_DEVOPS_ORG_URL',
        'AZURE_DEVOPS_PROJECT',
        'AZURE_DEVOPS_PAT',
        'AZURE_DEVOPS_BUG_TYPE',
        'AZURE_DEVOPS_FEATURE_TYPE',
        'AZURE_DEVOPS_AREA_PATH',
        'AZURE_DEVOPS_ITERATION_PATH',
    ):
        monkeypatch.delenv(key, raising=False)


def test_tracker_defaults_to_github(monkeypatch):
    """No FEEDBACK_TRACKER -> GitHub backend (zero-regression default)."""
    monkeypatch.setattr(views, '_create_github_feedback_issue', lambda *a, **k: ('GH', None))
    monkeypatch.setattr(views, '_create_azure_devops_feedback_workitem', lambda *a, **k: ('AZ', None))
    assert views._create_feedback_tracker_item('bug', 'x', 'admin', '') == ('GH', None)


def test_tracker_selects_azure(monkeypatch):
    monkeypatch.setenv('FEEDBACK_TRACKER', 'azure')
    monkeypatch.setattr(views, '_create_github_feedback_issue', lambda *a, **k: ('GH', None))
    monkeypatch.setattr(views, '_create_azure_devops_feedback_workitem', lambda *a, **k: ('AZ', None))
    assert views._create_feedback_tracker_item('bug', 'x', 'admin', '') == ('AZ', None)


def test_azure_missing_credentials_noops(monkeypatch):
    """Azure selected but no PAT -> no-op (None, None), never hits the network."""
    monkeypatch.setenv('AZURE_DEVOPS_ORG_URL', 'https://dev.azure.com/acme')
    monkeypatch.setenv('AZURE_DEVOPS_PROJECT', 'proj')
    # PAT intentionally unset
    called = {'post': False}

    def _fail_post(*a, **k):
        called['post'] = True
        raise AssertionError('requests.post should not be called without credentials')

    monkeypatch.setattr('requests.post', _fail_post)
    assert views._create_azure_devops_feedback_workitem('bug', 'x', 'admin', '') == (None, None)
    assert called['post'] is False


def test_azure_builds_bug_workitem_request(monkeypatch):
    monkeypatch.setenv('AZURE_DEVOPS_ORG_URL', 'https://dev.azure.com/acme')
    monkeypatch.setenv('AZURE_DEVOPS_PROJECT', 'My Proj')
    monkeypatch.setenv('AZURE_DEVOPS_PAT', 'secret-pat')
    monkeypatch.setenv('AZURE_DEVOPS_AREA_PATH', 'My Proj\\Area')

    captured = {}

    def _fake_post(url, headers=None, auth=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, auth=auth, body=json, timeout=timeout)
        return _FakeResponse(200, {'id': 42, '_links': {'html': {'href': 'https://az/edit/42'}}})

    monkeypatch.setattr('requests.post', _fake_post)

    item_url, err = views._create_azure_devops_feedback_workitem(
        'bug', 'Login button is broken', 'admin', '',
        page_url='https://app/x', submitter_label='alice@example.com',
    )

    assert err is None
    assert item_url == 'https://az/edit/42'
    # URL: project URL-encoded, work item type as $Bug, api-version present.
    assert captured['url'].startswith('https://dev.azure.com/acme/My%20Proj/_apis/wit/workitems/$Bug')
    assert 'api-version=' in captured['url']
    # PAT via basic auth with empty username; json-patch content type.
    assert captured['auth'] == ('', 'secret-pat')
    assert captured['headers']['Content-Type'] == 'application/json-patch+json'
    # Patch fields.
    fields = {op['path']: op['value'] for op in captured['body']}
    assert fields['/fields/System.Title'].startswith('[Feedback][bug] Login button is broken')
    assert fields['/fields/System.Tags'] == 'feedback; bug'
    assert fields['/fields/System.AreaPath'] == 'My Proj\\Area'
    # Bug type surfaces rich text in Repro Steps, not System.Description.
    assert '/fields/Microsoft.VSTS.TCM.ReproSteps' in fields
    assert '/fields/System.Description' not in fields
    assert 'Login button is broken' in fields['/fields/Microsoft.VSTS.TCM.ReproSteps']


def test_azure_feature_uses_description_field(monkeypatch):
    monkeypatch.setenv('AZURE_DEVOPS_ORG_URL', 'acme')  # bare org name accepted
    monkeypatch.setenv('AZURE_DEVOPS_PROJECT', 'proj')
    monkeypatch.setenv('AZURE_DEVOPS_PAT', 'pat')

    captured = {}

    def _fake_post(url, headers=None, auth=None, json=None, timeout=None):
        captured.update(url=url, body=json)
        return _FakeResponse(201, {'id': 7})

    monkeypatch.setattr('requests.post', _fake_post)

    item_url, err = views._create_azure_devops_feedback_workitem('feature', 'Add dark mode', 'account', '')

    assert err is None
    # Falls back to constructed edit URL when _links is absent.
    assert item_url == 'https://dev.azure.com/acme/proj/_workitems/edit/7'
    assert captured['url'].startswith('https://dev.azure.com/acme/proj/_apis/wit/workitems/$Issue')
    fields = {op['path']: op['value'] for op in captured['body']}
    assert '/fields/System.Description' in fields
    assert '/fields/Microsoft.VSTS.TCM.ReproSteps' not in fields
    assert fields['/fields/System.Tags'] == 'feedback; feature'
