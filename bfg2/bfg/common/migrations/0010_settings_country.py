from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0009_auditlog_module'),
    ]

    operations = [
        migrations.AddField(
            model_name='settings',
            name='country',
            field=models.CharField(blank=True, max_length=2, verbose_name='Country'),
        ),
    ]
