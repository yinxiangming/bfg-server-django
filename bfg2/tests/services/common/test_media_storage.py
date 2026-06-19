"""Media storage / S3 helpers + web.Media migration (WI-393)."""
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command

from bfg.common.models.core import Media as CommonMedia
from bfg.common.serializers import media_file_url_for_serializer, signed_media_url
from bfg.common.services.workspace_service import WorkspaceService
from bfg.web.models import Media as WebMedia

User = get_user_model()


def _workspace(slug):
    user = User.objects.create_user(username=f"media-{slug}", password="x")
    ws = WorkspaceService(workspace=None, user=user).create_workspace(
        name=f"Media {slug}", slug=slug, owner_user=user)
    return ws, user


def test_signed_media_url_public_when_not_sensitive(db, settings):
    settings.USE_S3_MEDIA = False
    ws, user = _workspace("pub")
    m = CommonMedia.objects.create(workspace=ws, media_type="image", is_sensitive=False)
    m.file.name = "media/2/x.jpg"
    m.save()
    # Public path is the plain CDN-style URL, no signing helper involved.
    assert signed_media_url(m) == media_file_url_for_serializer(m)


def test_signed_media_url_uses_private_storage_for_sensitive(db, settings):
    settings.USE_S3_MEDIA = True
    ws, user = _workspace("sens")
    m = CommonMedia.objects.create(workspace=ws, media_type="image", is_sensitive=True)
    m.file.name = "media/2/photos/secret.jpg"
    m.save()
    fake_storage = mock.Mock()
    fake_storage.url.return_value = "https://private.example.com/media/2/photos/secret.jpg?X-Amz-Signature=abc"
    with mock.patch("bfg.common.storage.private_media_storage", return_value=fake_storage):
        url = signed_media_url(m)
    fake_storage.url.assert_called_once_with("media/2/photos/secret.jpg")
    assert "X-Amz-Signature" in url


def test_migrate_web_media_creates_common_media_and_is_idempotent(db):
    ws, user = _workspace("legacy")
    WebMedia.objects.create(
        workspace=ws, file="media/2020/05/old.jpg", file_name="old.jpg",
        file_type="image", mime_type="image/jpeg", file_size=123,
        alt_text="legacy", width=10, height=20, uploaded_by=user)

    out = StringIO()
    call_command("migrate_web_media", stdout=out)
    migrated = CommonMedia.objects.filter(workspace=ws, file="media/2020/05/old.jpg")
    assert migrated.count() == 1
    cm = migrated.first()
    assert cm.alt_text == "legacy"
    assert cm.media_type == "image"
    assert "migrated 1" in out.getvalue()

    # Re-running migrates nothing new (matched by workspace + file key).
    call_command("migrate_web_media")
    assert CommonMedia.objects.filter(workspace=ws, file="media/2020/05/old.jpg").count() == 1
