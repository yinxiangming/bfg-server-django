# -*- coding: utf-8 -*-
"""
Give every workspace that has no owner one: its earliest active admin, or the
admin named for it with ``--owner``.

Ownership is an active ``PlatformMembership`` with role ``owner`` (see
``bfg.platform.services.ownership``). ``WorkspaceService.create_workspace``
writes one for its ``owner_user``, but workspaces created before it did, or by a
path that only adds ``StaffMember`` rows, have admins and no owner.

For each such workspace the active ``admin`` staff member added first becomes
the owner. Workspaces with no active admin are listed and left as they are.
Workspaces that already have an owner are not touched, so a second ``--apply``
writes nothing.

The first admin is not necessarily the person who should own a workspace: when
an operator set a workspace up for someone else, the operator's account is its
first admin. Read the preview, and for each workspace that should go to another
of its admins, name that admin with ``--owner WORKSPACE=USER``. WORKSPACE is a
workspace id or slug; USER is a user id, username or email address. Repeat the
option for more workspaces; the ones not named keep the default.

Every ``--owner`` is checked before anything is written, in the preview too. The
command writes nothing and stops with an error listing the bad values when one
is not ``WORKSPACE=USER``, names a workspace or user that does not exist or that
matches more than one, names a workspace already named, or names a user who is
not an active admin of that workspace. A named workspace that already has an
owner keeps it and is reported: this command fills in missing owners, it does
not transfer ownership.

Usage:

    # preview: lists the owner each workspace would get, writes nothing
    python manage.py backfill_workspace_owners

    # write them
    python manage.py backfill_workspace_owners --apply

    # the same, except that workspace "acme" goes to the admin with this email
    python manage.py backfill_workspace_owners --owner acme=jane@example.com
    python manage.py backfill_workspace_owners --owner acme=jane@example.com --apply
"""
from collections import Counter, defaultdict

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from bfg.platform.services.ownership import OWNER_ROLE, assign_workspace_owner


