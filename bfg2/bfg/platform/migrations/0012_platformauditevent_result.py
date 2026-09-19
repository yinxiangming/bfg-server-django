# Generated manually for an explicit Platform operation outcome.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0011_platform_meter_price_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformauditevent",
            name="result",
            field=models.CharField(default="succeeded", max_length=32),
        ),
    ]
