# -*- coding: utf-8 -*-
"""
Read what each meter costs, and price one from a moment on.

A meter's price is a vendor cost over the number of calls or tokens that cost
buys, plus a margin. Prices are never edited: a new rate is a new row with a
later ``effective_from``, and whichever row was in force when a call was made is
the one it was billed at. So this command adds rows and never changes them, and
``list`` shows a meter's whole history with the row in force marked.

A row dated in the past does not reprice usage already recorded — every usage row
keeps the price it was calculated with, which is what lets an old invoice still
be explained. It does decide what usage recorded from now on for a day back then
will cost, which is how a rate the vendor applied from the first of the month is
entered after the fact.

Prices are platform data: they belong to the deployment rather than to any one
workspace, so this runs with no workspace bound, as a management command does.

Usage:

    # every meter, its whole price history, and the row in force now
    python manage.py meter_prices list

    # one meter
    python manage.py meter_prices list --meter ai.gpt-4o-mini.input

    # $0.15 per million tokens, at the deployment's own margin, from now
    python manage.py meter_prices set ai.gpt-4o-mini.input --cost 0.15 --unit-size 1000000

    # $17 per thousand calls at a 30% margin, from the first of next month
    python manage.py meter_prices set vendor.lookup --cost 17.00 --unit-size 1000 \
        --margin 0.30 --from 2026-10-01T00:00:00Z
"""
from datetime import datetime, time, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from bfg.platform.models import MeterPrice
from bfg.platform.services import pricing
from bfg.platform.services.platform_variables import get_variable

# Options that only mean something to one of the two actions. Passing one to the
# other is a mistake worth stopping for: silently ignoring --cost on a list reads
# like the price was set.
SET_ONLY = (
    ("key", "a meter as an argument"),
    ("cost", "--cost"),
    ("unit_size", "--unit-size"),
    ("margin", "--margin"),
    ("effective_from", "--from"),
)

# A column the value came from, named back as the option it was typed as, so that
# a limit the model states is reported against something the operator wrote.
OPTION_FOR_FIELD = {
    "meter": "the meter",
    "vendor_cost": "--cost",
    "unit_size": "--unit-size",
    "margin": "--margin",
    "effective_from": "--from",
}


