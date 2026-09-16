"""``grant_entitlements``: entitle workspaces to what they already use, before billing starts."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from bfg.common.extensions import registry
from bfg.common.extensions.manifest import (
    PRICING_ADDON,
    PRICING_CORE,
    ExtensionManifest,
)
from bfg.common.models import Workspace, WorkspaceExtension
from bfg.platform.models import WorkspaceEntitlement

ADD_ON = "reviews"
CORE = "orders"

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="First", slug="first-ws", is_active=True)


@pytest.fixture
def manifests(monkeypatch):
    """A deployment shipping one add-on and one part of the base plan."""
    known = {
        ADD_ON: ExtensionManifest(key=ADD_ON, name="Add-on", pricing=PRICING_ADDON),
        CORE: ExtensionManifest(key=CORE, name="Core", pricing=PRICING_CORE),
    }
    monkeypatch.setattr(registry, "get_manifest", known.get)
    return known


def run(*args):
    out = StringIO()
    call_command("grant_entitlements", *args, stdout=out, no_color=True)
    return out.getvalue()


def entitlements_of(workspace, key=WorkspaceEntitlement.KEY_BASE_PLAN):
    return WorkspaceEntitlement.all_objects.filter(workspace=workspace, key=key)


def switched_on(workspace, key, status=WorkspaceExtension.STATUS_ACTIVE):
    return WorkspaceExtension.all_objects.create(workspace=workspace, key=key, status=status)


# ── Picking the workspaces ───────────────────────────────────────────


def test_a_workspace_can_be_named_by_slug_or_by_id(workspace):
    run("--workspace", workspace.slug, "--months", "3")
    assert entitlements_of(workspace).count() == 1

    other = Workspace.objects.create(name="Second", slug="second-ws")
    run("--workspace", str(other.pk), "--months", "3")
    assert entitlements_of(other).count() == 1


def test_all_workspaces_leaves_out_the_ones_that_are_switched_off(workspace):
    inactive = Workspace.objects.create(name="Gone", slug="gone-ws", is_active=False)

    run("--all-workspaces", "--months", "3")

    assert entitlements_of(workspace).exists()
    assert not entitlements_of(inactive).exists()


def test_naming_no_workspace_at_all_is_refused():
    with pytest.raises(CommandError, match="--all-workspaces"):
        run("--months", "3")


def test_naming_a_workspace_that_does_not_exist_is_refused():
    with pytest.raises(CommandError, match="nobody"):
        run("--workspace", "nobody", "--months", "3")


def test_a_period_has_to_be_given():
    with pytest.raises(CommandError):
        run("--all-workspaces")


# ── Picking the keys ─────────────────────────────────────────────────


def test_the_base_plan_is_granted_unless_it_is_asked_not_to_be(workspace):
    run("--workspace", workspace.slug, "--key", ADD_ON, "--no-base-plan", "--months", "3")

    assert not entitlements_of(workspace).exists()
    assert entitlements_of(workspace, ADD_ON).count() == 1


def test_switched_on_grants_the_add_ons_the_workspace_is_using(workspace, manifests):
    switched_on(workspace, ADD_ON)

    run("--workspace", workspace.slug, "--switched-on", "--months", "3")

    assert entitlements_of(workspace, ADD_ON).count() == 1
    assert entitlements_of(workspace).count() == 1


def test_switched_on_leaves_out_what_the_base_plan_already_covers(workspace, manifests):
    switched_on(workspace, CORE)

    run("--workspace", workspace.slug, "--switched-on", "--months", "3")

    assert not entitlements_of(workspace, CORE).exists()


def test_switched_on_leaves_out_an_extension_this_deployment_no_longer_ships(
    workspace, manifests
):
    switched_on(workspace, "vanished")

    run("--workspace", workspace.slug, "--switched-on", "--months", "3")

    assert not entitlements_of(workspace, "vanished").exists()


def test_switched_on_leaves_out_an_add_on_that_is_only_paused(workspace, manifests):
    switched_on(workspace, ADD_ON, status=WorkspaceExtension.STATUS_PAUSED)

    run("--workspace", workspace.slug, "--switched-on", "--months", "3")

    assert not entitlements_of(workspace, ADD_ON).exists()


# ── Granting ─────────────────────────────────────────────────────────


def test_what_is_granted_runs_for_the_months_asked_for_and_says_why(workspace):
    run("--workspace", workspace.slug, "--months", "3", "--reason", "Moving to billing")

    row = entitlements_of(workspace).get()
    assert row.source == WorkspaceEntitlement.SOURCE_GRANTED
    assert row.status == WorkspaceEntitlement.STATUS_ACTIVE
    assert row.reason == "Moving to billing"
    assert row.current_period_end is not None


def test_never_expires_grants_an_entitlement_with_no_end(workspace):
    run("--workspace", workspace.slug, "--never-expires")

    assert entitlements_of(workspace).get().current_period_end is None


def test_running_it_twice_does_not_grant_a_second_entitlement(workspace):
    run("--workspace", workspace.slug, "--months", "3")
    output = run("--workspace", workspace.slug, "--months", "3")

    assert entitlements_of(workspace).count() == 1
    assert "already" in output
    assert "1 already entitled" in output


def test_a_dry_run_writes_nothing_and_says_so(workspace):
    output = run("--workspace", workspace.slug, "--months", "3", "--dry-run")

    assert not entitlements_of(workspace).exists()
    assert "Dry run" in output
    assert "1 granted" in output
