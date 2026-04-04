import uuid
from django.db import migrations, models


def populate_workspace_uuids(apps, schema_editor):
    Workspace = apps.get_model('common', 'Workspace')
    for ws in Workspace.objects.filter(uuid__isnull=True):
        ws.uuid = uuid.uuid4()
        ws.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0004_user_platform_user_id'),
    ]

    operations = [
        # Step 1: add nullable uuid column
        migrations.AddField(
            model_name='workspace',
            name='uuid',
            field=models.UUIDField(
                null=True,
                blank=True,
                verbose_name='UUID',
                help_text='Globally unique identifier for cross-instance workspace identification',
            ),
        ),
        # Step 2: fill existing rows
        migrations.RunPython(populate_workspace_uuids, reverse_code=migrations.RunPython.noop),
        # Step 3: enforce unique + non-null + default
        migrations.AlterField(
            model_name='workspace',
            name='uuid',
            field=models.UUIDField(
                default=uuid.uuid4,
                unique=True,
                editable=False,
                db_index=True,
                verbose_name='UUID',
                help_text='Globally unique identifier for cross-instance workspace identification',
            ),
        ),
    ]
