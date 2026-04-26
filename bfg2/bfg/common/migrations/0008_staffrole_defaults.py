# Generated for role registry refactor — adds frozen default_permissions
# and owner_module to StaffRole so each role can be restored to its
# module-declared baseline.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0007_invitation'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffrole',
            name='default_permissions',
            field=models.JSONField(blank=True, default=dict, verbose_name='Default Permissions'),
        ),
        migrations.AddField(
            model_name='staffrole',
            name='owner_module',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Owner Module'),
        ),
    ]
