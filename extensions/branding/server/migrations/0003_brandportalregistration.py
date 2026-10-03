import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brand_portal', '0002_brandportalprovisioning_sso_code'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BrandPortalRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('callback_origin', models.URLField(max_length=255, verbose_name='Callback origin')),
                ('verified_at', models.DateTimeField(blank=True, null=True, verbose_name='Verified at')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('portal_workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='brand_portal_registrations', to='common.workspace', verbose_name='Portal workspace')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='brand_portal_registrations', to=settings.AUTH_USER_MODEL, verbose_name='User')),
            ],
            options={
                'verbose_name': 'Brand portal registration',
                'verbose_name_plural': 'Brand portal registrations',
                'ordering': ['-created_at', '-id'],
                'indexes': [models.Index(fields=['portal_workspace', 'verified_at'], name='brand_portal_reg_verified_idx')],
                'constraints': [models.UniqueConstraint(fields=('portal_workspace', 'user'), name='brand_portal_registration_user_uniq')],
            },
        ),
    ]
