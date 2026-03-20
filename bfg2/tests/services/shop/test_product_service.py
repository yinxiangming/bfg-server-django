from decimal import Decimal
from types import SimpleNamespace

import pytest

from bfg.shop.services.product_service import ProductService


@pytest.mark.django_db
def test_create_product_generates_unique_slug_and_sets_relations(monkeypatch):
    service = ProductService(workspace=SimpleNamespace(id=1), user=None)

    created_payload = {}
    events = {}

    class _ExistsChain:
        def __init__(self):
            self.calls = 0

        def exists(self):
            self.calls += 1
            return self.calls == 1

    exists_chain = _ExistsChain()

    class _ProductManager:
        @staticmethod
        def filter(**_kwargs):
            return exists_chain

        @staticmethod
        def create(**kwargs):
            created_payload.update(kwargs)
            return SimpleNamespace(
                **kwargs,
                categories=SimpleNamespace(set=lambda v: created_payload.update({"categories_set": v})),
                tags=SimpleNamespace(set=lambda v: created_payload.update({"tags_set": v})),
            )

    monkeypatch.setattr("bfg.shop.services.product_service.Product.objects", _ProductManager())
    service.emit_event = lambda name, data: events.update({"name": name, "data": data})

    product = service.create_product(
        name="Test Product",
        price=Decimal("12.34"),
        language="en",
        categories=[1, 2],
        tags=[3],
    )

    assert product.slug == "test-product-1"
    assert created_payload["categories_set"] == [1, 2]
    assert created_payload["tags_set"] == [3]
    assert events["name"] == "product.created"
