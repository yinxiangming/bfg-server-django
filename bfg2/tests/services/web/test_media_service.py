from io import BytesIO
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from bfg.common.models import User, Workspace
from bfg.web.services.media_service import MediaService


def test_update_media_updates_allowed_fields_only():
    service = MediaService(workspace=SimpleNamespace(id=1), user=None)
    media = SimpleNamespace(workspace_id=1, title="old", alt_text="old", caption="old")
    media.file_type = "image"
    state = {"saved": False}
    media.save = lambda: state.update({"saved": True})

    updated = service.update_media(media, title="new", file_type="video")
    assert updated.title == "new"
    assert updated.file_type == "image"
    assert state["saved"] is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("image_format", "extension", "content_type"),
    [("PNG", "png", "image/png"), ("JPEG", "jpg", "image/jpeg"), ("WEBP", "webp", "image/webp")],
)
def test_upload_image_preserves_dimensions_and_file_bytes(
    settings, tmp_path, image_format, extension, content_type
):
    settings.MEDIA_ROOT = str(tmp_path)
    workspace = Workspace.objects.create(name="Image uploads", slug="image-uploads")
    user = User.objects.create_user(username="image-uploader", password="test-password")
    stream = BytesIO()
    Image.new("RGB", (23, 17), color="#245678").save(stream, format=image_format)
    original = stream.getvalue()
    upload = SimpleUploadedFile(f"sample.{extension}", original, content_type=content_type)

    media = MediaService(workspace=workspace, user=user).upload_media(upload)

    assert (media.width, media.height) == (23, 17)
    assert media.file_type == "image"
    assert media.mime_type == content_type
    assert media.file_size == len(original)
    with media.file.open("rb") as stored:
        assert stored.read() == original


@pytest.mark.django_db
def test_upload_unreadable_image_preserves_existing_metadata_fallback(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    workspace = Workspace.objects.create(name="Image fallback", slug="image-fallback")
    user = User.objects.create_user(username="fallback-uploader", password="test-password")
    upload = SimpleUploadedFile("unreadable.png", b"unreadable-image", content_type="image/png")

    media = MediaService(workspace=workspace, user=user).upload_media(upload)

    assert media.width is None
    assert media.height is None
    assert media.file_size == len(b"unreadable-image")
