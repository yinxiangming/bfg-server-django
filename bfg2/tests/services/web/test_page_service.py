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
