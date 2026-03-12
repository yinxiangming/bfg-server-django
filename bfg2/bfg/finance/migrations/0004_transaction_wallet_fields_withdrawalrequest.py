# Generated manually: Transaction wallet fields + WithdrawalRequest

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0001_initial'),
        ('finance', '0003_wallet_workspace_dual_balance'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='wallet',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='wallet_transactions',
                to='finance.wallet',
            ),
        ),
        migrations.AddField(
            model_name='transaction',
            name='balance_type',
            field=models.CharField(
                blank=True,
                choices=[('', 'N/A'), ('cash', 'Cash (Gold)'), ('credit', 'Credit (Silver)')],
                max_length=10,
                verbose_name='Balance Type',
            ),
        ),
        migrations.AddField(
            model_name='transaction',
            name='tx_status',
            field=models.CharField(
                choices=[('completed', 'Completed'), ('pending', 'Pending'), ('reversed', 'Reversed')],
                default='completed',
                max_length=20,
                verbose_name='Status',
            ),
        ),
        migrations.AddField(
            model_name='transaction',
            name='source_type',
            field=models.CharField(blank=True, max_length=50, verbose_name='Source Type'),
        ),
        migrations.AddField(
            model_name='transaction',
            name='source_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='transaction_type',
            field=models.CharField(
                choices=[
                    ('payment', 'Payment'),
                    ('refund', 'Refund'),
                    ('credit', 'Credit'),
                    ('debit', 'Debit'),
                    ('adjustment', 'Adjustment'),
                    ('topup', 'Top-up'),
                    ('resale_payout', 'Resale Payout'),
                    ('withdrawal', 'Withdrawal'),
                    ('reward', 'Reward'),
                ],
                max_length=20,
                verbose_name='Type',
            ),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['wallet', '-created_at'], name='finance_tra_wallet__idx'),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['source_type', 'source_id'], name='finance_tra_source__idx'),
        ),
        migrations.CreateModel(
            name='WithdrawalRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Amount')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('approved', 'Approved'),
                        ('rejected', 'Rejected'),
                        ('processing', 'Processing'),
                        ('completed', 'Completed'),
                        ('cancelled', 'Cancelled'),
                    ],
                    default='pending',
                    max_length=20,
                    verbose_name='Status',
                )),
                ('payout_method', models.CharField(blank=True, max_length=100, verbose_name='Payout Method')),
                ('payout_details', models.JSONField(blank=True, default=dict, verbose_name='Payout Details')),
                ('notes', models.TextField(blank=True, verbose_name='Notes')),
                ('rejection_reason', models.TextField(blank=True, verbose_name='Rejection Reason')),
                ('requested_at', models.DateTimeField(default=timezone.now, verbose_name='Requested At')),
                ('approved_at', models.DateTimeField(blank=True, null=True, verbose_name='Approved At')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='Completed At')),
                ('approved_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='withdrawal_requests_approved',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('requested_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='withdrawal_requests_made',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('transaction', models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='withdrawal_request',
                    to='finance.transaction',
                )),
                ('wallet', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='withdrawal_requests',
                    to='finance.wallet',
                )),
            ],
            options={
                'verbose_name': 'Withdrawal Request',
                'verbose_name_plural': 'Withdrawal Requests',
                'ordering': ['-requested_at'],
            },
        ),
        migrations.AddIndex(
            model_name='withdrawalrequest',
            index=models.Index(fields=['wallet', 'status'], name='finance_wit_wallet__idx'),
        ),
    ]
