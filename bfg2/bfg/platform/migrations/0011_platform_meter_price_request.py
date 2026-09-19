# Generated manually for persistent Platform meter-price request idempotency.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0010_workspace_meter_usage"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformMeterPriceRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("idempotency_key", models.CharField(max_length=128)),
                ("payload_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="platform_meter_price_requests", to=settings.AUTH_USER_MODEL)),
                ("price", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="idempotency_request", to="platform.platformmeterprice")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="platformmeterpricerequest",
            constraint=models.UniqueConstraint(fields=("created_by", "idempotency_key"), name="platform_meter_price_request_key"),
        ),
    ]
