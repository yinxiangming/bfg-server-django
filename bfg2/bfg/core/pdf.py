"""
BFG Core PDF Generator

PDF generation utilities using WeasyPrint or ReportLab
"""

from typing import Optional, Dict, Any
from io import BytesIO
from django.template.loader import render_to_string
from django.conf import settings


class PDFGenerator:
    """
    PDF generation utility
    
    Supports both WeasyPrint (HTML to PDF) and ReportLab (programmatic PDF)
    """
    
    def __init__(self, backend: Optional[str] = None):
        """
        Initialize PDF generator
        
        Args:
            backend: 'weasyprint' or 'reportlab'. If None, auto-detect available backend.
        """
        if backend is None:
            # Auto-detect available backend
            backend = self._detect_backend()
        
        self.backend = backend
    
    def _detect_backend(self) -> str:
        """
        Detect which PDF backend is available
        
        Returns:
            str: 'weasyprint' or 'reportlab'
        """
        # Try WeasyPrint first (preferred for HTML templates)
        try:
            import weasyprint
            return 'weasyprint'
        except ImportError:
            pass
        
        # Fallback to ReportLab
        try:
            import reportlab
            return 'reportlab'
        except ImportError:
            raise ImportError(
                "No PDF backend available. "
                "Please install either WeasyPrint (pip install weasyprint) "
                "or ReportLab (pip install reportlab)"
            )
    
    def generate_from_html(
        self,
        html_content: str,
        base_url: Optional[str] = None
    ) -> bytes:
        """
        Generate PDF from HTML content (WeasyPrint)
        
        Args:
            html_content: HTML string
            base_url: Base URL for resolving relative URLs
            
        Returns:
            bytes: PDF content
        """
        if self.backend == 'weasyprint':
            return self._generate_with_weasyprint(html_content, base_url)
        else:
            raise NotImplementedError(f"Backend '{self.backend}' not implemented for HTML")
    
    def generate_from_template(
        self,
        template_name: str,
        context: Dict[str, Any],
        base_url: Optional[str] = None
    ) -> bytes:
        """
        Generate PDF from Django template
        
        Args:
            template_name: Template path
            context: Template context
            base_url: Base URL for resolving relative URLs
            
        Returns:
            bytes: PDF content
        """
        html_content = render_to_string(template_name, context)
        return self.generate_from_html(html_content, base_url)
    
    def _generate_with_weasyprint(
        self,
        html_content: str,
        base_url: Optional[str] = None
    ) -> bytes:
        """
        Generate PDF using WeasyPrint
        
        Args:
            html_content: HTML string
            base_url: Base URL for resolving relative URLs
            
        Returns:
            bytes: PDF content
        """
        try:
            from weasyprint import HTML, CSS
            
            # Create HTML object
            html = HTML(string=html_content, base_url=base_url)
            
            # Generate PDF
            pdf_bytes = html.write_pdf()
            
            return pdf_bytes
            
        except ImportError:
            raise ImportError(
                "WeasyPrint is not installed. "
                "Install it with: pip install weasyprint"
            )
    
    def _generate_with_reportlab(
        self,
        content: Dict[str, Any]
    ) -> bytes:
        """
        Generate PDF using ReportLab (programmatic approach)
        
        Args:
            content: Content dictionary with PDF structure
            
        Returns:
            bytes: PDF content
        """
        try:
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib import colors
            
            buffer = BytesIO()
            
            # Create PDF
            doc = SimpleDocTemplate(
                buffer,
                pagesize=content.get('page_size', A4),
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            # Build story (content elements)
            story = []
            styles = getSampleStyleSheet()
            
            # Add title
            if 'title' in content:
                title = Paragraph(content['title'], styles['Heading1'])
                story.append(title)
                story.append(Spacer(1, 12))
            
            # Add paragraphs
            if 'paragraphs' in content:
                for para in content['paragraphs']:
                    p = Paragraph(para, styles['Normal'])
                    story.append(p)
                    story.append(Spacer(1, 12))
            
            # Add table
            if 'table' in content:
                table_data = content['table']
                t = Table(table_data)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 14),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                story.append(t)
            
            # Build PDF
            doc.build(story)
            
            # Get PDF bytes
            pdf_bytes = buffer.getvalue()
            buffer.close()
            
            return pdf_bytes
            
        except ImportError:
            raise ImportError(
                "ReportLab is not installed. "
                "Install it with: pip install reportlab"
            )


