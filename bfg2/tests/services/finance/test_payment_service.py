from types import SimpleNamespace

from bfg.finance.services.payment_service import PaymentService


def test_generate_payment_number_retries_until_unique(monkeypatch):
    service = PaymentService(workspace=None, user=None)
    seq = iter(["11111", "22222"])
    monkeypatch.setattr("random.choices", lambda *_a, **_k: list(next(seq)))

    class _Exists:
        def __init__(self):
            self.calls = 0

        def exists(self):
            self.calls += 1
            return self.calls == 1

    exists = _Exists()
    monkeypatch.setattr(
        "bfg.finance.services.payment_service.Payment.objects",
        SimpleNamespace(filter=lambda **_kwargs: exists),
    )
    number = service._generate_payment_number()
    assert number.startswith("PAY-")
