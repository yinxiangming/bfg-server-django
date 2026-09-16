# -*- coding: utf-8 -*-
"""
Read the deployment's plan packs, and apply one to a workspace.

A pack is the set of extensions a kind of shop starts with, configured with
``BFG_EXTENSION_PLAN_PACKS`` — see ``bfg.common.extensions.packs``. The setup
wizard applies the pack matching the industry a new shop picks; this is how an
operator applies one to a workspace that already exists.

Applying a pack only ever switches things on. It never deactivates anything, and
it never grants an entitlement: a key the workspace may not have is reported and
skipped, so a pack can be applied to a shop that has not bought everything in it.

Usage:

    python manage.py plan_packs list
    python manage.py plan_packs apply boutique --workspace 7
    python manage.py plan_packs apply boutique --workspace a-slug --dry-run
"""
from django.core.management.base import BaseCommand, CommandError

from bfg.common.extensions import packs
from bfg.common.models import Workspace, WorkspaceExtension


class Command(BaseCommand):
    help = "List the deployment's plan packs, or apply one to a workspace"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        sub.add_parser("list", help="Show every configured pack and what it switches on")

        apply_parser = sub.add_parser("apply", help="Apply a pack to one workspace")
        apply_parser.add_argument("pack", help="The pack's key, as configured")
        apply_parser.add_argument(
            "--workspace", required=True, metavar="ID_OR_SLUG", help="The workspace to apply it to"
        )
        apply_parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report what the pack would switch on and write nothing. It asks no "
                "extension whether it would accept, so a key shown as one to switch "
                "on can still be refused by the real run."
            ),
        )

    def handle(self, *args, **options):
        if options["action"] == "list":
            return self._list()
        return self._apply(options)

    # ── list ─────────────────────────────────────────────────────────

    def _list(self):
        configured = packs.all_packs()
        if not configured:
            self.stdout.write(
                "No plan packs are configured. Set BFG_EXTENSION_PLAN_PACKS to offer some."
            )
            return

        for pack in configured:
            name = f"{pack['name']} ({pack['name_zh']})" if pack["name_zh"] else pack["name"]
            self.stdout.write(f"{pack['key']}  {name}")
            if pack["industries"]:
                self.stdout.write(f"    industries: {', '.join(pack['industries'])}")
            self.stdout.write(f"    extensions: {', '.join(pack['extensions']) or '(none)'}")

    # ── apply ────────────────────────────────────────────────────────

    def _apply(self, options):
        workspace = self._workspace(options["workspace"])
        pack = packs.get_pack(options["pack"])
        if pack is None:
            raise CommandError(
                f"No plan pack named {options['pack']!r} is configured. "
                f"`plan_packs list` shows the ones that are."
            )

        if options["dry_run"]:
            return self._describe(workspace, pack)

        applied = packs.apply_pack(workspace, pack["key"])
        for row in applied:
            if row["outcome"] == packs.OUTCOME_SKIPPED:
                self.stdout.write(f"  skipped  {row['key']}: {row['detail']}")
            else:
                self.stdout.write(f"  {row['outcome']:<9}{row['key']}")
        switched_on = sum(1 for row in applied if row["outcome"] == packs.OUTCOME_ACTIVATED)
        self.stdout.write(
            self.style.SUCCESS(f"{switched_on} switched on for {workspace.slug}.")
        )

    def _describe(self, workspace, pack):
        """What the pack would do, without asking any extension to accept it."""
        on_already = set(
            WorkspaceExtension.all_objects.filter(
                workspace=workspace,
                key__in=pack["extensions"],
                status=WorkspaceExtension.STATUS_ACTIVE,
            ).values_list("key", flat=True)
        )
        would_switch_on = [key for key in pack["extensions"] if key not in on_already]

        for key in pack["extensions"]:
            state = "already on" if key in on_already else "would switch on"
            self.stdout.write(f"  {state:<16}{key}")
        self.stdout.write(
            self.style.WARNING(
                f"Dry run: nothing was written. {len(would_switch_on)} would be switched on "
                f"for {workspace.slug}, if every one of them accepts."
            )
        )

    @staticmethod
    def _workspace(reference):
        lookup = {"pk": reference} if reference.isdigit() else {"slug": reference}
        workspace = Workspace.objects.filter(**lookup).first()
        if workspace is None:
            raise CommandError(f"No workspace {reference!r}.")
        return workspace
