# -*- coding: utf-8 -*-
"""
Settle the entitlements whose period, or grace, has run out.

An entitlement that is not renewed moves from ``active`` to ``grace`` when its
period ends, and from ``grace`` to ``ended`` when the deployment's ``grace_days``
are up. Ending one pauses the extension it paid for: the workspace's data and
configuration are kept, and paying again is all it takes to get it back.

**There is no scheduler behind this.** Neither deployment runs Celery beat, so
this has to be called — by hand, by cron, or by whatever else the deployment can
offer — ideally once a day. Nothing keeps working merely because it has not run:
an entitlement stops counting when its period and grace are past whether or not
anything has swept it. What waits on this command is the extension being paused
and the status reading the way it should, not the expiry itself. It is safe to
run as often as one likes, and running it twice in a row does nothing the second
time.

Usage:

    python manage.py close_entitlement_periods
    python manage.py close_entitlement_periods --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from bfg.platform.services.entitlements import close_due_periods

# What each count in the result means, in the order worth reading it.
LINES = (
    ("moved_to_grace", "entitlements whose period ended, now in their grace period"),
    ("ended", "entitlements whose grace ran out, now ended"),
    ("extensions_paused", "extensions paused because nothing entitles the workspace to them"),
)


class Command(BaseCommand):
    help = "Move entitlements past their period into grace, and past their grace into ended"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Do the whole sweep and roll it back, reporting exactly what it would "
                "have settled. Nothing is written and no cache is dropped."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        # The sweep itself rather than a second copy of its rules: a dry run that
        # counted rows its own way could disagree with the run it is describing.
        # Rolling back also leaves the after-commit cache invalidation unfired,
        # which is what makes the dry run leave nothing at all behind.
        with transaction.atomic():
            settled = close_due_periods()
            if dry_run:
                transaction.set_rollback(True)

        if not any(settled.values()):
            self.stdout.write("Nothing had run out.")
            return

        for key, description in LINES:
            self.stdout.write(f"  {settled[key]:>6}  {description}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: nothing was written."))
        else:
            self.stdout.write(self.style.SUCCESS("Settled."))
