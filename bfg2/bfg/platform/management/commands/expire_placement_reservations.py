# -*- coding: utf-8 -*-
"""Preview or release expired Platform placement-capacity reservations."""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from bfg.platform.services.placement_queue import expire_due_reservations


class Command(BaseCommand):
    help = "Preview expired placement reservations; add --apply to release their capacity"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Release the due reservations; without this flag the command only previews them",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Process at most this many reservations (1-1000, default 100)",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("--limit must be between 1 and 1000")
        PlacementRequest = apps.get_model("platform", "WorkspacePlacementRequest")
        due = list(
            PlacementRequest.objects.filter(
                status=PlacementRequest.STATUS_RESERVED,
                reservation_expires_at__lte=timezone.now(),
            ).select_related("workspace", "target_cluster").order_by("reservation_expires_at", "id")[:limit]
        )
        if not options["apply"]:
            for request in due:
                self.stdout.write(
                    f"  ~ {request.workspace.slug} (id={request.workspace_id}) → "
                    f"{request.target_cluster_id}; expired {request.reservation_expires_at.isoformat()}"
                )
            self.stdout.write(f"Would release {len(due)} expired placement reservation(s).")
            self.stdout.write("Preview only — nothing was written. Run again with --apply to release capacity.")
            return

        expired = expire_due_reservations(limit=limit)
        for request in expired:
            self.stdout.write(self.style.SUCCESS(
                f"  + released {request.workspace_id} → {request.target_cluster_id} ({request.id})"
            ))
        self.stdout.write(f"Released {len(expired)} expired placement reservation(s).")
