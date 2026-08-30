"""Serializer fields shared across BFG modules."""

import decimal

from rest_framework import serializers


class CoordinateField(serializers.DecimalField):
    """A ``DecimalField`` that rounds to ``decimal_places`` instead of rejecting.

    DRF checks precision *before* it quantizes, so a latitude straight out of a
    geocoder — ``-36.844142999999995``, which is what the Google SDK's own
    normalisation arithmetic makes of -36.844143 — is refused with "no more than
    10 digits in total" even though it lands in DECIMAL(10, 7) exactly once
    rounded. Any caller with a map behind it trips this, and the seventh decimal
    place is already about a centimetre, so the digits being refused cannot
    matter to anyone.

    Only use this where rounding is genuinely free. Money must keep rejecting
    over-precise input rather than quietly changing the amount.
    """

    def validate_precision(self, value):
        try:
            value = self.quantize(value)
        except decimal.InvalidOperation:
            # More whole digits than the column holds, so this is not a
            # coordinate at all. Leave it be and let the check below reject it.
            pass
        return super().validate_precision(value)


class CoordinateFieldsMixin:
    """Serialize a ModelSerializer's lat/lng columns with ``CoordinateField``.

    Built from the model field, so the precision stays in one place — the model
    — rather than being restated by every serializer that exposes coordinates.
    """

    coordinate_fields = ('latitude', 'longitude')

    def build_standard_field(self, field_name, model_field):
        field_class, field_kwargs = super().build_standard_field(field_name, model_field)
        if field_name in self.coordinate_fields and issubclass(field_class, serializers.DecimalField):
            field_class = CoordinateField
        return field_class, field_kwargs
