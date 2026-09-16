"""Reading the day's reference rates in, and converting with what was stored.

Nothing here reaches the network: ``requests.get`` is replaced, so a run offline
and a run in CI behave the same as a run with the service down.
"""

from datetime import date
from decimal import Decimal

import pytest

from bfg.finance.models import Currency, ExchangeRate
from bfg.platform.services import exchange_rates


class FakeResponse:
    """What ``requests.get`` returns, as much of it as this service touches."""

    def __init__(self, payload, *, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture
def currencies(db):
    for code, name, symbol in (
        ("USD", "US Dollar", "US$"),
        ("NZD", "New Zealand Dollar", "NZ$"),
        ("CNY", "Chinese Yuan", "¥"),
    ):
        Currency.objects.update_or_create(
            code=code,
            defaults={"name": name, "symbol": symbol, "decimal_places": 2, "is_active": True},
        )


@pytest.fixture
def served(monkeypatch):
    """Serve one payload, and record what was asked for."""
    calls = []

    def serve(payload, *, status=200):
        def fake_get(url, params=None, timeout=None):
            calls.append({"url": url, "params": params or {}, "timeout": timeout})
            return FakeResponse(payload, status=status)

        monkeypatch.setattr(exchange_rates.requests, "get", fake_get)
        return calls

    return serve


def _rate(from_code, to_code, day, value):
    return ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code=from_code),
        to_currency=Currency.objects.get(code=to_code),
        effective_date=day,
        rate=Decimal(value),
    )


# ── Reading rates in ─────────────────────────────────────────────────


def test_a_refresh_stores_a_row_per_rate_under_the_day_the_bank_published_it(currencies, served):
    served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.6789, "CNY": 7.1234}})

    written = exchange_rates.refresh_rates()

    assert written == 2
    stored = ExchangeRate.objects.get(
        from_currency__code="USD", to_currency__code="NZD", effective_date=date(2026, 9, 15)
    )
    assert stored.rate == Decimal("1.678900")


def test_the_currencies_kept_are_the_ones_the_deployment_has(currencies, served):
    calls = served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.6, "SEK": 9.4}})

    assert exchange_rates.refresh_rates() == 1

    assert calls[0]["params"] == {"base": "USD"}
    # Kept for a currency the deployment uses; dropped for one it does not.
    assert ExchangeRate.objects.filter(to_currency__code="NZD").exists()
    assert not Currency.objects.filter(code="SEK").exists()


def test_a_caller_can_name_the_currencies_instead(currencies, served):
    served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.7, "CNY": 7.1}})

    assert exchange_rates.refresh_rates(symbols=["nzd", "USD", " "]) == 1
    assert not ExchangeRate.objects.filter(to_currency__code="CNY").exists()


def test_a_currency_nobody_publishes_a_rate_for_does_not_cost_the_others_theirs(
    currencies, served, caplog
):
    # The service refuses a request that names a currency it does not publish, so
    # none are named and what came back is filtered here. A deployment with one
    # such currency on its books would otherwise get no rates at all, and every
    # workspace would go unbilled because of one row nobody reads.
    Currency.objects.update_or_create(
        code="XYZ",
        defaults={"name": "Nowhere", "symbol": "X", "decimal_places": 2, "is_active": True},
    )
    served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.6, "CNY": 7.1}})

    assert exchange_rates.refresh_rates() == 2
    assert "XYZ" in caplog.text


def test_a_rate_can_be_entered_by_hand_and_says_that_it_was(currencies, django_user_model):
    operator = django_user_model.objects.create_user(username="operator", email="operator@example.test")

    row = exchange_rates.set_rate("usd", "nzd", "1.6555555", on=date(2026, 9, 15), user=operator)

    assert row.source == ExchangeRate.SOURCE_MANUAL
    assert row.entered_by == operator
    # Written to the six places the column holds, as a rate from the feed is.
    assert row.rate == Decimal("1.655556")
    assert exchange_rates.convert(1, "USD", "NZD", on=date(2026, 9, 16)) == Decimal("1.655556")


@pytest.mark.parametrize("rate", ["0", "-1.5", "not a rate", "0.0000001", None])
def test_a_rate_that_is_not_a_positive_number_is_not_stored(currencies, rate):
    with pytest.raises(exchange_rates.InvalidExchangeRate):
        exchange_rates.set_rate("USD", "NZD", rate)
    assert not ExchangeRate.objects.exists()


def test_a_pair_of_the_same_currency_is_refused(currencies):
    with pytest.raises(exchange_rates.InvalidExchangeRate):
        exchange_rates.set_rate("USD", "usd", "1")


