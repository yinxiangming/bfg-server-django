from types import SimpleNamespace

import pytest

from bfg.core.exceptions import ValidationError
from bfg.shop.services.store_service import StoreService


@pytest.mark.django_db
def test_create_store_raises_when_code_exists(monkeypatch):
    service = StoreService(workspace=SimpleNamespace(id=1), user=None)

    class _StoreManager:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(exists=lambda: True)

    monkeypatch.setattr("bfg.shop.services.store_service.Store.objects", _StoreManager())

    with pytest.raises(ValidationError, match="already exists"):
        service.create_store(name="Main", code="M001")


@pytest.mark.django_db
def test_deactivate_store_sets_flag_and_saves():
    service = StoreService(workspace=SimpleNamespace(id=1), user=None)
    store = SimpleNamespace(workspace_id=1, is_active=True)
    state = {"saved": False}
    store.save = lambda: state.update({"saved": True})

    result = service.deactivate_store(store)

    assert result.is_active is False
    assert state["saved"] is True
