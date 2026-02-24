# -*- coding: utf-8 -*-
"""
Site config load and export for bfg.web.
Load from JSON/YAML config (Site, Theme, Pages, Menus) or export current workspace site data.
"""

from typing import Any, Dict, List, Optional
from django.utils import timezone
from django.contrib.auth import get_user_model
from bfg.core.services import BaseService
from bfg.common.models import Settings
from bfg.web.models import Site, Theme, Language, Page, Menu, MenuItem

User = get_user_model()


class SiteConfigService(BaseService):
    """Load site config into workspace or export workspace site data."""

    def load_from_config(
        self,
        config: Dict[str, Any],
        created_by_user=None,
        mode: str = "merge",
    ) -> Dict[str, Any]:
        """
        Load site config into current workspace.
        config: dict with keys site, theme (optional), pages, menus.
        mode: 'merge' (default) = create/update by slug; 'replace' = delete existing web data then import.
        """
        if mode == "replace":
            self._clear_workspace_web_site_data()
        created_by_user = created_by_user or getattr(self, "user", None) or User.objects.filter(is_superuser=True).first()
        site_data = config.get("site")
        site_obj = self._upsert_site(site_data)
        self._apply_site_storefront_overrides(site_data)
        theme_obj = self._upsert_theme(config.get("theme")) if config.get("theme") else None
        if site_obj and theme_obj:
            site_obj.theme = theme_obj
            site_obj.save(update_fields=["theme", "updated_at"])
        pages_by_slug = {}
        for p in config.get("pages", []):
            page = self._upsert_page(p, created_by_user or self.user, pages_by_slug)
            if page:
                pages_by_slug[page.slug] = page
        menus_data = config.get("menus") or config.get("menu") or []
        for m in menus_data:
            self._upsert_menu(m, pages_by_slug)
        return {"site": site_obj, "theme": theme_obj, "pages": list(pages_by_slug.values()), "menus_count": len(menus_data)}

    def _clear_workspace_web_site_data(self) -> None:
        """Remove Site, Menu/MenuItem, Page for this workspace (Theme/Language kept)."""
        MenuItem.objects.filter(menu__workspace=self.workspace).delete()
        Menu.objects.filter(workspace=self.workspace).delete()
        Page.objects.filter(workspace=self.workspace).delete()
        Site.objects.filter(workspace=self.workspace).delete()

    def _upsert_site(self, data: Optional[Dict]) -> Optional[Site]:
        if not data:
            return None
        domain = (data.get("domain") or "").strip() or "xmart-sales.local"
        site, created = Site.objects.get_or_create(
            workspace=self.workspace,
            domain=domain,
            defaults={
                "name": data.get("name", "XMart Sales"),
                "site_title": data.get("site_title", "XMart"),
                "site_description": data.get("site_description", ""),
                "default_language": data.get("default_language", "zh-hans"),
                "languages": data.get("languages", ["zh-hans", "en"]),
                "is_active": True,
                "is_default": True,
            },
        )
        if not created:
            site.name = data.get("name", site.name)
            site.site_title = data.get("site_title", site.site_title)
            site.site_description = data.get("site_description", site.site_description)
            site.default_language = data.get("default_language", site.default_language)
            site.languages = data.get("languages", site.languages)
            site.save(update_fields=["name", "site_title", "site_description", "default_language", "languages", "updated_at"])
        return site

    def _apply_site_storefront_overrides(self, data: Optional[Dict]) -> None:
        """Apply site config keys that map to workspace Settings (e.g. footer_copyright)."""
        if not data:
            return
        footer_copyright = (data.get("footer_copyright") or "").strip()
        if not footer_copyright:
            return
        settings_obj, _ = Settings.objects.get_or_create(
            workspace=self.workspace,
            defaults={"default_language": "en", "default_currency": "NZD"},
        )
        custom = dict(settings_obj.custom_settings or {})
        general = dict(custom.get("general") or {})
        general["footer_copyright"] = footer_copyright
        custom["general"] = general
        settings_obj.custom_settings = custom
        settings_obj.save(update_fields=["custom_settings", "updated_at"])

    def _upsert_theme(self, data: Optional[Dict]) -> Optional[Theme]:
        if not data:
            return None
        code = (data.get("code") or "xmart").strip()
        theme, created = Theme.objects.get_or_create(
            workspace=self.workspace,
            code=code,
            defaults={
                "name": data.get("name", "XMart Theme"),
                "template_path": data.get("template_path", "themes/default"),
                "primary_color": data.get("primary_color", "#2563eb"),
                "secondary_color": data.get("secondary_color", "#0b1120"),
                "is_active": True,
            },
        )
        if not created:
            theme.name = data.get("name", theme.name)
            theme.template_path = data.get("template_path", theme.template_path)
            theme.primary_color = data.get("primary_color", theme.primary_color)
            theme.secondary_color = data.get("secondary_color", theme.secondary_color)
            theme.save(update_fields=["name", "template_path", "primary_color", "secondary_color", "updated_at"])
        return theme

    def _upsert_page(
        self,
        data: Dict,
        created_by_user,
        pages_by_slug: Dict[str, Page],
    ) -> Optional[Page]:
        slug = (data.get("slug") or "").strip()
        if not slug:
            return None
        language = data.get("language", "zh-hans")
        parent = None
        if data.get("parent_slug"):
            parent = pages_by_slug.get(data["parent_slug"])
        blocks = data.get("blocks", [])
        if not blocks and data.get("content"):
            blocks = [{"id": "block_content", "type": "text_block_v1", "settings": {"align": "left", "maxWidth": "800px"}, "data": {"content": {"en": data["content"], "zh-hans": data.get("content_zh") or data["content"]}}}]
        defaults = {
            "title": data.get("title", slug),
            "content": data.get("content", ""),
            "template": data.get("template", "default"),
            "status": data.get("status", "published"),
            "language": language,
            "blocks": blocks,
            "meta_title": data.get("meta_title", ""),
            "meta_description": data.get("meta_description", ""),
            "order": data.get("order", 100),
            "parent": parent,
        }
        page_creator = created_by_user or getattr(self, "user", None) or User.objects.filter(is_superuser=True).first()
        if page_creator:
            defaults["created_by"] = page_creator
        if defaults["status"] == "published":
            defaults.setdefault("published_at", timezone.now())
        page, created = Page.objects.update_or_create(
            workspace=self.workspace,
            slug=slug,
            language=language,
            defaults=defaults,
        )
        pages_by_slug[slug] = page
        return page

    def _upsert_menu(self, data: Dict, pages_by_slug: Dict[str, Page]) -> None:
        slug = (data.get("slug") or "menu").strip()
        language = data.get("language", "zh-hans")
        menu, _ = Menu.objects.get_or_create(
            workspace=self.workspace,
            slug=slug,
            language=language,
            defaults={
                "name": data.get("name", slug),
                "location": data.get("location", "header"),
                "is_active": True,
            },
        )
        menu.name = data.get("name", menu.name)
        menu.location = data.get("location", menu.location)
        menu.save(update_fields=["name", "location"])
        MenuItem.objects.filter(menu=menu).delete()
        items = data.get("items", [])
        for i, it in enumerate(items):
            url = (it.get("url") or "").strip()
            if it.get("page_slug"):
                page = pages_by_slug.get(it["page_slug"])
                url = f"/{it['page_slug']}" if page else url or f"/{it['page_slug']}"
            MenuItem.objects.create(
                menu=menu,
                title=it.get("title", "Link"),
                url=url or "/",
                order=it.get("order", i + 1),
                is_active=True,
            )

    def export_site(self, include_theme: bool = True) -> Dict[str, Any]:
        """Export current workspace site data (Site, Theme, Pages, Menus) as JSON-serializable dict."""
        sites = list(Site.objects.filter(workspace=self.workspace).select_related("theme"))
        site = sites[0] if sites else None
        if not site:
            return {"version": "1.0", "exported_at": timezone.now().isoformat(), "site": None, "pages": [], "menus": []}
        out = {
            "version": "1.0",
            "exported_at": timezone.now().isoformat(),
            "site": {
                "name": site.name,
                "domain": site.domain,
                "site_title": site.site_title,
                "site_description": site.site_description or "",
                "default_language": site.default_language,
                "languages": list(site.languages) if site.languages else [site.default_language],
            },
            "pages": [],
            "menus": [],
        }
        if include_theme and site.theme:
            out["theme"] = {
                "code": site.theme.code,
                "name": site.theme.name,
                "template_path": site.theme.template_path,
                "primary_color": site.theme.primary_color,
                "secondary_color": site.theme.secondary_color,
            }
        else:
            out["theme"] = None
        for page in Page.objects.filter(workspace=self.workspace).order_by("order", "title"):
            out["pages"].append({
                "slug": page.slug,
                "title": page.title,
                "language": page.language,
                "status": page.status,
                "template": page.template,
                "blocks": page.blocks,
                "meta_title": page.meta_title or "",
                "meta_description": page.meta_description or "",
                "order": page.order,
                "parent_slug": page.parent.slug if page.parent_id else None,
            })
        for menu in Menu.objects.filter(workspace=self.workspace).prefetch_related("items"):
            items = [{"title": i.title, "url": i.url, "order": i.order} for i in menu.items.filter(is_active=True).order_by("order")]
            out["menus"].append({
                "slug": menu.slug,
                "name": menu.name,
                "location": menu.location,
                "language": menu.language,
                "items": items,
            })
        return out
