from types import SimpleNamespace

from django.contrib.auth import get_user_model

from bfg.common.models import Workspace, WorkspaceDomain
from bfg.web.models import Category, Post
from bfg.web.services.site_config_service import SiteConfigService


def test_upsert_site_returns_none_for_empty_payload():
    service = SiteConfigService(workspace=SimpleNamespace(id=1), user=None)
    assert service._upsert_site(None) is None


def test_sync_workspace_custom_domain_upserts_workspace_domain(db):
    workspace = SimpleNamespace(id=1)
    workspace.pk = 1
    workspace.domains = WorkspaceDomain.objects.none()
    service = SiteConfigService(workspace=workspace, user=None)

    from bfg.common.models import Workspace
    real_workspace = Workspace.objects.create(name="Site WS", slug="site-ws", is_active=True)
    service.workspace = real_workspace

    service._sync_workspace_custom_domain({"domain": "https://Shop.Example.test:443"})

    domain = WorkspaceDomain.objects.get(workspace=real_workspace, hostname="shop.example.test")
    assert domain.kind == WorkspaceDomain.KIND_CUSTOM
    assert domain.is_primary is False
    assert domain.verification_status == WorkspaceDomain.VERIFICATION_PENDING


def test_load_config_imports_content_categories_and_posts_idempotently(db):
    workspace = Workspace.objects.create(name="Content WS", slug="content-ws", is_active=True)
    user = get_user_model().objects.create_user(username="content-author", email="content@example.test")
    service = SiteConfigService(workspace=workspace, user=user)
    config = {
        "content_categories": [{"slug": "news", "name": "News", "language": "en", "content_type_name": "post"}],
        "posts": [{
            "slug": "hello-world",
            "title": "Hello world",
            "language": "en",
            "content": "<p>Welcome</p>",
            "category_slug": "news",
            "featured_image": "media/1/news/hero.jpg",
            "status": "published",
        }],
    }

    first = service.load_from_config(config, created_by_user=user)
    second = service.load_from_config(config, created_by_user=user)

    assert first["content_categories_count"] == 1
    assert first["posts_count"] == 1
    assert second["posts_count"] == 1
    assert Category.objects.filter(workspace=workspace, slug="news").count() == 1
    post = Post.objects.get(workspace=workspace, slug="hello-world", language="en")
    assert post.category.slug == "news"
    assert post.featured_image.name == "media/1/news/hero.jpg"
