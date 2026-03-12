# Generated manually for Wallet workspace + cash/credit balance

from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


def copy_balance_and_workspace(apps, schema_editor):
    """Copy balance to cash_balance and set workspace from customer."""
    Wallet = apps.get_model('finance', 'Wallet')
    for w in Wallet.objects.select_related('customer').all():
        w.workspace_id = w.customer.workspace_id
        w.cash_balance = w.balance
        w.save(update_fields=['workspace_id', 'cash_balance'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0001_initial'),
        ('finance', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='wallet',
            name='workspace',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='wallets',
                to='common.workspace',
            ),
        ),
        migrations.AddField(
            model_name='wallet',
            name='cash_balance',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                max_digits=12,
                verbose_name='Cash Balance',
            ),
        ),
        migrations.AddField(
            model_name='wallet',
            name='credit_balance',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                max_digits=12,
                verbose_name='Credit Balance',
            ),
        ),
        migrations.RunPython(copy_balance_and_workspace, noop),
        migrations.RemoveField(
            model_name='wallet',
            name='balance',
        ),
        migrations.AlterField(
            model_name='wallet',
            name='workspace',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='wallets',
                to='common.workspace',
            ),
        ),
        migrations.AlterField(
            model_name='wallet',
            name='customer',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='wallets',
                to='common.customer',
            ),
        ),
        migrations.AddConstraint(
            model_name='wallet',
            constraint=models.UniqueConstraint(
                fields=('workspace', 'customer'),
                name='finance_wallet_workspace_customer_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='wallet',
            index=models.Index(fields=['workspace', 'customer'], name='finance_wal_workspa_idx'),
        ),
    ]
