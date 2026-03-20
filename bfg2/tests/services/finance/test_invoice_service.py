from types import SimpleNamespace

from bfg.finance.services.invoice_service import InvoiceService


def test_generate_invoice_number_increments_last_sequence(monkeypatch):
    service = InvoiceService(workspace=SimpleNamespace(id=1), user=None)
    last_invoice = SimpleNamespace(invoice_number="INV-0009")
    
    class _FilterResult:
        def __init__(self, kwargs):
            self.kwargs = kwargs

        def order_by(self, *_args):
            return SimpleNamespace(first=lambda: last_invoice)

        def exists(self):
            return False

    monkeypatch.setattr(
        "bfg.finance.services.invoice_service.Invoice.objects",
        SimpleNamespace(filter=lambda **kwargs: _FilterResult(kwargs)),
    )

    number = service._generate_invoice_number()
    assert number == "INV-0010"