class Command(BaseCommand):
    help = "List what each meter costs, or price one from a moment on"

    def add_arguments(self, parser):
        parser.add_argument(
            "action", choices=("list", "set"),
            help="list: show prices. set: add a new price for one meter.",
        )
        parser.add_argument(
            "key", nargs="?", metavar="KEY",
            help="The meter to price, for set (e.g. ai.gpt-4o-mini.input).",
        )
        parser.add_argument(
            "--meter", metavar="KEY",
            help="For list: show only this meter instead of every one.",
        )
        parser.add_argument(
            "--cost", metavar="USD",
            help="For set: what the vendor charges for one --unit-size of this meter, in US dollars.",
        )
        parser.add_argument(
            "--unit-size", dest="unit_size", metavar="N",
            help=(
                "For set: how many calls or tokens --cost buys. Required, and not defaulted to 1: "
                "a vendor quotes a price over a million tokens, and a price entered without this "
                "would be a million times too high."
            ),
        )
        parser.add_argument(
            "--margin", metavar="SHARE",
            help=(
                "For set: the share added on top of the vendor cost, as a fraction — 0.30 charges "
                "1.30 times cost. Left out, the deployment's usage_margin applies, and a change to "
                "it moves this price too."
            ),
        )
        parser.add_argument(
            "--from", dest="effective_from", metavar="WHEN",
            help=(
                "For set: when the price takes effect, as a date or a timestamp "
                "(2026-10-01, or 2026-10-01T00:00:00Z). A time with no zone is read in the "
                "deployment's own time zone. Now by default."
            ),
        )

    def handle(self, *args, **options):
        if options["action"] == "list":
            return self.list_prices(options)
        return self.set_price(options)

    # ── list ─────────────────────────────────────────────────────────

    def list_prices(self, options):
        for name, label in SET_ONLY:
            if options.get(name):
                raise CommandError(
                    f"meter_prices list does not take {label}. To show one meter, use "
                    f"--meter KEY; to price one, use meter_prices set KEY --cost ... --unit-size ..."
                )

        prices = MeterPrice.objects.all()
        if options["meter"]:
            prices = prices.filter(meter=options["meter"])
        # Ordered newest first within each meter, which is how a price is read:
        # what it costs now, and what it used to.
        prices = prices.order_by("meter", "-effective_from", "-id")

        grouped = {}
        for price in prices:
            grouped.setdefault(price.meter, []).append(price)

        if not grouped:
            which = f" for {options['meter']!r}" if options["meter"] else ""
            self.stdout.write(self.style.WARNING(f"No meter prices{which} yet."))
            self.stdout.write(
                "Add one with: python manage.py meter_prices set KEY --cost 0.15 --unit-size 1000000"
            )
            return

        default_margin = get_variable("usage_margin")
        for meter, rows in grouped.items():
            self.stdout.write(self.style.MIGRATE_HEADING(meter))
            in_force = self.in_force(meter)
            for price in rows:
                current = in_force is not None and price.pk == in_force.pk
                self.stdout.write(
                    ("  * " if current else "    ")
                    + self.describe(price, default_margin)
                )
            if in_force is None:
                # Every row starts later than now, which is what a price entered
                # with the wrong date looks like — and until one starts, metering
                # this meter raises rather than billing anything.
                starts = min(price.effective_from for price in rows)
                self.stdout.write(self.style.WARNING(
                    f"    ! nothing in force — the earliest price starts {self.moment(starts)}"
                ))

        self.stdout.write("")
        self.stdout.write("* the price in force now. Points are US dollars; a call is billed at the price in force when it was made.")

    # ── set ──────────────────────────────────────────────────────────

    def set_price(self, options):
        if options["meter"]:
            raise CommandError(
                "meter_prices set takes the meter as an argument, not --meter: "
                f"python manage.py meter_prices set {options['meter']} --cost 0.15 --unit-size 1000000"
            )
        meter = (options["key"] or "").strip()
        if not meter:
            raise CommandError(
                "meter_prices set needs the meter to price: "
                "python manage.py meter_prices set KEY --cost 0.15 --unit-size 1000000"
            )

        cost = self.decimal(options["cost"], "--cost", required=True)
        unit_size = self.whole(options["unit_size"], "--unit-size")
        margin = self.decimal(options["margin"], "--margin", required=False)
        effective_from = self.when(options["effective_from"])

        price = MeterPrice(
            meter=meter,
            vendor_cost=cost,
            unit_size=unit_size,
            margin=margin,
            effective_from=effective_from,
        )
        try:
            # The columns' own limits rather than a second copy of them here, so
            # that a number too big for one is refused in words instead of
            # failing, or quietly rounding, in the database.
            price.full_clean()
        except ValidationError as invalid:
            raise CommandError("Nothing was written. " + " ".join(
                f"{OPTION_FOR_FIELD.get(field, field)}: {' '.join(problems)}"
                for field, problems in invalid.message_dict.items()
            ))
        price.save()
        # Read back so that what is reported is what was stored, to the decimal
        # places the columns hold, and reads the same as it will in a listing.
        price.refresh_from_db()

        self.stdout.write(self.style.SUCCESS(
            f"  + {meter}  {self.describe(price, get_variable('usage_margin'))}"
        ))

        # What the deployment will actually bill at is worth reading back: a
        # price dated behind one that already exists changes nothing today.
        in_force = self.in_force(meter)
        if in_force is None:
            self.stdout.write(self.style.WARNING(
                f"  ! {meter} has no price in force until {self.moment(effective_from)}; "
                f"metering it before then raises rather than billing anything."
            ))
        elif in_force.pk != price.pk:
            self.stdout.write(self.style.WARNING(
                f"  ! not in force: {meter} is priced by the row from {self.moment(in_force.effective_from)} "
                f"until this one starts."
            ))

    # ── reading and writing values ───────────────────────────────────

    @staticmethod
    def in_force(meter):
        """The price ``meter`` would be billed at right now, or None.

        Asked of the pricing service rather than worked out again here, so that
        what this command marks as current is what an invoice would use.
        """
        try:
            return pricing.price_for(meter)
        except pricing.MeterNotPriced:
            return None

    @staticmethod
    def decimal(value, option, *, required):
        """``value`` as a non-negative Decimal, or None when it may be left out."""
        if value is None:
            if required:
                raise CommandError(f"meter_prices set needs {option}.")
            return None
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise CommandError(f"{option} is a number, not {value!r}.")
        if not number.is_finite():
            raise CommandError(f"{option} is a number, not {value!r}.")
        if number < 0:
            raise CommandError(f"{option} cannot be negative ({value!r}).")
        return number

    @staticmethod
    def whole(value, option):
        """``value`` as a unit size: a whole number of calls or tokens, at least one."""
        if value is None:
            raise CommandError(
                f"meter_prices set needs {option} — how many calls or tokens the cost buys "
                f"(1000000 for a price quoted per million tokens, 1 for a price per call)."
            )
        try:
            number = int(str(value).strip())
        except ValueError:
            raise CommandError(f"{option} is a whole number, not {value!r}.")
        if number < 1:
            raise CommandError(f"{option} is at least 1, not {value!r}.")
        return number

    @staticmethod
    def when(value):
        """``value`` as an aware datetime; now when it was left out.

        A date on its own is midnight on that day, and a time with no offset is
        read in the deployment's own time zone rather than guessed at as UTC.
        Whichever it was, it is printed back in UTC, which is the day usage is
        totalled by.
        """
        if value is None:
            return timezone.now()
        text = str(value).strip()
        try:
            moment = parse_datetime(text)
            if moment is None:
                day = parse_date(text)
                moment = datetime.combine(day, time.min) if day else None
        except ValueError:
            # Well formed but impossible, such as the 31st of February.
            moment = None
        if moment is None:
            raise CommandError(
                f"--from is a date or a timestamp, not {value!r} "
                f"(2026-10-01, 2026-10-01T00:00:00Z, 2026-10-01T13:30:00+13:00)."
            )
        if timezone.is_naive(moment):
            moment = timezone.make_aware(moment)
        return moment

    # ── printing ─────────────────────────────────────────────────────

    @classmethod
    def describe(cls, price, default_margin):
        """One price as a line: when it starts, what it costs, and what that comes to."""
        if price.margin is None:
            # Quantized to the column's own places, so the deployment's margin and
            # a price's own read the same way down a listing.
            share = Decimal(default_margin).quantize(Decimal("0.0001"))
            margin = f"margin {share:f} (deployment default)"
        else:
            margin = f"margin {price.margin:f}"
        cost = f"${price.vendor_cost:f} per {price.unit_size:,}"
        points = pricing.points_for(price.meter, 1, price=price)
        return (
            f"from {cls.moment(price.effective_from):<20}  {cost:<28}  "
            f"{margin:<34}  {points:f} pt per unit"
        )

    @staticmethod
    def moment(value):
        """A time as UTC, the zone usage days and invoices are counted in."""
        return value.astimezone(datetime_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
