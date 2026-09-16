from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0017_workspace_extension'),
    ]

    operations = [
        migrations.AddField(
            model_name='workspaceextension',
            name='archive_state',
            field=models.JSONField(blank=True, default=dict, verbose_name='Archive state'),
        ),
    ]