def test_the_published_rate_replaces_one_somebody_typed_for_the_same_day(currencies, served):
    exchange_rates.set_rate("USD", "NZD", "1.500000", on=date(2026, 9, 15))
    served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.6}})

    assert exchange_rates.refresh_rates(symbols=["NZD"]) == 1

    stored = ExchangeRate.objects.get(from_currency__code="USD", to_currency__code="NZD")
    assert stored.rate == Decimal("1.600000")
    # The bank's number has arrived; the stand-in no longer claims to be typed.
    assert stored.source == ExchangeRate.SOURCE_FEED
    assert stored.entered_by is None


def test_a_day_already_stored_is_updated_rather_than_repeated(currencies, served):
    served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.6}})
    exchange_rates.refresh_rates(symbols=["NZD"])
    served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.7}})

    exchange_rates.refresh_rates(symbols=["NZD"])

    rates = ExchangeRate.objects.filter(from_currency__code="USD", to_currency__code="NZD")
    assert rates.count() == 1
    assert rates.get().rate == Decimal("1.700000")


def test_a_currency_the_deployment_has_never_used_is_created_to_hang_the_rate_off(
    currencies, served
):
    served({"base": "USD", "date": "2026-09-15", "rates": {"EUR": 0.92}})

    assert exchange_rates.refresh_rates(symbols=["EUR"]) == 1
    assert Currency.objects.filter(code="EUR", is_active=True).exists()


def test_a_refresh_that_fails_says_so_in_the_log_rather_than_at_the_caller(
    currencies, served, caplog
):
    served({}, status=503)

    assert exchange_rates.refresh_rates() == 0
    assert not ExchangeRate.objects.exists()
    assert "Could not read exchange rates" in caplog.text


def test_a_body_that_is_not_an_object_is_refused(currencies, served, caplog):
    served(["not", "rates"])

    assert exchange_rates.refresh_rates() == 0
    assert not ExchangeRate.objects.exists()
    assert "not an object" in caplog.text


def test_a_rate_that_is_not_a_number_is_left_out_and_the_rest_are_kept(currencies, served, caplog):
    served({"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.6, "CNY": "n/a"}})

    assert exchange_rates.refresh_rates() == 1
    assert ExchangeRate.objects.filter(to_currency__code="NZD").exists()
    assert not ExchangeRate.objects.filter(to_currency__code="CNY").exists()


def test_a_deployment_with_nothing_but_the_base_reads_nothing(db, served):
    Currency.objects.update_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "US$", "decimal_places": 2, "is_active": True},
    )
    calls = served({"base": "USD", "date": "2026-09-15", "rates": {}})

    assert exchange_rates.refresh_rates() == 0
    assert calls == []


# ── Converting ───────────────────────────────────────────────────────


def test_a_conversion_uses_the_rate_for_the_day_asked_about(currencies):
    _rate("USD", "NZD", date(2026, 9, 1), "1.60")
    _rate("USD", "NZD", date(2026, 9, 10), "1.70")

    assert exchange_rates.convert(10, "USD", "NZD", on=date(2026, 9, 5)) == Decimal("16.00")
    assert exchange_rates.convert(10, "USD", "NZD", on=date(2026, 9, 10)) == Decimal("17.00")


def test_a_day_with_no_rate_of_its_own_falls_back_to_the_last_one_published(currencies):
    # Friday's rate is what a bill issued on the Sunday is worked out at.
    _rate("USD", "NZD", date(2026, 9, 11), "1.65")

    assert exchange_rates.convert(2, "USD", "NZD", on=date(2026, 9, 13)) == Decimal("3.30")


def test_converting_a_currency_into_itself_changes_nothing(currencies):
    assert exchange_rates.convert(Decimal("12.34"), "NZD", "nzd") == Decimal("12.34")


def test_a_pair_with_no_rate_at_all_is_refused_rather_than_guessed_at(currencies):
    with pytest.raises(exchange_rates.ExchangeRateNotFound):
        exchange_rates.convert(1, "USD", "NZD", on=date(2026, 9, 5))


def test_a_rate_published_after_the_day_asked_about_does_not_count(currencies):
    _rate("USD", "NZD", date(2026, 9, 20), "1.70")

    with pytest.raises(exchange_rates.ExchangeRateNotFound):
        exchange_rates.convert(1, "USD", "NZD", on=date(2026, 9, 5))


def test_the_rate_the_other_way_round_is_not_turned_upside_down(currencies):
    _rate("USD", "NZD", date(2026, 9, 1), "1.60")

    with pytest.raises(exchange_rates.ExchangeRateNotFound):
        exchange_rates.convert(1, "NZD", "USD", on=date(2026, 9, 5))


def test_a_conversion_is_exact_and_left_for_the_caller_to_round(currencies):
    _rate("USD", "NZD", date(2026, 9, 1), "1.678900")

    assert exchange_rates.convert(3, "USD", "NZD", on=date(2026, 9, 2)) == Decimal("5.036700")
