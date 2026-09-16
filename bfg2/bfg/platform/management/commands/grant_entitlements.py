# -*- coding: utf-8 -*-
"""
Give workspaces an entitlement they have not bought.

This exists for the day a deployment that has been running without billing turns
it on. Once ``BFG_EXTENSION_ENTITLEMENT_CHECK`` is wired up, an add-on a workspace
has been using for a year stops being available the moment nothing entitles the
workspace to it. Granting the base plan, and whatever each workspace already has
switched on, for a few months turns billing on without taking anything away on
the day it starts.

Running it twice is safe: a workspace that already holds a live entitlement for a
key is left alone rather than given a second one.

Usage:

    python manage.py grant_entitlements --all-workspaces --switched-on --months 3
    python manage.py grant_entitlements --workspace 7 --key some-key --months 12
    python manage.py grant_entitlements --all-workspaces --never-expires
    python manage.py grant_entitlements --all-workspaces --months 3 --dry-run
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bfg.common.extensions import registry
from bfg.common.extensions.manifest import PRICING_ADDON
from bfg.common.models import Workspace, WorkspaceExtension
from bfg.platform.models import WorkspaceEntitlement
from bfg.platform.services import entitlements

# How the base plan reads in the output. Its key is the empty string, which would
# otherwise print as nothing at all.
BASE_PLAN_LABEL = "the base plan"


def _label(key):
    return BASE_PLAN_LABEL if key == WorkspaceEntitlement.KEY_BASE_PLAN else key


class Command(BaseCommand):
    help = "Grant workspaces an entitlement to the base plan, or to add-ons, without a sale"

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            action="append",
            default=[],
            metavar="ID_OR_SLUG",
            help="A workspace to grant to. Repeatable. Either this or --all-workspaces.",
        )
        parser.add_argument(
            "--all-workspaces",
            action="store_true",
            help="Grant to every active workspace.",
        )
        parser.add_argument(
            "--key",
            action="append",
            default=[],
            metavar="KEY",
            help=(
                "An add-on's extension key to grant. Repeatable. The base plan is "
                "granted as well unless --no-base-plan is given."
            ),
        )
        parser.add_argument(
            "--no-base-plan",
            action="store_true",
            help="Grant only the keys named, not the base plan.",
        )
        parser.add_argument(
            "--switched-on",
            action="store_true",
            help=(
                "Also grant each workspace every add-on it currently has switched "
                "on, which is what keeps a rollout from taking anything away."
            ),
        )
        period = parser.add_mutually_exclusive_group(required=True)
        period.add_argument(
            "--months",
            type=int,
            metavar="N",
            help="How many months each entitlement runs for.",
        )
        period.add_argument(
            "--never-expires",
            action="store_true",
            help="Grant an entitlement with no end, for something permanently included.",
        )
        parser.add_argument(
            "--reason",
            default="",
            help="Recorded on each row: why it was given.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be granted and write nothing.",
        )

    def handle(self, *args, **options):
        months = options["months"]
        if months is not None and months < 1:
            raise CommandError("--months has to be at least 1.")

        workspaces = self._workspaces(options)
        keys_by_workspace = {
            workspace: self._keys_for(workspace, options) for workspace in workspaces
        }
        if not any(keys_by_workspace.values()):
            self.stdout.write("Nothing to grant.")
            return

        granted, skipped = self._grant(keys_by_workspace, months, options)
        self._report(granted, skipped, months, options)

    # ── What to grant, and to whom ───────────────────────────────────

    def _workspaces(self, options):
        named, everything = options["workspace"], options["all_workspaces"]
        if named and everything:
            raise CommandError("Give either --workspace or --all-workspaces, not both.")
        if everything:
            return list(Workspace.objects.filter(is_active=True).order_by("id"))
        if not named:
            raise CommandError("Name the workspaces with --workspace, or use --all-workspaces.")

        workspaces = []
        for reference in named:
            workspaces.append(self._workspace(reference))
        return workspaces

    def _workspace(self, reference):
        lookup = {"pk": reference} if reference.isdigit() else {"slug": reference}
        workspace = Workspace.objects.filter(**lookup).first()
        if workspace is None:
            raise CommandError(f"No workspace {reference!r}.")
        return workspace

    def _keys_for(self, workspace, options):
        """The keys to grant ``workspace``, in the order they should be reported."""
        keys = [] if options["no_base_plan"] else [WorkspaceEntitlement.KEY_BASE_PLAN]
        keys += [key for key in options["key"] if key not in keys]
        if options["switched_on"]:
            keys += [key for key in self._switched_on_add_ons(workspace) if key not in keys]
        return keys

    def _switched_on_add_ons(self, workspace):
        """The add-on keys ``workspace`` has switched on right now.

        An extension the deployment no longer ships has nothing to price and
        nothing to check, so a record left behind by one is skipped rather than
        turned into an entitlement to something that does not exist.
        """
        switched_on = (
            WorkspaceExtension.all_objects.filter(
                workspace=workspace, status=WorkspaceExtension.STATUS_ACTIVE
            )
            .order_by("key")
            .values_list("key", flat=True)
        )
        add_ons = []
        for key in switched_on:
            manifest = registry.get_manifest(key)
            if manifest is not None and manifest.pricing == PRICING_ADDON:
                add_ons.append(key)
        return add_ons

    # ── Granting ─────────────────────────────────────────────────────

    def _grant(self, keys_by_workspace, months, options):
        granted, skipped = [], []
        # One transaction so a dry run can roll the whole thing back, and so a
        # failure halfway through leaves no half-entitled deployment behind.
        with transaction.atomic():
            for workspace, keys in keys_by_workspace.items():
                for key in keys:
                    if entitlements.is_entitled(workspace, key):
                        skipped.append((workspace, key))
                        continue
                    entitlements.grant(
                        workspace,
                        key,
                        months=months,
                        reason=options["reason"],
                    )
                    granted.append((workspace, key))
            if options["dry_run"]:
                transaction.set_rollback(True)
        return granted, skipped

    # ── Saying what happened ─────────────────────────────────────────

    def _report(self, granted, skipped, months, options):
        for workspace, key in granted:
            self.stdout.write(f"  granted  {workspace.slug}: {_label(key)}")
        for workspace, key in skipped:
            self.stdout.write(f"  already  {workspace.slug}: {_label(key)}")

        runs_for = f"{months} month(s)" if months else "as long as the deployment lasts"
        summary = f"{len(granted)} granted, running for {runs_for}; {len(skipped)} already entitled."
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Dry run: nothing was written. {summary}"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
