from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0012_workspaceplatformprofile_placement_fence_and_more"),
        ("common", "0011_media_is_sensitive"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceDataSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("archive", "Archive"), ("transfer", "Transfer"), ("restore", "Restore")], default="archive", max_length=16)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("exporting", "Exporting"), ("ready", "Ready"), ("verifying", "Verifying"), ("verified", "Verified"), ("restoring", "Restoring"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=16)),
                ("artifact_uri", models.CharField(blank=True, max_length=500)),
                ("artifact_sha256", models.CharField(blank=True, max_length=64)),
                ("manifest_sha256", models.CharField(blank=True, max_length=64)),
                ("manifest", models.JSONField(blank=True, default=dict)),
                ("row_count", models.PositiveBigIntegerField(default=0)),
                ("media_count", models.PositiveBigIntegerField(default=0)),
                ("media_bytes", models.PositiveBigIntegerField(default=0)),
                ("source_cluster_id", models.CharField(blank=True, max_length=32)),
                ("target_cluster_id", models.CharField(blank=True, max_length=32)),
                ("failure_code", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="workspace_data_snapshots", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="data_snapshots", to="common.workspace")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="workspacedatasnapshot",
            index=models.Index(fields=["workspace", "-created_at"], name="plat_snapshot_ws_time_idx"),
        ),
        migrations.AddIndex(
            model_name="workspacedatasnapshot",
            index=models.Index(fields=["status", "-created_at"], name="plat_snapshot_status_idx"),
        ),
    ]
