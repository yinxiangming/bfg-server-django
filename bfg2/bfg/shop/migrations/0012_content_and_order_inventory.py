"""Consolidate this feature PR; preserve published migration history and backfills."""

import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models
from django.db.models.functions import Coalesce
from django.utils import timezone


def preserve_paid_orders(apps, schema_editor):
    # Historical paid orders have already followed the old fulfillment path.
    apps.get_model('shop', 'Order').all_objects.using(schema_editor.connection.alias).filter(
        payment_status='paid', stock_deducted_at__isnull=True,
    ).update(stock_deducted_at=Coalesce('paid_at', 'created_at'))


class Migration(migrations.Migration):
    replaces = [
        ('shop', '0012_productcontentpolicy'),
        ('shop', '0013_order_stock_policy'),
        ('shop', '0014_order_stock_reservations'),
    ]

    dependencies = [
        ('common', '0018_workspace_extension_archive_state'),
        ('shop', '0011_subscriptionplan_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductContentPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scope_key', models.CharField(editable=False, max_length=64)),
                ('language', models.CharField(default='en', max_length=10)),
                ('slot', models.CharField(choices=[('footer', 'Footer')], default='footer', max_length=16)),
                ('mode', models.CharField(choices=[('own', 'Own'), ('inherit', 'Inherit'), ('off', 'Off')], default='own', max_length=10)),
                ('include_descendants', models.BooleanField(default=False)),
                ('text', models.TextField(blank=True)),
                ('enabled', models.BooleanField(default=True)),
                ('revision', models.PositiveIntegerField(default=1, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='shop.productcategory')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='common.workspace')),
            ],
            options={
                'ordering': ['scope_key', 'language'],
                'base_manager_name': 'all_objects',
                'constraints': [models.UniqueConstraint(fields=('workspace', 'scope_key', 'language', 'slot'), name='shop_content_policy_scope_uniq')],
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddField(model_name='order', name='stock_deduction_event', field=models.CharField(
            max_length=24, choices=[('order_created', 'Order created'), ('payment_confirmed', 'Payment confirmed')], default='payment_confirmed')),
        migrations.AddField(model_name='order', name='stock_deducted_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.RunPython(preserve_paid_orders, migrations.RunPython.noop),
        migrations.AddField(model_name='order', name='stock_error', field=models.CharField(max_length=255, blank=True)),
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
