from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bfg.web.services.post_service import PostService


@pytest.mark.django_db
def test_schedule_post_sets_draft_with_publish_time():
    service = PostService(workspace=SimpleNamespace(id=1), user=None)
    post = SimpleNamespace(workspace_id=1, status="published", published_at=None)
    state = {"saved": False}
    post.save = lambda: state.update({"saved": True})
    publish_at = datetime.now() + timedelta(days=1)

    result = service.schedule_post(post, publish_at)
    assert result.status == "draft"
    assert result.published_at == publish_at
    assert state["saved"] is True
