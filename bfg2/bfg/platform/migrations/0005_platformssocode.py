# -*- coding: utf-8 -*-
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("common", "0001_initial"),
        ("platform", "0004_add_cluster_frontend_base_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformSSOCode",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        db_index=True,
                        max_length=128,
                        unique=True,
                        verbose_name="SSO Code",
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(db_index=True, verbose_name="Expires At"),
                ),
                (
                    "used_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="Used At"
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="Created At",
                    ),
                ),
                (
                    "created_by_ip",
                    models.GenericIPAddressField(
                        blank=True, null=True, verbose_name="Created By IP"
                    ),
                ),
                (
                    "next_url",
                    models.CharField(
                        blank=True,
                        default="/admin",
                        max_length=512,
                        verbose_name="Next URL",
                    ),
                ),
                (
                    "redirect_domain",
                    models.CharField(
                        blank=True,
                        help_text="Target domain used for the redirect URL",
                        max_length=255,
                        verbose_name="Redirect Domain",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sso_codes",
                        to="common.workspace",
                        verbose_name="Workspace",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sso_codes",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User",
                    ),
                ),
            ],
            options={
                "verbose_name": "Platform SSO Code",
                "verbose_name_plural": "Platform SSO Codes",
                "indexes": [
                    models.Index(
                        fields=["workspace", "user"],
                        name="platform_pl_workspa_idx",
                    ),
                    models.Index(
                        fields=["expires_at"],
                        name="platform_pl_expires_idx",
                    ),
                ],
            },
        ),
    ]
