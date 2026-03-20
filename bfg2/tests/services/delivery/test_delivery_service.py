from decimal import Decimal
from types import SimpleNamespace

from bfg.delivery.services.delivery_service import DeliveryService


def test_address_to_dict_includes_coordinates():
    service = DeliveryService(workspace=None, user=None)
    address = SimpleNamespace(
        full_name="A",
        company="",
        address_line1="l1",
        address_line2="",
        city="c",
        state="s",
        postal_code="p",
        country="NZ",
        phone="1",
        email="e",
        latitude=Decimal("1.2"),
        longitude=Decimal("3.4"),
    )
    result = service._address_to_dict(address)
    assert result["latitude"] == 1.2
    assert result["longitude"] == 3.4
