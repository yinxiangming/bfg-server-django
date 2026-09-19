# Generated manually for optimistic Cluster configuration updates.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0007_platformauditevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="cluster",
            name="config_version",
            field=models.PositiveIntegerField(default=1, verbose_name="Configuration Version"),
        ),
    ]
