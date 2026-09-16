from django.db import migrations, models
import uuid


def populate_refund_idempotency_keys(apps, schema_editor):
    Refund = apps.get_model('finance', 'Refund')
    for refund in Refund.objects.filter(idempotency_key__isnull=True).iterator():
        refund.idempotency_key = f'legacy-{refund.pk}-{uuid.uuid4().hex}'
        refund.save(update_fields=['idempotency_key'])


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0008_invoicesettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='refund',
            name='idempotency_key',
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.RunPython(
            populate_refund_idempotency_keys,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='refund',
            name='idempotency_key',
            field=models.CharField(max_length=255),
        ),
        migrations.AddConstraint(
            model_name='refund',
            constraint=models.UniqueConstraint(
                fields=('payment', 'idempotency_key'),
                name='finance_refund_payment_idempotency_uniq',
            ),
        ),
    ]
