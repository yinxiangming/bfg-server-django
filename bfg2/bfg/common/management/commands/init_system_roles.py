"""
Initialize / sync system roles across all active workspaces.

Source of truth is the role registry — each BFG module declares its
own roles in ``<module>/roles.py`` and registers them at app-ready
time. This command just iterates active workspaces and applies the
registry to each.

Idempotent. Safe to re-run after deploys that add new module roles.
Customised ``permissions`` JSON on existing roles is preserved; only
metadata (``name``, ``description``, ``default_permissions``,
``owner_module``, ``is_system``) is refreshed.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync system roles to every active workspace from the role registry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            type=int,
            default=None,
            help="Only sync the workspace with this id (default: all active).",
        )

    def handle(self, *args, **options):
        from bfg.common.models import Workspace
        from bfg.common.role_registry import role_registry
        from bfg.common.services.role_provisioning import provision_system_roles

        defs = role_registry.all_roles()
        self.stdout.write(
            f"Registry has {len(defs)} role definition(s) from "
            f"{len({d.owner_module for d in defs})} module(s)."
        )

        ws_qs = Workspace.objects.filter(is_active=True)
        if options.get("workspace") is not None:
            ws_qs = ws_qs.filter(id=options["workspace"])

        total_created = total_updated = 0
        for ws in ws_qs:
            result = provision_system_roles(ws, defs)
            total_created += len(result.created)
            total_updated += len(result.updated)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [{ws.id}] {ws.name}: created={result.created} "
                    f"updated={result.updated} skipped={len(result.skipped)}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {total_created}, refreshed {total_updated}."
            )
        )
