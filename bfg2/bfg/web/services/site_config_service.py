# -*- coding: utf-8 -*-
"""
Site config load and export for bfg.web.
Load from JSON/YAML config (Site, Theme, Pages, Menus, Product categories) or export workspace site data.
"""

from typing import Any, Dict, List, Optional
from django.utils import timezone
from django.contrib.auth import get_user_model
from bfg.core.services import BaseService
from bfg.common.models import Settings, Workspace
from bfg.common.utils import first_staff_user_for_workspace
from bfg.web.models import Site, Theme, Language, Page, Menu, MenuItem

User = get_user_model()


class SiteConfigService(BaseService):
    """Load site config into workspace or export workspace site data."""

    def load_from_config(
        self,
        config: Dict[str, Any],
        created_by_user=None,
        mode: str = "merge",
        replace_shop_categories: bool = False,
    ) -> Dict[str, Any]:
        """
        Load site config into current workspace.
        config: dict with keys site, theme (optional), pages, menus, categories (optional).
        mode: 'merge' (default) = create/update by slug; 'replace' = delete existing web data then import.
        replace_shop_categories: if True and config contains 'categories', delete workspace ProductCategory rows before import.
        """
        if mode == "replace":
            self._clear_workspace_web_site_data()
        created_by_user = created_by_user or getattr(self, "user", None) or first_staff_user_for_workspace(self.workspace)
        site_data = config.get("site")
        site_obj = self._upsert_site(site_data)
        self._sync_workspace_primary_domain(site_data)
        self._apply_workspace_bootstrap(config)
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
        categories_count = 0
        raw_categories = config.get("categories")
        if raw_categories and isinstance(raw_categories, list):
            lang = (site_data or {}).get("default_language") or "en"
            if replace_shop_categories:
                from bfg.shop.models import ProductCategory

                ProductCategory.objects.filter(workspace=self.workspace).delete()
            categories_count = self._upsert_product_categories(raw_categories, language=lang)
        menus_data = config.get("menus") or config.get("menu") or []
        for m in menus_data:
            self._upsert_menu(m, pages_by_slug)
        return {
            "site": site_obj,
            "theme": theme_obj,
            "pages": list(pages_by_slug.values()),
            "menus_count": len(menus_data),
            "categories_count": categories_count,
        }

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

    def _sync_workspace_primary_domain(self, data: Optional[Dict]) -> None:
        """Set Workspace.domain from site config hostname so middleware resolves without Site lookup."""
        if not data:
            return
        raw = (data.get("domain") or "").strip()
        if not raw:
            return
        host = raw.split(":")[0].strip()[:255]
        if not host or self.workspace.domain == host:
            return
        self.workspace.domain = host
        self.workspace.save(update_fields=["domain", "updated_at"])
        from bfg.common.middleware import invalidate_workspace_cache

        invalidate_workspace_cache(self.workspace)

    def _apply_workspace_bootstrap(self, config: Dict[str, Any]) -> None:
        """Apply optional workspace_bootstrap (name, slug, note) from site-config JSON."""
        wb = config.get("workspace_bootstrap")
        if not wb or not isinstance(wb, dict):
            return
        name = (wb.get("name") or "").strip()
        if name:
            self.workspace.name = name[:255]
            self.workspace.save(update_fields=["name", "updated_at"])
        slug = (wb.get("slug") or "").strip()
        if slug and slug != self.workspace.slug:
            if not Workspace.objects.filter(slug=slug).exclude(pk=self.workspace.pk).exists():
                self.workspace.slug = slug[:100]
                self.workspace.save(update_fields=["slug", "updated_at"])
        note = (wb.get("note") or "").strip()
        if note:
            settings_obj, _ = Settings.objects.get_or_create(
                workspace=self.workspace,
                defaults={"default_language": "en", "default_currency": "NZD"},
            )
            custom = dict(settings_obj.custom_settings or {})
            general = dict(custom.get("general") or {})
            general["workspace_note"] = note
            custom["general"] = general
            settings_obj.custom_settings = custom
            settings_obj.save(update_fields=["custom_settings", "updated_at"])

    def _apply_site_storefront_overrides(self, data: Optional[Dict]) -> None:
        """Map site config to workspace Settings (footer, site name/description for admin/storefront)."""
        if not data:
            return
        settings_obj, _ = Settings.objects.get_or_create(
            workspace=self.workspace,
            defaults={"default_language": "en", "default_currency": "NZD"},
        )
        custom = dict(settings_obj.custom_settings or {})
        general = dict(custom.get("general") or {})

        footer_copyright = (data.get("footer_copyright") or "").strip()
        if footer_copyright:
            general["footer_copyright"] = footer_copyright

        short_name = (data.get("name") or "").strip()
        title = (data.get("site_title") or "").strip()
        site_name_val = short_name or title
        if site_name_val:
            sn = site_name_val[:255]
            settings_obj.site_name = sn
            general["site_name"] = sn

        site_description = (data.get("site_description") or "").strip()
        if site_description:
            settings_obj.site_description = site_description
            general["site_description"] = site_description

        settings_obj.custom_settings = {**custom, "general": general}
        uf = ["custom_settings", "updated_at"]
        if site_name_val:
            uf.insert(0, "site_name")
        if site_description:
            uf.insert(0, "site_description")
        settings_obj.save(update_fields=uf)

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
        page_creator = created_by_user or getattr(self, "user", None) or first_staff_user_for_workspace(self.workspace)
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

    def _upsert_product_categories(self, items: List[Dict[str, Any]], language: str = "en") -> int:
        """Create or update ProductCategory rows from site-config JSON (multi-pass for parent_slug)."""
        from bfg.shop.models import ProductCategory

        category_map: Dict[str, Any] = {}
        remaining: List[Dict[str, Any]] = list(items)
        max_rounds = len(items) + 2
        for _ in range(max_rounds):
            if not remaining:
                break
            next_remaining: List[Dict[str, Any]] = []
            for cat_data in remaining:
                slug = (cat_data.get("slug") or "").strip()
                if not slug:
                    continue
                parent_slug = (cat_data.get("parent_slug") or "").strip() or None
                parent = None
                if parent_slug:
                    parent = category_map.get(parent_slug)
                    if not parent:
                        next_remaining.append(cat_data)
                        continue
                defaults = {
                    "name": cat_data.get("name", slug),
                    "description": (cat_data.get("description") or "")[:2000],
                    "parent": parent,
                    "order": int(cat_data.get("order", 100)),
                    "icon": (cat_data.get("icon") or "")[:50],
                    "is_active": True,
                }
                lang = (cat_data.get("language") or language or "en")[:10]
                obj, _ = ProductCategory.objects.update_or_create(
                    workspace=self.workspace,
                    slug=slug,
                    language=lang,
                    defaults=defaults,
                )
                category_map[slug] = obj
            remaining = next_remaining
        # Orphans: create without parent (invalid parent_slug)
        for cat_data in remaining:
            slug = (cat_data.get("slug") or "").strip()
            if not slug or slug in category_map:
                continue
            lang = (cat_data.get("language") or language or "en")[:10]
            obj, _ = ProductCategory.objects.update_or_create(
                workspace=self.workspace,
                slug=slug,
                language=lang,
                defaults={
                    "name": cat_data.get("name", slug),
                    "description": (cat_data.get("description") or "")[:2000],
                    "parent": None,
                    "order": int(cat_data.get("order", 100)),
                    "icon": (cat_data.get("icon") or "")[:50],
                    "is_active": True,
                },
            )
            category_map[slug] = obj
        return len(category_map)

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
            page_obj = None
            if it.get("page_slug"):
                page_obj = pages_by_slug.get(it["page_slug"])
                url = f"/{it['page_slug']}" if page_obj else (url or f"/{it['page_slug']}")
            MenuItem.objects.create(
                menu=menu,
                title=it.get("title", "Link"),
                url=url or "/",
                page=page_obj,
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
