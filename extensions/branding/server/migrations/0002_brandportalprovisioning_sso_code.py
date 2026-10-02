import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brand_portal', '0001_initial'),
        ('platform', '0008_trial_credit_and_period_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='brandportalprovisioning',
            name='sso_code',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='brand_portal_provisioning',
                to='platform.platformssocode',
                verbose_name='SSO code',
            ),
        ),
    ]
