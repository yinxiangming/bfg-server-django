# Generated manually to join the existing Finance 0006 branch with Platform rate fields.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0006_exchange_rate_platform_audit_fields"),
        ("finance", "0006_alter_invoice_options_alter_payment_options_and_more"),
    ]

    operations = []
