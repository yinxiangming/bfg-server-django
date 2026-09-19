# Generated manually for Platform console configuration controls.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0002_alter_settings_default_currency"),
        ("platform", "0008_cluster_config_version"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformMeterPrice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("meter", models.CharField(db_index=True, max_length=100)),
                ("vendor_cost", models.DecimalField(decimal_places=8, max_digits=20)),
                ("unit_size", models.PositiveIntegerField()),
                ("margin", models.DecimalField(blank=True, decimal_places=6, max_digits=10, null=True)),
                ("effective_from", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_meter_prices", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["meter", "-effective_from", "-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PlatformVariableChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(db_index=True, max_length=100)),
                ("old_value", models.JSONField(blank=True, null=True)),
                ("new_value", models.JSONField(blank=True, null=True)),
                ("reason", models.CharField(max_length=500)),
                ("changed_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_variable_changes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-changed_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PlatformVariableOverride",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=100, unique=True)),
                ("value", models.JSONField()),
                ("reason", models.CharField(max_length=500)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_variable_overrides", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["key"]},
        ),
        migrations.CreateModel(
            name="WorkspaceEntitlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(blank=True, default="", max_length=255)),
                ("status", models.CharField(choices=[("active", "Active"), ("expired", "Expired"), ("revoked", "Revoked")], default="active", max_length=20)),
                ("source", models.CharField(default="platform_grant", max_length=40)),
                ("starts_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("current_period_end", models.DateTimeField(blank=True, null=True)),
                ("reason", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="workspace_entitlement_grants", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="platform_entitlements", to="common.workspace")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="WorkspaceUsageCap",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cap_points", models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="workspace_usage_cap_updates", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="platform_usage_cap", to="common.workspace")),
            ],
        ),
        migrations.AddIndex(model_name="platformmeterprice", index=models.Index(fields=["meter", "effective_from"], name="plat_meter_effective_idx")),
        migrations.AddIndex(model_name="platformvariablechange", index=models.Index(fields=["key", "-changed_at"], name="plat_variable_change_idx")),
        migrations.AddIndex(model_name="workspaceentitlement", index=models.Index(fields=["workspace", "key", "status"], name="plat_entitlement_lookup_idx")),
    ]
