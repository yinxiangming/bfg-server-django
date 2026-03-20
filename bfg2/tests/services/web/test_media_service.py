from types import SimpleNamespace

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
