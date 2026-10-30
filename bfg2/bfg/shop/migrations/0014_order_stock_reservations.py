import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [('shop', '0013_order_stock_policy')]
    operations = [
        migrations.AddField(model_name='order', name='stock_error', field=models.CharField(max_length=255, blank=True)),
        # Existing aggregate reservations have no reliable owner/warehouse evidence.
        migrations.AddField(model_name='order', name='stock_reservations_managed', field=models.BooleanField(default=False)),
        migrations.AlterField(model_name='order', name='stock_reservations_managed', field=models.BooleanField(default=True)),
        migrations.CreateModel(name='OrderItemStockReservation', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('quantity', models.PositiveIntegerField()),
            ('state', models.CharField(max_length=16, choices=[('reserved', 'Reserved'), ('consumed', 'Consumed'), ('released', 'Released')], default='reserved')),
            ('reserved_at', models.DateTimeField(default=timezone.now)),
            ('consumed_at', models.DateTimeField(null=True, blank=True)),
            ('released_at', models.DateTimeField(null=True, blank=True)),
            ('inventory', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='order_reservations', to='shop.variantinventory')),
            ('item', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='stock_reservation', to='shop.orderitem')),
        ], options={'constraints': [models.CheckConstraint(condition=models.Q(quantity__gte=1), name='shop_order_reservation_positive')]}),
    ]
