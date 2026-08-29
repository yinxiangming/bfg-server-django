from bfg.web.services.page_service import (
    get_page_cache_ttl,
    get_page_rendered_cache_key,
    is_home_slug,
    is_page_cacheable,
)


def test_page_cache_key_and_home_helpers():
    assert get_page_rendered_cache_key(7, "home", "en") == "page_rendered:7:home:en"
    assert is_home_slug("home") is True
    assert is_page_cacheable("category-news") is True


def test_page_cache_ttl_non_cacheable_slug_is_zero():
    assert get_page_cache_ttl("product-detail") == 0


def test_home_promo_blocks_leave_an_unfeatured_category_grid_unresolved(db, monkeypatch):
    """An empty campaign must not stamp resolvedData=[] onto the grid.

    The clients treat *any* resolvedData list as the final answer, so an empty one
    renders an empty grid instead of falling back to the workspace's own categories.
    """
    from bfg.common.services.workspace_service import WorkspaceService
    from bfg.marketing import promo_views
    from bfg.web.services.page_service import PageService

    workspace = WorkspaceService(workspace=None, user=None).create_workspace(
        name="Promo WS", slug="promo-ws",
    )
    # _resolve_home_promo_blocks imports this inside the function, so the patch has
    # to land on the source module rather than on page_service.
    monkeypatch.setattr(
        promo_views, "get_promo_available",
        lambda *a, **k: {"slides": [], "featured_categories": []},
        raising=False,
    )

    blocks = [{"type": "category_grid_v1", "data": {"source": "promo"}}]
    resolved = PageService(workspace=workspace, user=None)._resolve_home_promo_blocks(blocks, None)

    assert "resolvedData" not in resolved[0]


def test_home_promo_blocks_localise_with_zh_hans_not_zh(db, monkeypatch):
    """Carousel copy is keyed the way both clients resolve their locale."""
    from bfg.common.services.workspace_service import WorkspaceService
    from bfg.marketing import promo_views
    from bfg.web.services.page_service import PageService

    workspace = WorkspaceService(workspace=None, user=None).create_workspace(
        name="Promo WS 2", slug="promo-ws-2",
    )
    # _resolve_home_promo_blocks imports this inside the function, so the patch has
    # to land on the source module rather than on page_service.
    monkeypatch.setattr(
        promo_views, "get_promo_available",
        lambda *a, **k: {
            "slides": [{"title": "T", "subtitle": "S", "image": "i.png",
                        "link_url": "/x", "order": 0}],
            "featured_categories": [],
        },
        raising=False,
    )

    blocks = [{"type": "hero_carousel_v1", "data": {"source": "promo"}}]
    resolved = PageService(workspace=workspace, user=None)._resolve_home_promo_blocks(blocks, None)

    slide = resolved[0]["data"]["slides"][0]
    for key in ("title", "subtitle", "buttonText"):
        assert "zh-hans" in slide[key], key
        assert "zh" not in slide[key], key
    assert slide["buttonText"]["zh-hans"] == "立即选购"
