# -*- coding: utf-8 -*-
"""
Read the day's reference rates and store them.

Bills are worked out in points, which are US dollars, and written in the
workspace's own currency, so a rate has to be on file for the day a bill is
issued. The rates are the European Central Bank's daily reference rates.

**There is no scheduler behind this**, the same as with closing periods: neither
deployment runs Celery beat, so run it from cron once a day, and in any case
before issuing a month's bills. Rates are stored under the day the bank published
them, so running it twice in a day rewrites the same rows rather than adding any.

A refresh that fails writes nothing and leaves the rates already stored in place,
which is what conversions will then use — billing looks up the latest rate on or
before the day it wants, not the rate for exactly that day.

Usage:

    python manage.py refresh_exchange_rates
    python manage.py refresh_exchange_rates --base USD --symbols NZD,CNY
"""
from django.core.management.base import BaseCommand

from bfg.platform.services.exchange_rates import refresh_rates


class Command(BaseCommand):
    help = "Store today's reference exchange rates against a base currency"

    def add_arguments(self, parser):
        parser.add_argument(
            "--base",
            default="USD",
            help="The currency the rates are quoted against. US dollars by default, which is what a point is.",
        )
        parser.add_argument(
            "--symbols",
            default="",
            help=(
                "Comma-separated currencies to read. Left out, every currency the "
                "deployment has is read, because a rate for one it does not use is a "
                "row nothing will ever look at."
            ),
        )

    def handle(self, *args, **options):
        base = options["base"].strip().upper()
        typed = [code for code in options["symbols"].split(",") if code.strip()]
        written = refresh_rates(base=base, symbols=typed or None)

        if written:
            self.stdout.write(self.style.SUCCESS(f"Stored {written} rates against {base}."))
            return
        # Nothing written is a refusal to guess, not a crash: the reason is in the
        # log, and yesterday's rates are still what bills will be worked out at.
        self.stdout.write(
            self.style.WARNING(
                f"No rates were stored against {base}. The rates already on file still apply; "
                f"see the log for why this run read none."
            )
        )
