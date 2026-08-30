# -*- coding: utf-8 -*-
"""Collection orders: which point they attach to, and what they get charged."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError as APIValidationError

from bfg.shop.services.order_service import OrderService


def _point(pk=1, fee=Decimal('0')):
    from bfg.delivery.models import PickupPoint
    return PickupPoint(id=pk, name=f'Point {pk}', code=f'p{pk}', fee=fee)


def _stub_points(monkeypatch, by_id=None, default=None):
    """Stand in for PickupPoint.objects with a two-query surface."""
    def _filter(**kwargs):
        if 'id' in kwargs:
            found = (by_id or {}).get(kwargs['id'])
        else:
            found = default
        return SimpleNamespace(first=lambda: found)

    from bfg.delivery import models as delivery_models
    monkeypatch.setattr(delivery_models.PickupPoint, 'objects', SimpleNamespace(filter=_filter))


# ---------------------------------------------------------------------------
# resolve_pickup_point
# ---------------------------------------------------------------------------

def test_shipping_orders_resolve_no_point(monkeypatch):
    service = OrderService(workspace=None, user=None)
    assert service.resolve_pickup_point('shipping', 7) is None


def test_named_point_is_used(monkeypatch):
    service = OrderService(workspace=None, user=None)
    monkeypatch.setattr(service, 'validate_workspace_access', lambda _obj: None)
    wanted = _point(7)
    _stub_points(monkeypatch, by_id={7: wanted}, default=_point(1))

    assert service.resolve_pickup_point('pickup', 7) is wanted


def test_unknown_point_is_rejected_rather_than_silently_defaulted(monkeypatch):
    service = OrderService(workspace=None, user=None)
    _stub_points(monkeypatch, by_id={}, default=_point(1))

    with pytest.raises(APIValidationError) as exc:
        service.resolve_pickup_point('pickup', 999)
    assert 'pickup_point' in exc.value.detail


def test_falls_back_to_the_workspace_default(monkeypatch):
    # A single-point shop should not have to send an id it has no choice about.
    service = OrderService(workspace=None, user=None)
    monkeypatch.setattr(service, 'validate_workspace_access', lambda _obj: None)
    fallback = _point(1)
    _stub_points(monkeypatch, default=fallback)

    assert service.resolve_pickup_point('pickup', None) is fallback


def test_pickup_without_any_point_configured_is_a_400(monkeypatch):
    service = OrderService(workspace=None, user=None)
    _stub_points(monkeypatch, default=None)

    with pytest.raises(APIValidationError):
        service.resolve_pickup_point('pickup', None)


# ---------------------------------------------------------------------------
# calculate_order_totals
# ---------------------------------------------------------------------------

class _Items:
    def __init__(self, items):
        self._items = items

    def select_related(self, *_a):
        return self

    def all(self):
        return self._items


def _cart(price=Decimal('40.00')):
    # A real (unsaved) Product: calculate_order_totals builds OrderItem rows to
    # hand to the discount service, and a FK will not take a stand-in.
    from bfg.shop.models import Product
    item = SimpleNamespace(
        product=Product(id=1, name='Thing', weight=Decimal('1.0')),
        variant=None,
        quantity=1,
        price=price,
        subtotal=price,
    )
    return SimpleNamespace(items=_Items([item]), customer=None)


def _no_discounts(monkeypatch):
    import bfg.marketing.services.discount_service as ds
    monkeypatch.setattr(ds, 'DiscountCalculationService', lambda **_kw: SimpleNamespace(
        calculate_order_discount=lambda **_k: {
            'discount': Decimal('0.00'),
            'shipping_discount': Decimal('0.00'),
            'gift_card_amount': Decimal('0.00'),
        }
    ))


def test_pickup_is_charged_the_points_fee_not_freight(monkeypatch):
    service = OrderService(workspace=None, user=None)
    _no_discounts(monkeypatch)
    monkeypatch.setattr(service, '_calculate_tax', lambda *_a, **_k: Decimal('0.00'))

    def _boom(*_a, **_k):
        raise AssertionError('freight must not be quoted for an order nobody carries')
    monkeypatch.setattr(service, '_calculate_shipping_cost', _boom)

    totals = service.calculate_order_totals(
        cart=_cart(),
        freight_service_id=99,           # ignored: nothing is being carried
        fulfillment_method='pickup',
        pickup_point=_point(1, fee=Decimal('3.50')),
    )

    assert totals['shipping_cost'] == Decimal('3.50')
    assert totals['total'] == Decimal('43.50')


def test_pickup_without_a_point_costs_nothing(monkeypatch):
    service = OrderService(workspace=None, user=None)
    _no_discounts(monkeypatch)
    monkeypatch.setattr(service, '_calculate_tax', lambda *_a, **_k: Decimal('0.00'))

    totals = service.calculate_order_totals(
        cart=_cart(), fulfillment_method='pickup', pickup_point=None
    )

    assert totals['shipping_cost'] == Decimal('0.00')


def test_shipping_still_quotes_freight(monkeypatch):
    service = OrderService(workspace=None, user=None)
    _no_discounts(monkeypatch)
    monkeypatch.setattr(service, '_calculate_tax', lambda *_a, **_k: Decimal('0.00'))
    monkeypatch.setattr(service, '_calculate_shipping_cost', lambda **_k: Decimal('8.00'))

    totals = service.calculate_order_totals(cart=_cart(), shipping_method='standard')

    assert totals['shipping_cost'] == Decimal('8.00')
    assert totals['total'] == Decimal('48.00')
