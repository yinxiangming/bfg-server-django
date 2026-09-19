# -*- coding: utf-8 -*-
"""Typed Platform configuration used by the superuser-only control plane."""

from decimal import Decimal, InvalidOperation

from django.apps import apps


PLATFORM_VARIABLES = {
    "default_meter_margin": {
        "kind": "decimal",
        "description": "The margin used by a meter price that does not set one of its own.",
        "default": "0.200000",
    },
    "default_usage_cap_points": {
        "kind": "decimal",
        "description": "The monthly metered-usage cap a workspace follows until it is given its own cap.",
        "default": "1000.0000",
    },
}


def _decimal_string(value, *, nonnegative=True, maximum=None):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Use a decimal number.") from exc
    if not parsed.is_finite() or (nonnegative and parsed < 0):
        raise ValueError("Use a non-negative decimal number.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"Use a value no greater than {maximum}.")
    return format(parsed, "f")


def validate_platform_variable(key, value):
    """Return a JSON-safe, canonical value for a declared Platform variable."""
    definition = PLATFORM_VARIABLES.get(key)
    if not definition:
        raise KeyError(key)
    kind = definition["kind"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("Use true or false.")
        return value
    if kind == "int":
        if isinstance(value, bool):
            raise ValueError("Use a whole number.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Use a whole number.") from exc
        if str(parsed) != str(value).strip() or parsed < 0:
            raise ValueError("Use a non-negative whole number.")
        return parsed
    maximum = Decimal("1") if key == "default_meter_margin" else None
    return _decimal_string(value, maximum=maximum)


def platform_variable_value(key):
    """Read a declared value with its code default when no override exists."""
    definition = PLATFORM_VARIABLES[key]
    Override = apps.get_model("platform", "PlatformVariableOverride")
    override = Override.objects.filter(key=key).only("value").first()
    return override.value if override else definition["default"]


def platform_variable_decimal(key):
    return Decimal(str(platform_variable_value(key)))


def platform_variable_item(key):
    """Serialize the current value and its most recent explanation for the API."""
    definition = PLATFORM_VARIABLES[key]
    Override = apps.get_model("platform", "PlatformVariableOverride")
    Change = apps.get_model("platform", "PlatformVariableChange")
    override = Override.objects.select_related("updated_by").filter(key=key).first()
    change = Change.objects.select_related("changed_by").filter(key=key).first()

    def actor(user):
        return {"id": user.id, "username": user.username} if user else None

    return {
        "key": key,
        "kind": definition["kind"],
        "description": definition["description"],
        "default": definition["default"],
        "value": override.value if override else definition["default"],
        "overridden": bool(override),
        "updated_at": override.updated_at if override else None,
        "updated_by": actor(override.updated_by) if override else None,
        "last_change": (
            {
                "old_value": change.old_value,
                "new_value": change.new_value,
                "reason": change.reason,
                "changed_at": change.changed_at,
                "changed_by": actor(change.changed_by),
            }
            if change else None
        ),
    }
