from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0008_staffrole_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditlog',
            name='module',
            field=models.CharField(blank=True, db_index=True, max_length=32, verbose_name='Module'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['workspace', 'module', '-created_at'], name='audit_ws_module_time_idx'),
        ),
    ]
