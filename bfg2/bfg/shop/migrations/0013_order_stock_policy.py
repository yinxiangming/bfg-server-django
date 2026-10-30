from django.db import migrations, models
from django.db.models.functions import Coalesce


def preserve_paid_orders(apps, schema_editor):
    # Historical paid orders have already followed the old fulfillment path.
    apps.get_model('shop', 'Order').all_objects.using(schema_editor.connection.alias).filter(
        payment_status='paid', stock_deducted_at__isnull=True,
    ).update(stock_deducted_at=Coalesce('paid_at', 'created_at'))


class Migration(migrations.Migration):
    dependencies = [('shop', '0012_productcontentpolicy')]
    operations = [
        migrations.AddField(model_name='order', name='stock_deduction_event', field=models.CharField(
            max_length=24, choices=[('order_created', 'Order created'), ('payment_confirmed', 'Payment confirmed')], default='payment_confirmed')),
        migrations.AddField(model_name='order', name='stock_deducted_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.RunPython(preserve_paid_orders, migrations.RunPython.noop),
    ]
