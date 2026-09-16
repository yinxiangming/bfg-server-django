"""Platform variables: what they are worth when nobody has set them, and what a change leaves behind."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from bfg.platform.models import PlatformVariable, PlatformVariableChange
from bfg.platform.services import platform_variables as variables

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_variable_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def operator(db):
    return User.objects.create_user(username="operator", email="operator@example.test")


def test_a_variable_nobody_set_is_worth_its_default(db):
    assert variables.get_variable("usage_margin") == Decimal("0.30")
    assert variables.get_variable("yearly_discount") == Decimal("0.10")
    assert variables.get_variable("grace_days") == 14
    assert variables.get_variable("archive_after_days") == 30
    assert variables.get_variable("archive_retention_days") == 365
    assert variables.get_variable("monthly_usage_cap_points") == Decimal("20")
    assert variables.get_variable("trial_points") == Decimal("1")
    assert variables.get_variable("invoice_due_days") == 14
    assert not PlatformVariable.objects.exists()


def test_whole_number_variables_come_back_as_ints_and_rates_as_decimals(db):
    assert isinstance(variables.get_variable("grace_days"), int)
    assert isinstance(variables.get_variable("usage_margin"), Decimal)


def test_setting_a_variable_changes_what_everything_reads(db, operator):
    variables.set_variable("usage_margin", Decimal("0.45"), user=operator)

    assert variables.get_variable("usage_margin") == Decimal("0.45")
    assert PlatformVariable.objects.get(key="usage_margin").updated_by == operator


def test_every_change_records_who_made_it_and_what_it_replaced(db, operator):
    variables.set_variable("grace_days", 21, user=operator, reason="matching the competition")
    variables.set_variable("grace_days", 7, user=None, reason="too generous")

    trail = list(PlatformVariableChange.objects.order_by("id"))
    assert [(change.old_value, change.new_value) for change in trail] == [(14, 21), (21, 7)]
    assert trail[0].changed_by == operator
    assert trail[0].reason == "matching the competition"
    # The first change replaced the default, which no row had ever held.
    assert trail[1].changed_by is None


def test_all_variables_lists_every_known_one_with_overrides_applied(db, operator):
    variables.set_variable("trial_points", 5, user=operator)

    everything = variables.all_variables()

    assert set(everything) == set(variables.VARIABLES)
    assert everything["trial_points"] == Decimal("5")
    assert everything["invoice_due_days"] == 14


def test_a_variable_this_deployment_does_not_define_is_refused(db, operator):
    with pytest.raises(variables.UnknownPlatformVariable):
        variables.get_variable("usage_margn")
    with pytest.raises(variables.UnknownPlatformVariable):
        variables.set_variable("free_money", 1, user=operator)


@pytest.mark.parametrize(
    "key, value",
    [
        ("grace_days", 1.5),
        ("grace_days", "many"),
        ("usage_margin", True),
        ("usage_margin", Decimal("-0.1")),
        ("monthly_usage_cap_points", None),
    ],
)
def test_a_value_the_variable_cannot_hold_is_refused(db, operator, key, value):
    with pytest.raises(variables.InvalidPlatformVariable):
        variables.set_variable(key, value, user=operator)


def test_a_row_that_cannot_be_read_falls_back_to_the_default(db, caplog):
    PlatformVariable.objects.create(key="grace_days", value="whenever")

    assert variables.get_variable("grace_days") == 14
    assert "grace_days" in caplog.text


def test_a_change_is_read_back_immediately_rather_than_from_the_cache(db, operator):
    assert variables.get_variable("monthly_usage_cap_points") == Decimal("20")

    variables.set_variable("monthly_usage_cap_points", Decimal("100"), user=operator)

    assert variables.get_variable("monthly_usage_cap_points") == Decimal("100")