class Command(BaseCommand):
    help = (
        "Make the earliest active admin, or the admin named with --owner, the owner of every "
        "workspace that has none (preview unless --apply)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the owners; without it the command only reports what it would do",
        )
        parser.add_argument(
            "--owner", action="append", default=[], metavar="WORKSPACE=USER",
            help=(
                "Make USER the owner of WORKSPACE instead of its earliest active admin. Use it when the "
                "preview picks the wrong admin, as it does for a workspace an operator set up for someone "
                "else. WORKSPACE is a workspace id or slug; USER is a user id, username or email and must "
                "be an active admin of WORKSPACE. Repeat for more workspaces. A workspace that already has "
                "an owner keeps it."
            ),
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        Workspace = apps.get_model("common", "Workspace")
        StaffMember = apps.get_model("common", "StaffMember")
        PlatformMembership = apps.get_model("platform", "PlatformMembership")

        # No workspace is bound to a command's thread, so the tenant-scoped
        # StaffMember.objects would find no one.
        active_admins = StaffMember.all_objects.filter(is_active=True, role__code="admin")
        # First of all, so that a bad value stops the preview as well as --apply.
        named = self.named_owners(options["owner"], active_admins)

        owner_memberships = PlatformMembership.objects.filter(
            role=OWNER_ROLE,
            is_active=True,
            # Standalone profiles may have no local workspace, and a single NULL in
            # the NOT IN below would exclude every workspace.
            profile__workspace__isnull=False,
        )
        unowned = list(
            Workspace.objects.exclude(id__in=owner_memberships.values("profile__workspace_id")).order_by("id")
        )
        already_owned = Workspace.objects.count() - len(unowned)

        admins = (
            active_admins
            .filter(workspace__in=unowned)
            .select_related("user")
            .order_by("workspace_id", "created_at", "id")
        )
        earliest = {}
        admin_counts = Counter()
        for member in admins:
            earliest.setdefault(member.workspace_id, member)
            admin_counts[member.workspace_id] += 1

        assignments = []
        skipped = []
        for workspace in unowned:
            if workspace.id in named:
                _, member = named[workspace.id]
                assignments.append((workspace, member, "named with --owner"))
            elif workspace.id in earliest:
                count = admin_counts[workspace.id]
                note = f"earliest of {count} active admins" if count > 1 else ""
                assignments.append((workspace, earliest[workspace.id], note))
            else:
                skipped.append(workspace)

        # A named workspace that already has an owner keeps it, as every owned
        # workspace does. That needs saying only when the owner is someone else.
        owners = defaultdict(list)
        for membership in (
            owner_memberships
            .filter(profile__workspace_id__in=list(named))
            .select_related("profile", "user")
            .order_by("profile__workspace_id", "id")
        ):
            owners[membership.profile.workspace_id].append(membership.user)
        not_transferred = []
        for workspace_id, users in owners.items():
            value, member = named[workspace_id]
            if member.user not in users:
                not_transferred.append((value, member, users))

        if apply:
            with transaction.atomic():
                for workspace, member, _ in assignments:
                    assign_workspace_owner(workspace, member.user)

        prefix = "  +" if apply else "  ~"
        for workspace, member, note in assignments:
            self.stdout.write(self.style.SUCCESS(
                f"{prefix} {self.label(workspace)} → {self.describe(member, note)}"
            ))
        for value, member, users in not_transferred:
            self.stdout.write(self.style.WARNING(
                f"  ! {self.label(member.workspace)} is already owned by {', '.join(map(self.person, users))}"
                f" — skipped --owner {value!r}; ownership is not transferred"
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

    def named_owners(self, values, active_admins):
        """Resolve each ``--owner WORKSPACE=USER`` value to the admin it names.

        Returns ``{workspace id: (value, staff member)}``. Every value is checked;
        if any fails, raises CommandError giving each failing value and its reason.
        """
        named, seen, errors = {}, {}, []
        for value in values:
            try:
                # Split at the first "=": a slug cannot contain one, an email address can.
                workspace_ref, equals, user_ref = (part.strip() for part in value.partition("="))
                if not (equals and workspace_ref and user_ref):
                    raise CommandError("expected WORKSPACE=USER")
                workspace = self.find_workspace(workspace_ref)
                if workspace.id in seen:
                    raise CommandError(f"{self.label(workspace)} is already named by --owner {seen[workspace.id]!r}")
                seen[workspace.id] = value
                user = self.find_user(user_ref)
                member = (
                    active_admins.filter(workspace=workspace, user=user)
                    .select_related("workspace", "user")
                    .first()
                )
                if member is None:
                    raise CommandError(f"{self.person(user)} is not an active admin of {self.label(workspace)}")
            except CommandError as problem:
                errors.append(f"  --owner {value!r}: {problem}")
            else:
                named[workspace.id] = (value, member)
        if errors:
            raise CommandError("Nothing was written. Fix these --owner values:\n" + "\n".join(errors))
        return named

    @classmethod
    def find_workspace(cls, ref):
        """The one workspace whose id or slug is *ref*."""
        Workspace = apps.get_model("common", "Workspace")
        lookup = Q(slug=ref)
        if ref.isascii() and ref.isdigit():
            lookup |= Q(pk=int(ref))
        matches = list(Workspace.objects.filter(lookup).order_by("id"))
        if not matches:
            raise CommandError(f"no workspace with id or slug {ref!r}")
        if len(matches) > 1:
            # A slug can be all digits, and then be another workspace's id.
            raise CommandError(f"{ref!r} matches more than one workspace: {', '.join(map(cls.label, matches))}")
        return matches[0]

    @classmethod
    def find_user(cls, ref):
        """The one user whose id, username or email is *ref*."""
        User = get_user_model()
        lookup = Q(**{User.USERNAME_FIELD: ref}) | Q(**{f"{User.get_email_field_name()}__iexact": ref})
        if ref.isascii() and ref.isdigit():
            lookup |= Q(pk=int(ref))
        matches = list(User.objects.filter(lookup).order_by("pk"))
        if not matches:
            raise CommandError(f"no user with id, username or email {ref!r}")
        if len(matches) > 1:
            # Emails are not unique, and a username can be another user's email or id.
            raise CommandError(f"{ref!r} matches more than one user: {', '.join(map(cls.person, matches))}")
        return matches[0]

    @staticmethod
    def label(workspace):
        return f"{workspace.slug} (id={workspace.id})"

    @staticmethod
    def person(user):
        who = user.get_username()
        if user.email and user.email != who:
            who = f"{who} <{user.email}>"
        return f"{who} (user id={user.pk})"

    @classmethod
    def describe(cls, member, note=""):
        text = f"{cls.person(member.user)}, added {member.created_at:%Y-%m-%d}"
        return f"{text}, {note}" if note else text
