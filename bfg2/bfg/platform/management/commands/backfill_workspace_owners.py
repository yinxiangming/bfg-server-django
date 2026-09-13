# -*- coding: utf-8 -*-
"""
Give every workspace that has no owner one: its earliest active admin.

Ownership is an active ``PlatformMembership`` with role ``owner`` (see
``bfg.platform.services.ownership``). ``WorkspaceService.create_workspace``
writes one for its ``owner_user``, but workspaces created before it did, or by a
path that only adds ``StaffMember`` rows, have admins and no owner.

For each such workspace the active ``admin`` staff member added first becomes
the owner. Workspaces with no active admin are listed and left as they are.
Workspaces that already have an owner are not touched, so a second ``--apply``
writes nothing.

Usage:

    # preview: lists the owner each workspace would get, writes nothing
    python manage.py backfill_workspace_owners

    # write them
    python manage.py backfill_workspace_owners --apply

The first admin is not necessarily the person who should own a workspace (an
operator may have set it up for them), which is why the preview comes first.
"""
from collections import Counter

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from bfg.platform.services.ownership import OWNER_ROLE, assign_workspace_owner


class Command(BaseCommand):
    help = "Make the earliest active admin the owner of every workspace that has none (preview unless --apply)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the owners; without it the command only reports what it would do",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        Workspace = apps.get_model("common", "Workspace")
        StaffMember = apps.get_model("common", "StaffMember")
        PlatformMembership = apps.get_model("platform", "PlatformMembership")

        owned = PlatformMembership.objects.filter(
            role=OWNER_ROLE,
            is_active=True,
            # Standalone profiles may have no local workspace, and a single NULL in
            # the NOT IN below would exclude every workspace.
            profile__workspace__isnull=False,
        ).values("profile__workspace_id")
        unowned = list(Workspace.objects.exclude(id__in=owned).order_by("id"))
        already_owned = Workspace.objects.count() - len(unowned)

        # No workspace is bound to a command's thread, so the tenant-scoped
        # StaffMember.objects would find no one.
        admins = (
            StaffMember.all_objects
            .filter(workspace__in=unowned, is_active=True, role__code="admin")
            .select_related("user")
            .order_by("workspace_id", "created_at", "id")
        )
        earliest = {}
        admin_counts = Counter()
        for member in admins:
            earliest.setdefault(member.workspace_id, member)
            admin_counts[member.workspace_id] += 1

        assignments = [(workspace, earliest[workspace.id]) for workspace in unowned if workspace.id in earliest]
        skipped = [workspace for workspace in unowned if workspace.id not in earliest]

        if apply:
            with transaction.atomic():
                for workspace, member in assignments:
                    assign_workspace_owner(workspace, member.user)

        prefix = "  +" if apply else "  ~"
        for workspace, member in assignments:
            self.stdout.write(self.style.SUCCESS(
                f"{prefix} {self.label(workspace)} → {self.describe(member, admin_counts[workspace.id])}"
            ))
        for workspace in skipped:
            self.stdout.write(self.style.WARNING(f"  ! {self.label(workspace)} has no active admin — skipped"))

        self.stdout.write("")
        verb = "Assigned" if apply else "Would assign"
        self.stdout.write(
            f"{verb} {len(assignments)} owner(s); skipped {len(skipped)} workspace(s) with no active admin; "
            f"{already_owned} already have an owner."
        )
        if not apply:
            self.stdout.write("Preview only — nothing was written. Run again with --apply to write these owners.")

    @staticmethod
    def label(workspace):
        return f"{workspace.slug} (id={workspace.id})"

    @staticmethod
    def describe(member, admin_count):
        user = member.user
        who = user.get_username()
        if user.email and user.email != who:
            who = f"{who} <{user.email}>"
        text = f"{who} (user id={user.pk}), added {member.created_at:%Y-%m-%d}"
        if admin_count > 1:
            text += f", earliest of {admin_count} active admins"
        return text
