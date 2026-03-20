from decimal import Decimal
from types import SimpleNamespace

import pytest

from bfg.shop.services.product_service import ProductService


# ---------------------------------------------------------------------------
# Existing test
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# New tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_product_no_slug_collision_slug_matches_name(monkeypatch):
    service = ProductService(workspace=SimpleNamespace(id=1), user=None)

    events = {}
    created_payload = {}

    class _ProductManager:
        @staticmethod
        def filter(**_kwargs):
            # Always returns non-existing → no collision
            return SimpleNamespace(exists=lambda: False)

        @staticmethod
        def create(**kwargs):
            created_payload.update(kwargs)
            return SimpleNamespace(
                **kwargs,
                categories=SimpleNamespace(set=lambda v: None),
                tags=SimpleNamespace(set=lambda v: None),
            )

    monkeypatch.setattr("bfg.shop.services.product_service.Product.objects", _ProductManager())
    service.emit_event = lambda name, data: events.update({"name": name})

    product = service.create_product(name="My Widget", price=Decimal("9.99"), language="en")

    # No collision → slug should be the plain slugified name
    assert product.slug == "my-widget"
    assert events["name"] == "product.created"


@pytest.mark.django_db
def test_create_product_slug_collision_retries(monkeypatch):
    service = ProductService(workspace=SimpleNamespace(id=1), user=None)

    created_payload = {}
    events = {}

    class _ExistsChain:
        def __init__(self):
            self.calls = 0

        def exists(self):
            self.calls += 1
            # First slug exists, second doesn't
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
                categories=SimpleNamespace(set=lambda v: None),
                tags=SimpleNamespace(set=lambda v: None),
            )

    monkeypatch.setattr("bfg.shop.services.product_service.Product.objects", _ProductManager())
    service.emit_event = lambda name, data: events.update({"name": name})

    product = service.create_product(name="Cool Product", price=Decimal("5.00"), language="en")

    # First collision → suffix -1 appended
    assert product.slug == "cool-product-1"
    assert events["name"] == "product.created"


@pytest.mark.django_db
def test_create_product_emits_product_created_event(monkeypatch):
    service = ProductService(workspace=SimpleNamespace(id=1), user=None)

    emitted_events = []

    class _ProductManager:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(exists=lambda: False)

        @staticmethod
        def create(**kwargs):
            p = SimpleNamespace(
                **kwargs,
                categories=SimpleNamespace(set=lambda v: None),
                tags=SimpleNamespace(set=lambda v: None),
            )
            return p

    monkeypatch.setattr("bfg.shop.services.product_service.Product.objects", _ProductManager())
    service.emit_event = lambda name, data: emitted_events.append({"name": name, "data": data})

    product = service.create_product(name="Event Test", price=Decimal("1.00"), language="en")

    assert len(emitted_events) == 1
    assert emitted_events[0]["name"] == "product.created"
    assert emitted_events[0]["data"]["product"] is product


@pytest.mark.django_db
def test_create_product_empty_categories_and_tags_calls_set_with_empty(monkeypatch):
    service = ProductService(workspace=SimpleNamespace(id=1), user=None)

    set_calls = {}

    class _ProductManager:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(exists=lambda: False)

        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(
                **kwargs,
                categories=SimpleNamespace(set=lambda v: set_calls.update({"categories": v})),
                tags=SimpleNamespace(set=lambda v: set_calls.update({"tags": v})),
            )

    monkeypatch.setattr("bfg.shop.services.product_service.Product.objects", _ProductManager())
    service.emit_event = lambda name, data: None

    service.create_product(
        name="Empty Relations",
        price=Decimal("1.00"),
        language="en",
        categories=[],
        tags=[],
    )

    assert set_calls["categories"] == []
    assert set_calls["tags"] == []
