# -*- coding: utf-8 -*-
"""
Issue one invoice per workspace for a month of usage and renewals.

The invoice is issued by the management workspace and made out to the workspace's
owner, in the workspace's own currency, at the day's exchange rate — so run
``refresh_exchange_rates`` first, or a workspace whose currency has no rate on
file is skipped rather than billed at a made-up one.

**There is no scheduler behind this**, the same as with closing periods: neither
deployment runs Celery beat. Run it once at the start of a month, from cron or by
hand. Running it twice bills nothing twice: an invoice number is the workspace and
the period, and the second attempt is refused by the database.

Usage:

    # last month, for every workspace with something to bill
    python manage.py issue_monthly_bills

    # read the run before making it
    python manage.py issue_monthly_bills --dry-run

    # a particular month
    python manage.py issue_monthly_bills --month 2026-09
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from bfg.platform.services.billing import PlatformWorkspaceMissing, issue_monthly_bills


class Command(BaseCommand):
    help = "Issue each workspace's invoice for a month of metered usage and renewals"

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            metavar="YYYY-MM",
            help="The month to bill. Last month by default, which is what a run at the start of a month wants.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Work out every invoice and write none of them, printing what would be issued.",
        )

    def handle(self, *args, **options):
        month = self.month(options["month"])
        dry_run = options["dry_run"]

        try:
            bills = issue_monthly_bills(month, dry_run=dry_run)
        except PlatformWorkspaceMissing as missing:
            raise CommandError(
                f"{missing.message} Set PLATFORM_WORKSPACE_SLUG to the workspace that sells, "
                f"and nothing will be billed from a workspace that is only a shop."
            )

        if not bills:
            self.stdout.write("No workspace used anything or had anything to renew.")
            return

        for bill in bills:
            self.write_bill(bill, dry_run=dry_run)

        issued = [bill for bill in bills if bill["issued"]]
        skipped = [bill for bill in bills if bill["skipped"]]
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {len(bills) - len(skipped)} invoices would be issued, "
                f"{len(skipped)} workspaces skipped. Nothing was written."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"{len(issued)} invoices issued, {len(skipped)} workspaces skipped."
            ))

    def write_bill(self, bill, *, dry_run):
        heading = f"{bill['invoice_number']}  {bill['workspace_name']} ({bill['period']})"
        if bill["skipped"]:
            self.stdout.write(f"  - {heading}: {bill['skipped']}")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(heading))
        for line in bill["lines"]:
            self.stdout.write(
                f"      {line['description'][:56]:<56} "
                f"{line['quantity']:>10} × {line['unit_price']:>10} = {line['subtotal']:>12}"
            )
        self.stdout.write(
            f"      {'subtotal / tax / total':<56} "
            f"{bill['subtotal']:>12} {bill['tax']:>10} {bill['total']:>12} {bill['currency']}"
        )

    @staticmethod
    def month(value):
        """``YYYY-MM`` as a date inside that month, or None for last month."""
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m").date()
        except ValueError:
            raise CommandError(f"--month is a year and a month, not {value!r} (2026-09).")
