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


# ─── MEDIA_URL joining (S3 / CDN) ────────────────────────────────────────
# media_file_url_for_serializer builds URLs as MEDIA_URL + file.name rather than
# calling file.url. It used to collapse every '//' in the result, which is a no-op
# for a relative MEDIA_URL but destroys the scheme of an absolute one.

def test_media_url_join_keeps_scheme_on_absolute_cdn_url(db, settings):
    settings.MEDIA_URL = "https://files.surlex.co.nz/nexus/prod/"
    ws, _ = _workspace("cdn")
    m = CommonMedia.objects.create(workspace=ws, media_type="image")
    m.file.name = "media/3/led-ring-module.png"
    m.save()
    assert media_file_url_for_serializer(m) == (
        "https://files.surlex.co.nz/nexus/prod/media/3/led-ring-module.png")


def test_media_url_join_unchanged_for_relative_media_url(db, settings):
    # Local/filesystem behaviour must be byte-identical to before the fix.
    settings.MEDIA_URL = "/media/"
    ws, _ = _workspace("rel")
    m = CommonMedia.objects.create(workspace=ws, media_type="image")
    m.file.name = "seed_images/store/x.png"
    m.save()
    assert media_file_url_for_serializer(m) == "/media/seed_images/store/x.png"


def test_media_url_join_tolerates_leading_slash_in_key(db, settings):
    settings.MEDIA_URL = "https://files.surlex.co.nz/nexus/uat/"
    ws, _ = _workspace("slash")
    m = CommonMedia.objects.create(workspace=ws, media_type="image")
    m.file.name = "/media/3/x.png"
    m.save()
    # Exactly one separator at the join, no empty path segment.
    assert media_file_url_for_serializer(m) == (
        "https://files.surlex.co.nz/nexus/uat/media/3/x.png")


def test_s3_storage_url_includes_location_prefix():
    """Pin the django-storages contract config.settings.MEDIA_URL mirrors.

    S3Storage.url() prepends the ``location`` prefix itself. config/settings.py
    therefore has to append AWS_LOCATION to MEDIA_URL by hand, or the two ways of
    addressing a file (file.url vs MEDIA_URL + file.name) disagree by one path
    segment and every image 404s.
    """
    from storages.backends.s3 import S3Storage

    storage = S3Storage(
        bucket_name="surlex",
        location="nexus/prod",
        custom_domain="files.surlex.co.nz",
        querystring_auth=False,
    )
    assert storage.url("media/3/x.png") == (
        "https://files.surlex.co.nz/nexus/prod/media/3/x.png")
