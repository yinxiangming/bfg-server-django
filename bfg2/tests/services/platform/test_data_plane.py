import json
import zipfile

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from bfg.common.models import Media, MediaLink, Workspace
from bfg.platform.data_plane import (
    DataPlaneBoundaryError,
    LocalWorkspaceDataPlaneAdapter,
)
from bfg.shop.models import ProductCategory


@pytest.mark.django_db
def test_local_archive_contains_workspace_rows_and_media_but_not_global_users(tmp_path):
    source = Workspace.objects.create(name="Source", slug="data-source")
    target = Workspace.objects.create(name="Target", slug="data-target")
    category = ProductCategory.objects.create(
        workspace=source,
        name="Archive category",
        slug="archive-category",
        language="en",
    )
    category.image.save("category.png", ContentFile(b"archive-media"), save=True)
    linked_media = Media.objects.create(
        workspace=source,
        file=ContentFile(b"shared-media", name="shared.bin"),
        media_type="image",
    )
    MediaLink.objects.create(
        media=linked_media,
        content_type=ContentType.objects.get_for_model(ProductCategory),
        object_id=category.pk,
    )

    adapter = LocalWorkspaceDataPlaneAdapter(tmp_path / "archives")
    result = adapter.export(source, snapshot_id="snapshot-1")

    assert result.manifest["format"] == "bfg.workspace-data.v1"
    assert result.manifest["boundaries"]["includes_business_data"] is True
    assert result.manifest["boundaries"]["includes_media"] is True
    assert result.manifest["boundaries"]["includes_global_identity"] is False
    assert result.media_count >= 2

    with zipfile.ZipFile(tmp_path / "archives" / result.artifact_uri) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        table_names = {table["model"] for table in manifest["tables"]}
        assert "shop.productcategory" in table_names
        assert "common.user" not in table_names
        assert all(not member.endswith(".env") for member in archive.namelist())

    restored = adapter.restore(result.artifact_uri, target_workspace=target)

    assert restored.row_count == result.row_count
    restored_category = ProductCategory.all_objects.get(workspace=target, slug="archive-category")
    assert restored_category.image.name.startswith(f"workspace-data/{target.uuid}/")
    restored_link = MediaLink.objects.get(media__workspace=target)
    assert restored_link.content_object == restored_category


@pytest.mark.django_db
def test_local_restore_refuses_non_empty_target_and_cross_cluster_cutover(tmp_path):
    source = Workspace.objects.create(name="Source two", slug="data-source-two")
    target = Workspace.objects.create(name="Target two", slug="data-target-two")
    ProductCategory.objects.create(
        workspace=source, name="One", slug="one", language="en",
    )
    ProductCategory.objects.create(
        workspace=target, name="Already there", slug="already-there", language="en",
    )
    adapter = LocalWorkspaceDataPlaneAdapter(tmp_path / "archives")
    result = adapter.export(source, snapshot_id="snapshot-2")

    with pytest.raises(DataPlaneBoundaryError, match="empty target"):
        adapter.restore(result.artifact_uri, target_workspace=target)
    with pytest.raises(DataPlaneBoundaryError, match="cutover"):
        adapter.cutover(source, target)


@pytest.mark.django_db
def test_data_export_endpoint_is_superuser_only_and_separate_from_config_export(tmp_path, settings):
    settings.WORKSPACE_DATA_ARCHIVE_ROOT = str(tmp_path / "archives")
    owner = Workspace.objects.create(name="Console source", slug="console-data-source")
    superuser = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model().objects.create_superuser(
        username="data-root", password="secret", email="data-root@example.test",
    )
    staff = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model().objects.create_user(
        username="data-staff", password="secret", is_staff=True,
    )
    ProductCategory.objects.create(workspace=owner, name="Console", slug="console", language="en")
    path = f"/api/v1/platform/control/workspaces/{owner.pk}/data-export/"

    client = APIClient()
    client.force_authenticate(user=staff)
    assert client.post(path, {"confirm": True, "reason": "archive test"}, format="json", HTTP_X_IDEMPOTENCY_KEY="staff-key-1").status_code == 403

    client.force_authenticate(user=superuser)
    response = client.post(
        path,
        {"confirm": True, "reason": "archive test"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="root-key-1",
    )
    assert response.status_code == 201
    assert response.data["status"] == "ready"
    assert response.data["row_count"] >= 1
    assert response.data["media_count"] == 0
    assert client.get(f"/api/v1/platform/control/workspaces/{owner.pk}/data-snapshots/").status_code == 200

    verify_response = client.post(
        f"/api/v1/platform/control/workspaces/{owner.pk}/data-verify/",
        {"confirm": True, "reason": "verify archive", "snapshot_id": response.data["id"]},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="root-key-verify-1",
    )
    assert verify_response.status_code == 200
    assert verify_response.data["status"] == "verified"
    verify_replay = client.post(
        f"/api/v1/platform/control/workspaces/{owner.pk}/data-verify/",
        {"confirm": True, "reason": "verify archive", "snapshot_id": response.data["id"]},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="root-key-verify-1",
    )
    assert verify_replay.status_code == 200
    assert verify_replay["Idempotent-Replayed"] == "true"

    target = Workspace.objects.create(name="Console target", slug="console-data-target")
    restore_response = client.post(
        "/api/v1/platform/control/workspaces/data-restore/",
        {
            "confirm": True,
            "reason": "restore archive",
            "snapshot_id": response.data["id"],
            "target_workspace_id": target.pk,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="root-key-restore-1",
    )
    assert restore_response.status_code == 201
    assert restore_response.data["status"] == "completed"
    assert ProductCategory.all_objects.filter(workspace=target, slug="console").exists()

    config_response = client.post(
        f"/api/v1/platform/control/workspaces/{owner.pk}/export/",
        {"confirm": True, "reason": "configuration export"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="root-key-2",
    )
    assert config_response.status_code == 200
    assert json.loads(config_response.content)["scope"] == "configuration-template"
