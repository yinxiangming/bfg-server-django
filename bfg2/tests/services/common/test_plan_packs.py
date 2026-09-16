"""Plan packs: the set of extensions a kind of shop starts with."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from bfg.common.extensions import packs, registry
from bfg.common.extensions.manifest import PRICING_ADDON, ExtensionManifest
from bfg.common.extensions.services import ExtensionError
from bfg.common.models import Workspace, WorkspaceExtension

FIRST = "first_key"
SECOND = "second_key"

PACKS = {
    "boutique": {
        "name": "Boutique",
        "name_zh": "精品",
        "industries": ("fashion",),
        "extensions": (FIRST, SECOND),
    },
    "bare": {"name": "Bare", "industries": ("b2b_wholesale",), "extensions": ()},
}

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="Packed", slug="packed-ws", is_active=True)


@pytest.fixture
def deployed(monkeypatch, settings):
    """A deployment shipping two add-ons and offering the packs above."""
    known = {
        key: ExtensionManifest(key=key, name=key, pricing=PRICING_ADDON)
        for key in (FIRST, SECOND)
    }
    monkeypatch.setattr(registry, "get_manifest", known.get)
    monkeypatch.setattr(registry, "all_manifests", lambda: list(known.values()))
    settings.BFG_EXTENSION_PLAN_PACKS = PACKS
    return known


def run(*args):
    out = StringIO()
    call_command("plan_packs", *args, stdout=out, no_color=True)
    return out.getvalue()


def status_of(workspace, key):
    record = WorkspaceExtension.all_objects.filter(workspace=workspace, key=key).first()
    return record.status if record else None


# ── Reading the configuration ────────────────────────────────────────


def test_no_configuration_means_no_packs(settings):
    settings.BFG_EXTENSION_PLAN_PACKS = None

    assert packs.all_packs() == []
    assert packs.get_pack("boutique") is None
    assert packs.pack_for_industry("fashion") is None


def test_a_pack_reports_the_fields_it_was_given(deployed):
    pack = packs.get_pack("boutique")

    assert pack["name"] == "Boutique"
    assert pack["name_zh"] == "精品"
    assert pack["extensions"] == (FIRST, SECOND)


def test_a_pack_naming_an_extension_this_deployment_does_not_ship_drops_it(deployed, settings):
    settings.BFG_EXTENSION_PLAN_PACKS = {
        "boutique": {"name": "Boutique", "extensions": (FIRST, "vanished")}
    }

    assert packs.get_pack("boutique")["extensions"] == (FIRST,)


def test_an_industry_finds_its_pack_and_an_unclaimed_one_finds_nothing(deployed):
    assert packs.pack_for_industry("fashion")["key"] == "boutique"
    assert packs.pack_for_industry("nothing-claims-this") is None
    assert packs.pack_for_industry("") is None


def test_configuration_that_is_not_a_mapping_is_ignored_rather_than_raising(settings):
    settings.BFG_EXTENSION_PLAN_PACKS = ["boutique"]

    assert packs.all_packs() == []


# ── Applying ─────────────────────────────────────────────────────────


def test_applying_switches_on_what_the_workspace_does_not_have(deployed, workspace):
    applied = packs.apply_pack(workspace, "boutique")

    assert [row["outcome"] for row in applied] == [packs.OUTCOME_ACTIVATED] * 2
    assert status_of(workspace, FIRST) == WorkspaceExtension.STATUS_ACTIVE
    assert status_of(workspace, SECOND) == WorkspaceExtension.STATUS_ACTIVE


def test_what_is_already_on_is_reported_as_such_and_not_touched_again(deployed, workspace):
    packs.apply_pack(workspace, "boutique")
    before = WorkspaceExtension.all_objects.get(workspace=workspace, key=FIRST).activated_at

    applied = packs.apply_pack(workspace, "boutique")

    assert [row["outcome"] for row in applied] == [packs.OUTCOME_ALREADY_ON] * 2
    assert WorkspaceExtension.all_objects.get(workspace=workspace, key=FIRST).activated_at == before


def test_applying_never_switches_anything_off(deployed, workspace):
    WorkspaceExtension.all_objects.create(
        workspace=workspace, key="not_in_the_pack", status=WorkspaceExtension.STATUS_ACTIVE
    )

    packs.apply_pack(workspace, "boutique")

    assert status_of(workspace, "not_in_the_pack") == WorkspaceExtension.STATUS_ACTIVE


def test_one_key_being_refused_does_not_stop_the_rest(deployed, workspace, monkeypatch):
    from bfg.common.extensions import packs as packs_module

    real = packs_module.activate

    def refuse_the_first(ws, key, **kwargs):
        if key == FIRST:
            raise ExtensionError("not_entitled", "This workspace is not entitled to it.")
        return real(ws, key, **kwargs)

    monkeypatch.setattr(packs_module, "activate", refuse_the_first)

    applied = packs.apply_pack(workspace, "boutique")

    assert applied[0] == {
        "key": FIRST,
        "outcome": packs.OUTCOME_SKIPPED,
        "code": "not_entitled",
        "detail": "This workspace is not entitled to it.",
    }
    assert applied[1]["outcome"] == packs.OUTCOME_ACTIVATED
    assert status_of(workspace, SECOND) == WorkspaceExtension.STATUS_ACTIVE


def test_applying_a_pack_that_is_not_configured_is_refused(deployed, workspace):
    with pytest.raises(ExtensionError) as refused:
        packs.apply_pack(workspace, "nope")

    assert refused.value.code == "unknown_pack"


# ── The command ──────────────────────────────────────────────────────


def test_listing_with_nothing_configured_says_how_to_configure_it(settings):
    settings.BFG_EXTENSION_PLAN_PACKS = {}

    assert "BFG_EXTENSION_PLAN_PACKS" in run("list")


def test_listing_shows_each_pack_with_its_industries_and_extensions(deployed):
    output = run("list")

    assert "boutique" in output and "Boutique" in output
    assert "fashion" in output
    assert FIRST in output and SECOND in output


def test_the_command_applies_a_pack_by_workspace_slug(deployed, workspace):
    output = run("apply", "boutique", "--workspace", workspace.slug)

    assert status_of(workspace, FIRST) == WorkspaceExtension.STATUS_ACTIVE
    assert "2 switched on" in output


def test_a_dry_run_writes_nothing(deployed, workspace):
    output = run("apply", "boutique", "--workspace", str(workspace.pk), "--dry-run")

    assert status_of(workspace, FIRST) is None
    assert "Dry run" in output
    assert "2 would be switched on" in output


def test_the_command_refuses_a_workspace_and_a_pack_it_cannot_find(deployed, workspace):
    with pytest.raises(CommandError, match="nobody"):
        run("apply", "boutique", "--workspace", "nobody")
    with pytest.raises(CommandError, match="nope"):
        run("apply", "nope", "--workspace", workspace.slug)


# ── The setup wizard ─────────────────────────────────────────────────


def test_the_wizard_applies_the_pack_for_the_industry_it_is_given(deployed, workspace):
    from bfg.common.onboarding.service import OnboardingService

    result = OnboardingService(workspace=workspace).apply(country="NZ", industry="fashion")

    assert status_of(workspace, FIRST) == WorkspaceExtension.STATUS_ACTIVE
    assert any(
        change["kind"] == "extension" and change["key"] == FIRST for change in result["changes"]
    )


def test_the_wizard_applies_nothing_for_an_industry_no_pack_claims(deployed, workspace):
    from bfg.common.onboarding.service import OnboardingService

    OnboardingService(workspace=workspace).apply(country="NZ", industry="b2b_wholesale")

    assert status_of(workspace, FIRST) is None


def test_a_pack_that_cannot_be_applied_does_not_fail_the_template(deployed, workspace, monkeypatch):
    from bfg.common.extensions import packs as packs_module
    from bfg.common.onboarding.service import OnboardingService

    def explode(*args, **kwargs):
        raise RuntimeError("the deployment's entitlement backend is down")

    monkeypatch.setattr(packs_module, "apply_pack", explode)

    result = OnboardingService(workspace=workspace).apply(country="NZ", industry="fashion")

    # The shop still got its currency, tax and pages.
    assert result["changes"]
    assert not any(change["kind"] == "extension" for change in result["changes"])


# ── Obtaining what the workspace has not got ─────────────────────────


def test_nothing_is_obtained_unless_the_deployment_says_how(deployed, workspace, monkeypatch):
    from bfg.common.extensions import packs as packs_module

    def refuse(ws, key, **kwargs):
        raise ExtensionError("not_entitled", "Not entitled.")

    monkeypatch.setattr(packs_module, "activate", refuse)

    applied = packs.apply_pack(workspace, "boutique")

    assert [row["outcome"] for row in applied] == [packs.OUTCOME_SKIPPED] * 2


def test_a_key_obtained_on_the_second_ask_counts_as_switched_on(
    deployed, workspace, settings, monkeypatch
):
    from bfg.common.extensions import packs as packs_module

    obtained = set()
    real = packs_module.activate

    def refuse_until_obtained(ws, key, **kwargs):
        if key not in obtained:
            raise ExtensionError("not_entitled", "Not entitled.")
        return real(ws, key, **kwargs)

    monkeypatch.setattr(packs_module, "activate", refuse_until_obtained)
    monkeypatch.setattr(
        packs_module, "import_string", lambda path: lambda ws, manifest: bool(obtained.add(manifest.key)) or True
    )
    settings.BFG_EXTENSION_PACK_OBTAIN = "deployment.obtain"

    applied = packs.apply_pack(workspace, "boutique")

    assert [row["outcome"] for row in applied] == [packs.OUTCOME_ACTIVATED] * 2
    assert status_of(workspace, FIRST) == WorkspaceExtension.STATUS_ACTIVE


def test_a_deployment_that_says_no_leaves_the_key_skipped(deployed, workspace, settings, monkeypatch):
    from bfg.common.extensions import packs as packs_module

    def refuse(ws, key, **kwargs):
        raise ExtensionError("not_entitled", "Not entitled.")

    monkeypatch.setattr(packs_module, "activate", refuse)
    monkeypatch.setattr(packs_module, "import_string", lambda path: lambda ws, manifest: False)
    settings.BFG_EXTENSION_PACK_OBTAIN = "deployment.obtain"

    applied = packs.apply_pack(workspace, "boutique")

    assert all(row["outcome"] == packs.OUTCOME_SKIPPED for row in applied)
    assert all(row["code"] == "not_entitled" for row in applied)


def test_an_obtain_hook_that_raises_skips_the_key_rather_than_the_pack(
    deployed, workspace, settings, monkeypatch
):
    from bfg.common.extensions import packs as packs_module

    real = packs_module.activate

    def refuse_the_first(ws, key, **kwargs):
        if key == FIRST:
            raise ExtensionError("not_entitled", "Not entitled.")
        return real(ws, key, **kwargs)

    def explode(ws, manifest):
        raise RuntimeError("the billing backend is down")

    monkeypatch.setattr(packs_module, "activate", refuse_the_first)
    monkeypatch.setattr(packs_module, "import_string", lambda path: explode)
    settings.BFG_EXTENSION_PACK_OBTAIN = "deployment.obtain"

    applied = packs.apply_pack(workspace, "boutique")

    assert applied[0]["outcome"] == packs.OUTCOME_SKIPPED
    assert applied[1]["outcome"] == packs.OUTCOME_ACTIVATED


def test_a_key_the_activation_refuses_for_another_reason_is_not_offered_to_the_hook(
    deployed, workspace, settings, monkeypatch
):
    from bfg.common.extensions import packs as packs_module

    asked = []

    def refuse(ws, key, **kwargs):
        raise ExtensionError("prerequisite_failed", "A setting is missing.")

    monkeypatch.setattr(packs_module, "activate", refuse)
    monkeypatch.setattr(packs_module, "import_string", lambda path: lambda ws, manifest: asked.append(manifest.key))
    settings.BFG_EXTENSION_PACK_OBTAIN = "deployment.obtain"

    packs.apply_pack(workspace, "boutique")

    assert asked == []


# ── Packs written as a file ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def forget_the_file():
    """The file is read once; every test here writes a different one."""
    packs._from_file.cache_clear()
    yield
    packs._from_file.cache_clear()


def test_packs_can_be_read_from_a_json_file(deployed, settings, tmp_path):
    settings.BFG_EXTENSION_PLAN_PACKS = None
    written = tmp_path / "packs.json"
    written.write_text(
        '{"boutique": {"name": "From a file", "industries": ["fashion"], '
        f'"extensions": ["{FIRST}"]}}}}',
        encoding="utf-8",
    )
    settings.BFG_EXTENSION_PLAN_PACKS_FILE = str(written)

    pack = packs.get_pack("boutique")

    assert pack["name"] == "From a file"
    assert pack["extensions"] == (FIRST,)


def test_the_setting_wins_over_the_file(deployed, settings, tmp_path):
    written = tmp_path / "packs.json"
    written.write_text('{"other": {"name": "From a file"}}', encoding="utf-8")
    settings.BFG_EXTENSION_PLAN_PACKS_FILE = str(written)

    assert packs.get_pack("boutique") is not None
    assert packs.get_pack("other") is None


def test_a_file_that_cannot_be_read_leaves_the_deployment_with_no_packs(settings, tmp_path):
    settings.BFG_EXTENSION_PLAN_PACKS = None
    settings.BFG_EXTENSION_PLAN_PACKS_FILE = str(tmp_path / "nothing-here.json")

    assert packs.all_packs() == []


def test_a_file_that_is_not_json_leaves_the_deployment_with_no_packs(settings, tmp_path):
    settings.BFG_EXTENSION_PLAN_PACKS = None
    written = tmp_path / "packs.json"
    written.write_text("not json at all", encoding="utf-8")
    settings.BFG_EXTENSION_PLAN_PACKS_FILE = str(written)

    assert packs.all_packs() == []
