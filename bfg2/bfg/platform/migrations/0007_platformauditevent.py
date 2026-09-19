# Generated manually for Platform control-plane audit logging.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0006_remove_profile_domain_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformAuditEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=100)),
                ("target_type", models.CharField(max_length=64)),
                ("target_id", models.CharField(max_length=255)),
                ("reason", models.CharField(max_length=500)),
                ("request_id", models.UUIDField(blank=True, null=True)),
                ("source_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("before", models.JSONField(blank=True, default=dict)),
                ("after", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="platform_audit_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="platformauditevent",
            index=models.Index(fields=["target_type", "target_id", "-created_at"], name="plat_audit_target_time_idx"),
        ),
        migrations.AddIndex(
            model_name="platformauditevent",
            index=models.Index(fields=["action", "-created_at"], name="plat_audit_action_time_idx"),
        ),
        migrations.AddIndex(
            model_name="platformauditevent",
            index=models.Index(fields=["actor", "-created_at"], name="plat_audit_actor_time_idx"),
        ),
    ]
