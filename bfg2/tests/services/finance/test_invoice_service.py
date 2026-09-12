from datetime import date
from decimal import Decimal

from bfg.common.models import Customer, User, Workspace
from bfg.finance.models import Currency, Invoice
from bfg.finance.services.invoice_service import InvoiceService


def test_generate_invoice_number_increments_last_sequence(db):
    workspace = Workspace.objects.create(name='Invoices', slug='invoices-ws', is_active=True)
    user = User.objects.create_user(username='invoice-buyer', email='invoice-buyer@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    currency = Currency.objects.create(code='NZD', name='New Zealand Dollar', symbol='$', is_active=True)
    Invoice.objects.create(
        workspace=workspace, customer=customer, invoice_number='INV-0009', currency=currency,
        subtotal=Decimal('1'), tax=Decimal('0'), total=Decimal('1'),
        issue_date=date.today(), due_date=date.today(),
    )

    # No workspace is bound here, as in a worker: the lookup must not depend on one.
    number = InvoiceService(workspace=workspace, user=None)._generate_invoice_number()

    assert number == 'INV-0010'
