# Generated manually for WorkspaceDomain refactor.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0005_platformssocode"),
        ("common", "0006_workspacedomain"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="workspaceplatformprofile",
            name="custom_domain",
        ),
        migrations.RemoveField(
            model_name="workspaceplatformprofile",
            name="ssl_status",
        ),
    ]
