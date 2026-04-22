# -*- coding: utf-8 -*-
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from bfg.common.models import StaffMember, StaffRole, Workspace

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Create or update a user and grant workspace admin (StaffMember with admin role). "
        "Prefer --password-env over --password on shared hosts (avoids argv in process listings)."
    )

    def add_arguments(self, parser):
        parser.add_argument("workspace_slug", type=str, help="Workspace slug (e.g. geeker)")
        parser.add_argument("--username", type=str, required=True)
        parser.add_argument(
            "--password",
            type=str,
            default=None,
            help="Plain password (discouraged on production; use --password-env)",
        )
        parser.add_argument(
            "--password-env",
            type=str,
            default=None,
            metavar="VAR",
            help="Read password from this environment variable",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="",
            help="Email when creating the user (default: {username}@workspace.invalid)",
        )

    def handle(self, *args, **options):
        slug = options["workspace_slug"].strip()
        username = options["username"].strip()
        if not username:
            raise CommandError("--username is required")

        pwd = options.get("password")
        pwd_env = (options.get("password_env") or "").strip()
        if pwd_env:
            pwd = os.environ.get(pwd_env)
            if pwd is None or pwd == "":
                raise CommandError(f"Environment variable {pwd_env!r} is missing or empty")
        elif not pwd:
            raise CommandError("Provide --password or --password-env")

        try:
            workspace = Workspace.objects.get(slug=slug)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Workspace not found: slug={slug!r}") from e

        try:
            admin_role = StaffRole.objects.get(workspace=workspace, code="admin")
        except StaffRole.DoesNotExist as e:
            raise CommandError(
                f"No admin StaffRole for workspace {slug!r}; workspace roles may be uninitialized."
            ) from e

        email = (options.get("email") or "").strip() or f"{username}@workspace.invalid"

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "first_name": "",
                "last_name": "",
                "is_active": True,
                "is_staff": False,
                "is_superuser": False,
                "default_workspace": workspace,
            },
        )
        user.set_password(pwd)
        user.is_active = True
        if not user.email:
            user.email = email
        user.default_workspace = workspace
        user.save()

        member, m_created = StaffMember.all_objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": admin_role, "is_active": True},
        )
        if not m_created:
            member.role = admin_role
            member.is_active = True
            member.save()

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} user {username!r} with workspace admin on {slug!r} "
                f"(user id={user.id}, staff_member id={member.id})."
            )
        )