class InvoicePDFGenerator(PDFGenerator):
    """
    Specialized PDF generator for invoices
    """
    
    def generate_invoice(self, invoice) -> bytes:
        """
        Generate invoice PDF
        
        Args:
            invoice: Invoice instance
            
        Returns:
            bytes: PDF content
        """
        context = {
            'invoice': invoice,
            'items': invoice.items.all(),
            'workspace': invoice.workspace,
            'customer': invoice.customer,
        }
        
        # Try to use HTML template first (requires WeasyPrint)
        # If WeasyPrint is not available, fallback to ReportLab
        if self.backend == 'weasyprint':
            try:
                return self.generate_from_template(
                    'invoice/invoice_pdf.html',
                    context
                )
            except ImportError:
                # WeasyPrint not available, fallback to ReportLab
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    "WeasyPrint is not installed. Install it with: pip install weasyprint. "
                    "Falling back to ReportLab."
                )
                return self._generate_invoice_with_reportlab(invoice)
            except Exception as e:
                # Other template errors - log and fallback
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Invoice template error: {e}. Falling back to ReportLab.")
                try:
                    return self._generate_invoice_with_reportlab(invoice)
                except ImportError:
                    raise ImportError(
                        "ReportLab is required for PDF generation fallback. "
                        "Please install it with: pip install reportlab"
                    )
        else:
            # Use ReportLab directly
            return self._generate_invoice_with_reportlab(invoice)
    
    def _generate_invoice_with_reportlab(self, invoice) -> bytes:
        """
        Generate invoice using ReportLab
        
        Args:
            invoice: Invoice instance
            
        Returns:
            bytes: PDF content
        """
        # Build table data
        table_data = [
            ['Description', 'Quantity', 'Unit Price', 'Subtotal']
        ]
        
        for item in invoice.items.all():
            table_data.append([
                item.description,
                str(item.quantity),
                f"{item.unit_price} {invoice.currency.code}",
                f"{item.subtotal} {invoice.currency.code}"
            ])
        
        # Add totals
        table_data.append(['', '', 'Subtotal:', f"{invoice.subtotal} {invoice.currency.code}"])
        
        # Add shipping if available from order
        if invoice.order and invoice.order.shipping_cost and invoice.order.shipping_cost > 0:
            table_data.append(['', '', 'Shipping:', f"{invoice.order.shipping_cost} {invoice.currency.code}"])
        
        # Add discount if available from order
        if invoice.order and invoice.order.discount and invoice.order.discount > 0:
            table_data.append(['', '', 'Discount:', f"-{invoice.order.discount} {invoice.currency.code}"])
        
        if invoice.tax > 0:
            table_data.append(['', '', 'Tax:', f"{invoice.tax} {invoice.currency.code}"])
        
        table_data.append(['', '', 'Total:', f"{invoice.total} {invoice.currency.code}"])
        
        # Get customer name safely
        if invoice.customer and invoice.customer.user:
            customer_name = invoice.customer.user.get_full_name() or invoice.customer.user.username
        elif invoice.customer and invoice.customer.company_name:
            customer_name = invoice.customer.company_name
        else:
            customer_name = str(invoice.customer) if invoice.customer else "Unknown Customer"
        
        # Build paragraphs
        paragraphs = [
            f"Customer: {customer_name}",
            f"Issue Date: {invoice.issue_date}",
        ]
        
        if invoice.due_date:
            paragraphs.append(f"Due Date: {invoice.due_date}")
        
        paragraphs.append("")
        
        content = {
            'title': f"Invoice {invoice.invoice_number}",
            'paragraphs': paragraphs,
            'table': table_data
        }
        
        return self._generate_with_reportlab(content)


# Convenience function
def generate_invoice_pdf(invoice) -> bytes:
    """
    Generate invoice PDF (convenience function)
    
    Args:
        invoice: Invoice instance
        
    Returns:
        bytes: PDF content
    """
    generator = InvoicePDFGenerator()
    return generator.generate_invoice(invoice)
