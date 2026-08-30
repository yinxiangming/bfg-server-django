# -*- coding: utf-8 -*-
"""Coordinates arriving at full double precision must round, not 400.

Regression cover for `bfg.core.serializer_fields.CoordinateField`.
"""

from decimal import Decimal

import pytest

from bfg.common.serializers import AddressSerializer
from bfg.core.serializer_fields import CoordinateField
from bfg.delivery.serializers import WarehouseSerializer

ADDRESS = {
    'full_name': 'Mark Yin',
    'phone': '0211234567',
    'address_line1': '12 Queen Street',
    'city': 'Auckland',
    'postal_code': '1010',
    'country': 'NZ',
}


@pytest.mark.parametrize('serializer_class', [AddressSerializer, WarehouseSerializer])
@pytest.mark.parametrize('field_name', ['latitude', 'longitude'])
def test_coordinate_columns_use_coordinate_field(serializer_class, field_name):
    assert isinstance(serializer_class().fields[field_name], CoordinateField)


def test_geocoder_precision_is_rounded_to_the_column():
    # What the Google SDK's normalisation arithmetic makes of the coordinates
    # of 12 Queen Street: 17 significant digits into a DECIMAL(10, 7) column.
    serializer = AddressSerializer(data=dict(
        ADDRESS, latitude=-36.844142999999995, longitude=174.76730859999998,
    ))

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data['latitude'] == Decimal('-36.8441430')
    assert serializer.validated_data['longitude'] == Decimal('174.7673086')


def test_value_too_large_for_the_column_is_still_rejected():
    # Rounding must not turn into "accept anything" — 1234.5678901 has more
    # whole digits than the column holds and is not a latitude either.
    serializer = AddressSerializer(data=dict(ADDRESS, latitude=1234.5678901))

    assert not serializer.is_valid()
    assert serializer.errors['latitude'][0].code == 'max_digits'
