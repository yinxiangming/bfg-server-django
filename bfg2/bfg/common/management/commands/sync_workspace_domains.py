# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from django.apps import apps

from bfg.common.models import (
    WorkspaceDomain,
    ensure_system_default_workspace_domain,
    normalize_hostname,
    upsert_custom_workspace_domain,
)


class Command(BaseCommand):
    help = "Ensure WorkspacePlatformProfile and WorkspaceDomain data are complete"

    def add_arguments(self, parser):
        parser.add_argument("--workspace", help="Workspace slug or numeric id")
        parser.add_argument("--apply", action="store_true", help="Persist missing data instead of dry-run output")

    def handle(self, *args, **options):
        Workspace = apps.get_model("common", "Workspace")
        WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
        WorkspaceDomain = apps.get_model("common", "WorkspaceDomain")
        Site = apps.get_model("web", "Site")

        workspace_arg = (options.get("workspace") or "").strip()
        apply = bool(options.get("apply"))

        workspaces = Workspace.objects.all().order_by("id")
        if workspace_arg:
            if workspace_arg.isdigit():
                workspaces = workspaces.filter(id=int(workspace_arg))
            else:
                workspaces = workspaces.filter(slug=workspace_arg)

        if not workspaces.exists():
            self.stdout.write(self.style.WARNING("No matching workspaces found."))
            return

        created_profiles = 0
        created_domains = 0
        updated_domains = 0
        repaired_domains = 0
        warnings = []

        for workspace in workspaces:
            profile, profile_created = WorkspacePlatformProfile.objects.get_or_create(workspace=workspace)
            if profile_created:
                created_profiles += 1
                self.stdout.write(self.style.SUCCESS(f"[profile] created for workspace={workspace.slug}"))

            system_domain = ensure_system_default_workspace_domain(workspace) if apply else None
            expected_system_hostname = None
            if getattr(profile, "cluster", None):
                expected_system_hostname = ensure_system_default_workspace_domain(workspace).hostname if apply else None
                if not apply:
                    expected = workspace.domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).first()
                    if expected:
                        expected_system_hostname = expected.hostname
                extra_system_defaults = workspace.domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).count() - (1 if expected_system_hostname else 0)
                if extra_system_defaults > 0:
                    if apply:
                        keep = workspace.domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).order_by("id").first()
                        workspace.domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).exclude(pk=keep.pk).delete()
                        repaired_domains += extra_system_defaults
                    warnings.append(f"workspace={workspace.slug}: had {extra_system_defaults} extra system_default domain(s)")
                if not expected_system_hostname:
                    warnings.append(f"workspace={workspace.slug}: cluster bound but missing system_default domain")
                elif system_domain:
                    created_domains += 1
                    self.stdout.write(self.style.SUCCESS(f"[domain] ensured system_default {system_domain.hostname} for workspace={workspace.slug}"))

            sites = Site.all_objects.filter(workspace=workspace, is_active=True)
            for site in sites:
                hostname = normalize_hostname(site.domain)
                if not hostname:
                    continue
                existing = WorkspaceDomain.objects.filter(hostname=hostname).first()
                if existing and existing.workspace_id != workspace.id:
                    warnings.append(
                        f"workspace={workspace.slug}: site domain {hostname} already belongs to workspace={existing.workspace.slug}"
                    )
                    continue
                if apply:
                    before = WorkspaceDomain.objects.filter(hostname=hostname).first()
                    domain = upsert_custom_workspace_domain(
                        workspace,
                        hostname,
                        is_primary=not workspace.domains.filter(kind=WorkspaceDomain.KIND_CUSTOM, is_primary=True).exists(),
                        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
                        ssl_status=WorkspaceDomain.SSL_NONE,
                    )
                    if before:
                        updated_domains += 1
                    elif domain:
                        created_domains += 1
                    self.stdout.write(self.style.SUCCESS(f"[domain] synced custom {hostname} for workspace={workspace.slug}"))
                else:
                    self.stdout.write(f"[dry-run] would sync custom {hostname} for workspace={workspace.slug}")

            primary_customs = list(workspace.domains.filter(
                kind=WorkspaceDomain.KIND_CUSTOM,
                verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
                is_primary=True,
            ).order_by("id"))
            if len(primary_customs) > 1:
                warnings.append(
                    f"workspace={workspace.slug}: has {len(primary_customs)} verified primary custom domains"
                )
                if apply:
                    keep = primary_customs[0]
                    workspace.domains.filter(
                        workspace=workspace,
                        kind=WorkspaceDomain.KIND_CUSTOM,
                        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
                        is_primary=True,
                    ).exclude(pk=keep.pk).update(is_primary=False)
                    repaired_domains += len(primary_customs) - 1

            has_primary_custom = workspace.domains.filter(
                kind=WorkspaceDomain.KIND_CUSTOM,
                verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
                is_primary=True,
            ).exists()
            has_system_default = workspace.domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).exists()
            if not has_primary_custom and not has_system_default:
                warnings.append(
                    f"workspace={workspace.slug}: missing both verified primary custom domain and system_default domain"
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Profiles created: {created_profiles}"))
        self.stdout.write(self.style.SUCCESS(f"Domains created: {created_domains}"))
        self.stdout.write(self.style.SUCCESS(f"Domains updated: {updated_domains}"))
        self.stdout.write(self.style.SUCCESS(f"Domains repaired: {repaired_domains}"))

        if warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Warnings:"))
            for item in warnings:
                self.stdout.write(self.style.WARNING(f"- {item}"))
