from types import SimpleNamespace

from bfg.shop.services.order_service import OrderService


def test_generate_order_number_retries_until_unique(monkeypatch):
    service = OrderService(workspace=None, user=None)

    seq = iter(["11111", "22222"])
    monkeypatch.setattr(
        "random.choices",
        lambda *_args, **_kwargs: list(next(seq)),
    )

    class _Exists:
        def __init__(self):
            self.calls = 0

        def exists(self):
            self.calls += 1
            return self.calls == 1

    exists = _Exists()
    monkeypatch.setattr(
        "bfg.shop.services.order_service.Order.objects",
        SimpleNamespace(filter=lambda **_kwargs: exists),
    )

    order_no = service._generate_order_number()
    assert order_no.startswith("ORD-")
    assert order_no.endswith("22222")
