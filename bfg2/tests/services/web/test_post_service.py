from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from bfg.web.exceptions import PostNotFound
from bfg.web.models import Post
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


@pytest.fixture
def workspace():
    from bfg.common.services.workspace_service import WorkspaceService

    return WorkspaceService(workspace=None, user=None).create_workspace(
        name="Post Rendering WS", slug="post-rendering-ws",
    )


@pytest.fixture
def author():
    return get_user_model().objects.create_user(
        username="post-author", email="author@test.com", password="x"
    )


@pytest.mark.django_db
def test_get_rendered_post_returns_published_post_in_requested_language(workspace, author):
    Post.objects.create(
        workspace=workspace, slug="hello", language="en", title="Hello",
        content="<p>Hi</p>", status="published", published_at=timezone.now(),
        author=author,
    )

    data = PostService(workspace=workspace, user=None).get_rendered_post("hello", "en")

    assert data["title"] == "Hello"
    assert data["content"] == "<p>Hi</p>"
    assert data["language"] == "en"


@pytest.mark.django_db
def test_get_rendered_post_falls_back_to_english(workspace, author):
    """A shop with only an English post should still resolve /post/hello for a zh-hans visitor."""
    Post.objects.create(
        workspace=workspace, slug="hello", language="en", title="Hello",
        content="<p>Hi</p>", status="published", published_at=timezone.now(),
        author=author,
    )

    data = PostService(workspace=workspace, user=None).get_rendered_post("hello", "zh-hans")

    assert data["title"] == "Hello"


@pytest.mark.django_db
def test_get_rendered_post_rejects_scheduled_post(workspace, author):
    """A post whose publish time has not arrived must not be reachable by guessing its slug."""
    Post.objects.create(
        workspace=workspace, slug="future", language="en", title="Not yet",
        content="<p>Soon</p>", status="published",
        published_at=timezone.now() + timedelta(days=1),
        author=author,
    )

    with pytest.raises(PostNotFound):
        PostService(workspace=workspace, user=None).get_rendered_post("future", "en")


@pytest.mark.django_db
def test_get_rendered_post_rejects_draft(workspace, author):
    Post.objects.create(
        workspace=workspace, slug="draft-post", language="en", title="Draft",
        content="<p>WIP</p>", status="draft", author=author,
    )

    with pytest.raises(PostNotFound):
        PostService(workspace=workspace, user=None).get_rendered_post("draft-post", "en")
