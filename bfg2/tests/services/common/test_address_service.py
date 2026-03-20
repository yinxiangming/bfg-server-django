from types import SimpleNamespace

from bfg.common.services.address_service import AddressService


def test_get_default_address_selects_default_record(monkeypatch):
    service = AddressService(workspace=None, user=None)
    expected = SimpleNamespace(id=1)

    class _Addresses:
        def filter(self, **kwargs):
            assert kwargs == {"is_default": True}
            return SimpleNamespace(first=lambda: expected)

    monkeypatch.setattr(service, "get_addresses_for_object", lambda _obj: _Addresses())
    result = service.get_default_address(SimpleNamespace(id=3))
    assert result is expected
