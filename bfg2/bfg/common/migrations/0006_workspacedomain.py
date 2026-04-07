# -*- coding: utf-8 -*-
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0005_workspace_uuid"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceDomain",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hostname", models.CharField(max_length=255, unique=True, verbose_name="Hostname")),
                ("kind", models.CharField(choices=[("system_default", "System default"), ("custom", "Custom")], max_length=20, verbose_name="Kind")),
                ("verification_status", models.CharField(choices=[("pending", "Pending"), ("verified", "Verified"), ("failed", "Failed")], default="pending", max_length=20, verbose_name="Verification Status")),
                ("ssl_status", models.CharField(choices=[("none", "None"), ("pending", "Pending"), ("active", "Active"), ("failed", "Failed")], default="none", max_length=20, verbose_name="SSL Status")),
                ("is_primary", models.BooleanField(default=False, verbose_name="Is Primary")),
                ("last_dns_check_at", models.DateTimeField(blank=True, null=True, verbose_name="Last DNS Check At")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created At")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated At")),
                ("workspace", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="domains", to="common.workspace", verbose_name="Workspace")),
            ],
            options={
                "verbose_name": "Workspace Domain",
                "verbose_name_plural": "Workspace Domains",
                "ordering": ["workspace_id", "kind", "hostname"],
            },
        ),
        migrations.AddIndex(
            model_name="workspacedomain",
            index=models.Index(fields=["workspace", "kind"], name="common_work_workspa_dbb3d9_idx"),
        ),
        migrations.AddIndex(
            model_name="workspacedomain",
            index=models.Index(fields=["workspace", "is_primary"], name="common_work_workspa_93adbe_idx"),
        ),
        migrations.AddIndex(
            model_name="workspacedomain",
            index=models.Index(fields=["workspace", "verification_status"], name="common_work_workspa_d87f2b_idx"),
        ),
        migrations.AddConstraint(
            model_name="workspacedomain",
            constraint=models.UniqueConstraint(condition=models.Q(("kind", "system_default")), fields=("workspace",), name="unique_system_default_domain_per_workspace"),
        ),
        migrations.AddConstraint(
            model_name="workspacedomain",
            constraint=models.UniqueConstraint(condition=models.Q(("is_primary", True)), fields=("workspace",), name="unique_primary_domain_per_workspace"),
        ),
        migrations.RemoveField(
            model_name="workspace",
            name="domain",
        ),
    ]
