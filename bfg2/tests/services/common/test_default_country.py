"""
The workspace default country.

`bfg.delivery` used to fall back to a hardcoded country code in four places when a
warehouse or a caller-supplied pickup address had none — the country the platform's
first tenant happened to sell in. On a multi-tenant platform that is not a safe default
but a wrong address: an under-configured workspace had its freight quoted from the wrong
hemisphere, and nothing failed to say so. The country now comes from the workspace's own
settings, with one system-level constant as the last resort.
"""

import pytest

from bfg.common.constants import (
    DEFAULT_COUNTRY_CODE,
    get_default_country_for_workspace,
)
from bfg.common.models import Settings, Workspace


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Country Test', slug='country-test', is_active=True)


def set_country(workspace, country):
    """A Settings row is created with the workspace, so set the field on the existing one."""
    Settings.objects.update_or_create(workspace=workspace, defaults={'country': country})
    workspace.refresh_from_db()
    return workspace


def test_the_workspaces_own_country_is_used(workspace):
    assert get_default_country_for_workspace(set_country(workspace, 'NZ')) == 'NZ'


def test_a_different_workspace_gets_its_own_country(workspace, db):
    other = Workspace.objects.create(name='Other', slug='other-country', is_active=True)
    set_country(workspace, 'NZ')
    set_country(other, 'AU')
    assert get_default_country_for_workspace(other) == 'AU'
    assert get_default_country_for_workspace(workspace) == 'NZ'


def test_a_workspace_that_has_not_said_where_it_ships_from_gets_no_guess(workspace):
    assert get_default_country_for_workspace(set_country(workspace, '')) == DEFAULT_COUNTRY_CODE


def test_a_workspace_with_no_settings_row_at_all_gets_no_guess(workspace):
    Settings.objects.filter(workspace=workspace).delete()
    workspace.refresh_from_db()
    assert get_default_country_for_workspace(workspace) == DEFAULT_COUNTRY_CODE


def test_no_workspace_gets_no_guess():
    assert get_default_country_for_workspace(None) == DEFAULT_COUNTRY_CODE


def test_the_constant_names_no_country():
    """The fallback is deliberately empty — see the comment on the constant."""
    assert DEFAULT_COUNTRY_CODE == ''
