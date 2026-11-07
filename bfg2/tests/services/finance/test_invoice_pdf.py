"""Tax amounts and literal invoice text survive both shared PDF renderers."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.template.loader import render_to_string

from bfg.common.models import Workspace
from bfg.core.pdf import InvoicePDFGenerator


def document(workspace, subtotal='100', tax='7.50'):
    item = SimpleNamespace(description='Example invoice item', quantity=1, unit_price=Decimal(subtotal),
                           subtotal=Decimal(subtotal), tax=Decimal(tax), tax_type='default')
    return SimpleNamespace(workspace=workspace, invoice_number='INV-TEST', customer=SimpleNamespace(
        user=None, company_name='Company <example> & partners'), currency=SimpleNamespace(code='NZD', symbol='$'),
        issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1), order=None, brand=None, notes='',
        subtotal=Decimal(subtotal), tax=Decimal(tax), total=Decimal(subtotal) + Decimal(tax),
        items=SimpleNamespace(all=lambda: [item]))


@pytest.mark.parametrize(('subtotal', 'tax', 'expected'), [
    ('100', '7.50', '7.5'), ('100', '0', '0'), ('-100', '-15', '15'),
    ('100', '19.99', '19.99'), ('0', '0', None), ('0', '1', None),
])
def test_effective_tax_percentage_preserves_fractional_zero_and_signed_amounts(subtotal, tax, expected):
    assert InvoicePDFGenerator._tax_percent(subtotal, tax) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(('subtotal', 'tax', 'expected'), [('100', '7.50', '7.5%'), ('100', '0', '0%'), ('-100', '-15', '15%')])
def test_html_invoice_uses_effective_line_tax_without_fixed_rate_fallback(subtotal, tax, expected):
    workspace = Workspace.objects.create(name='PDF workspace', slug='pdf-tax-workspace')
    invoice = document(workspace, subtotal, tax)
    generator = InvoicePDFGenerator(backend='weasyprint')
    with patch.object(generator, 'generate_from_template', side_effect=lambda template, context: render_to_string(template, context)):
        html = generator.generate_invoice(invoice)
    assert expected in html
    assert 'Company &lt;example&gt; &amp; partners' in html
    if Decimal(tax) < 0:
        assert 'TOTAL GST 15%' in html
        assert '$-15.00' in html
    if Decimal(tax) == 0:
        assert '15%' not in html


@pytest.mark.django_db
def test_reportlab_preserves_negative_tax_and_escapes_literal_customer_and_number():
    workspace = Workspace.objects.create(name='PDF workspace', slug='pdf-reportlab-workspace')
    invoice = document(workspace, '-100', '-15')
    invoice.invoice_number = 'INV-<one>'
    generator = InvoicePDFGenerator(backend='reportlab')
    with patch.object(generator, '_generate_with_reportlab', return_value=b'%PDF-captured') as output:
        assert generator.generate_invoice(invoice) == b'%PDF-captured'
    content = output.call_args.args[0]
    assert content['title'] == 'Invoice INV-&lt;one&gt;'
    assert content['paragraphs'][0] == 'Customer: Company &lt;example&gt; &amp; partners'
    assert ['', '', 'Tax:', '-15 NZD'] in content['table']
    assert generator.generate_invoice(invoice).startswith(b'%PDF-')
