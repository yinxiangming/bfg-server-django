# -*- coding: utf-8 -*-
"""
Apply a country/industry template to a workspace, non-destructively.

The rule the whole module is built around: **never overwrite something the user
has already touched.** ``SiteConfigService`` is happy to ``update_or_create``
every page it is given and to delete a menu's items before rebuilding them —
correct for importing a curated site config, wrong for a wizard someone may run
twice. So the plan is filtered down to what is genuinely missing *before* it is
handed over, and the filtering is what ``preview`` shows.
"""

from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from bfg.core.services import BaseService

from .blocks import home_page_blocks
from .catalog import DEFAULT_COUNTRY, DEFAULT_INDUSTRY
from .checklist import evaluate
from .templates import build_plan

#: ``action`` values in the change list the API returns.
DEFAULT_THEME_CODE = 'store'

CREATE = 'create'
UPDATE = 'update'
KEEP = 'keep'


class OnboardingService(BaseService):
    """Read the checklist, and write the parts of it a template can write."""

    # ── read ─────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        settings_obj = self._settings()
        return dict((settings_obj.custom_settings or {}).get('onboarding') or {})

    def status(self) -> Dict[str, Any]:
        return evaluate(self.workspace, self.get_state())

    # ── plan ─────────────────────────────────────────────────────────────

    def build(self, country: str = '', industry: str = '', overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """The rendered template for a pick, with the workspace's own values folded in."""
        overrides = overrides or {}
        settings_obj = self._settings()
        state = self.get_state()

        country = (country or state.get('country') or getattr(settings_obj, 'country', '') or DEFAULT_COUNTRY)
        industry = (industry or state.get('industry') or DEFAULT_INDUSTRY)

        general = (settings_obj.custom_settings or {}).get('general') or {}
        site_name = (
            overrides.get('site_name')
            or settings_obj.site_name
            or general.get('site_name')
            or self.workspace.name
        )
        return build_plan(
            country_code=country,
            industry_key=industry,
            site_name=site_name,
            languages=overrides.get('languages'),
            default_language=overrides.get('default_language', ''),
            currency=overrides.get('currency', ''),
            timezone=overrides.get('timezone', ''),
            contact_email=overrides.get('contact_email') or settings_obj.contact_email or '',
            contact_phone=overrides.get('contact_phone') or settings_obj.contact_phone or '',
            address=overrides.get('address') or self._workspace_address(),
            year=timezone.now().year,
        )

    def preview(self, country: str = '', industry: str = '', overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """What ``apply`` would do, computed without writing anything."""
        plan = self.build(country, industry, overrides)
        return {
            'country': plan['country'],
            'industry': plan['industry'],
            'settings': plan['settings'],
            'tax': plan['tax'],
            'changes': self._diff(plan),
        }

    # ── write ────────────────────────────────────────────────────────────

    def apply(self, country: str = '', industry: str = '', overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create everything the workspace is missing, leave everything else alone."""
        plan = self.build(country, industry, overrides)
        changes: List[Dict[str, str]] = []

        with transaction.atomic():
            changes += self._apply_settings(plan)
            changes += self._apply_currency(plan)
            changes += self._apply_tax(plan)
            changes += self._apply_store(plan)
            changes += self._apply_delivery(plan)
            changes += self._apply_shop_settings(plan)
            changes += self._apply_extension_settings(plan)
            changes += self._apply_site(plan)
            changes += self._apply_site_content(plan)
            self._record_state(plan)

        self._invalidate_caches()
        return {
            'country': plan['country'],
            'industry': plan['industry'],
            'changes': changes,
            'status': self.status(),
        }

    def skip_item(self, item_key: str, skipped: bool = True) -> Dict[str, Any]:
        """Mark a checklist item as a deliberate non-decision, or undo that."""
        from .checklist import items_by_key

        if item_key not in items_by_key():
            raise ValueError(f'Unknown checklist item: {item_key}')
        state = self.get_state()
        current = set(state.get('skipped') or [])
        current.add(item_key) if skipped else current.discard(item_key)
        state['skipped'] = sorted(current)
        self._save_state(state)
        return self.status()

    def dismiss(self, dismissed: bool = True) -> Dict[str, Any]:
        state = self.get_state()
        state['dismissed'] = bool(dismissed)
        self._save_state(state)
        return self.status()

    # ── diff ─────────────────────────────────────────────────────────────

    def _diff(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        """Same filtering the ``_apply_*`` methods do, reported instead of run."""
        from bfg.delivery.models import DeliveryZone, Warehouse
        from bfg.finance.models import Currency, TaxRate
        from bfg.shop.models import ProductCategory, Store

        settings_obj = self._settings()
        changes: List[Dict[str, str]] = []

        for field, value in plan['settings'].items():
            current = getattr(settings_obj, field, None)
            # Mirrors _apply_settings exactly, including its one exception: a
            # shop name the user already chose is never replaced, so preview
            # must not promise that it will be.
            keep = (not value) or current == value or (field == 'site_name' and settings_obj.site_name)
            changes.append(self._change(KEEP if keep else UPDATE, 'settings', field,
                                        str(current if keep else value)))

        code = plan['currency']['code']
        changes.append(self._change(
            KEEP if Currency.objects.filter(code=code, is_active=True).exists() else CREATE,
            'currency', code, code))

        tax = plan['tax']
        changes.append(self._change(
            KEEP if TaxRate.objects.filter(workspace=self.workspace, is_active=True).exists() else CREATE,
            'tax_rate', tax['name'], f"{tax['name']} {tax['rate']}%"))

        store = plan['store']
        changes.append(self._change(
            KEEP if Store.all_objects.filter(workspace=self.workspace, code=store['code']).exists() else CREATE,
            'store', store['code'], store['name']))

        if not self._delivery_skipped(plan):
            delivery = plan['delivery']
            changes.append(self._change(
                KEEP if Warehouse.all_objects.filter(
                    workspace=self.workspace, code=delivery['warehouse_code']).exists() else CREATE,
                'warehouse', delivery['warehouse_code'], delivery['warehouse_name']))
            changes.append(self._change(
                KEEP if DeliveryZone.objects.filter(
                    workspace=self.workspace, code=delivery['zone_code']).exists() else CREATE,
                'zone', delivery['zone_code'], delivery['zone_name']))

        existing_categories = set(
            ProductCategory.all_objects.filter(workspace=self.workspace).values_list('slug', 'language')
        )
        for item in plan['categories']:
            action = KEEP if (item['slug'], item['language']) in existing_categories else CREATE
            changes.append(self._change(action, 'category', f"{item['slug']}:{item['language']}", item['name']))

        has_author = self._page_author() is not None
        custom = dict(settings_obj.custom_settings or {})
        changes.append(self._change(
            KEEP if custom.get('shop') else CREATE, 'shop_settings', 'shop',
            ', '.join(f'{k}={v}' for k, v in sorted(plan['shop_settings'].items()))))

        from .extensions import custom_settings_patch

        for key, value in custom_settings_patch(plan, self.workspace).items():
            existing = custom.get(key)
            settled = existing is not None and (
                not isinstance(value, dict) or all(k in existing for k in value)
            )
            changes.append(self._change(KEEP if settled else CREATE, 'extension_settings', key, str(key)))

        hostname = self._workspace_hostname()
        if not hostname:
            changes.append(self._change(KEEP, 'site', 'site', 'no hostname connected yet'))
        else:
            from bfg.web.models import Site

            changes.append(self._change(
                KEEP if Site.all_objects.filter(workspace=self.workspace, domain=hostname).exists() else CREATE,
                'site', hostname, hostname))

        for page in self._pages_with_home(plan):
            action = CREATE if (has_author and self._page_missing(page)) else KEEP
            changes.append(self._change(action, 'page', f"{page['slug']}:{page['language']}", page['title']))

        for menu in plan['menus']:
            action = CREATE if self._menu_empty(menu) else KEEP
            changes.append(self._change(action, 'menu', f"{menu['slug']}:{menu['language']}", menu['name']))

        return changes

    @staticmethod
    def _change(action: str, kind: str, key: str, label: str) -> Dict[str, str]:
        return {'action': action, 'kind': kind, 'key': key, 'label': label}

    # ── apply steps ──────────────────────────────────────────────────────

    def _apply_settings(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        """Locale and branding. Blank fields are filled; set ones are respected.

        Exception: the fields the user explicitly chose in the wizard (country,
        currency, language, timezone) *are* overwritten — picking New Zealand
        and then seeing USD would make the wizard look broken.
        """
        settings_obj = self._settings()
        changes = []
        for field, value in plan['settings'].items():
            if not value:
                continue
            if field == 'site_name' and settings_obj.site_name:
                changes.append(self._change(KEEP, 'settings', field, settings_obj.site_name))
                continue
            if getattr(settings_obj, field, None) == value:
                changes.append(self._change(KEEP, 'settings', field, str(value)))
                continue
            setattr(settings_obj, field, value)
            changes.append(self._change(UPDATE, 'settings', field, str(value)))

        custom = dict(settings_obj.custom_settings or {})
        general = dict(custom.get('general') or {})
        for field in ('default_language', 'default_currency', 'default_timezone', 'site_name',
                      'contact_email', 'contact_phone'):
            general[field] = getattr(settings_obj, field, '') or general.get(field, '')
        custom['general'] = general
        settings_obj.custom_settings = custom
        settings_obj.save()
        return changes

    def _apply_currency(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        from bfg.finance.models import Currency

        profile = plan['currency']
        code = profile['code']
        if not code:
            return []
        if Currency.objects.filter(code=code, is_active=True).exists():
            return [self._change(KEEP, 'currency', code, code)]
        # Global row, not per workspace: reactivating a disabled one is right.
        Currency.objects.update_or_create(
            code=code,
            defaults={
                'name': profile['name'],
                'symbol': profile['symbol'],
                'decimal_places': profile['decimal_places'],
                'is_active': True,
            },
        )
        return [self._change(CREATE, 'currency', code, f"{code} {profile['symbol']}")]

    def _apply_tax(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        from bfg.finance.models import TaxRate

        tax = plan['tax']
        # Any existing rate means someone has thought about this already; a
        # second "GST 15%" row would quietly double-charge.
        if TaxRate.objects.filter(workspace=self.workspace, is_active=True).exists():
            return [self._change(KEEP, 'tax_rate', tax['name'], tax['name'])]
        TaxRate.objects.create(
            workspace=self.workspace,
            name=tax['name'],
            rate=tax['rate'],
            country=tax['country'],
            is_active=True,
        )
        return [self._change(CREATE, 'tax_rate', tax['name'], f"{tax['name']} {tax['rate']}%")]

    def _apply_store(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        from bfg.shop.models import Store

        store = plan['store']
        if Store.all_objects.filter(workspace=self.workspace, is_active=True).exists():
            return [self._change(KEEP, 'store', store['code'], store['name'])]
        Store.all_objects.create(
            workspace=self.workspace, name=store['name'], code=store['code'], is_active=True,
        )
        return [self._change(CREATE, 'store', store['code'], store['name'])]

    def _apply_delivery(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        from bfg.delivery.models import DeliveryZone, Warehouse

        if self._delivery_skipped(plan):
            return []
        delivery = plan['delivery']
        changes = []

        if Warehouse.all_objects.filter(workspace=self.workspace, is_active=True).exists():
            changes.append(self._change(KEEP, 'warehouse', delivery['warehouse_code'], delivery['warehouse_name']))
        else:
            # Address is required but unknowable here; the checklist keeps
            # pointing at the warehouse screen until a human fills it in.
            Warehouse.all_objects.create(
                workspace=self.workspace,
                name=delivery['warehouse_name'],
                code=delivery['warehouse_code'],
                address_line1='',
                city='',
                postal_code='',
                country=plan['settings']['country'],
                is_active=True,
            )
            changes.append(self._change(CREATE, 'warehouse', delivery['warehouse_code'], delivery['warehouse_name']))

        if DeliveryZone.objects.filter(workspace=self.workspace, is_active=True).exists():
            changes.append(self._change(KEEP, 'zone', delivery['zone_code'], delivery['zone_name']))
        else:
            DeliveryZone.objects.create(
                workspace=self.workspace,
                name=delivery['zone_name'],
                code=delivery['zone_code'],
                countries=delivery['zone_countries'],
                is_active=True,
            )
            changes.append(self._change(CREATE, 'zone', delivery['zone_code'], delivery['zone_name']))
        return changes

    def _apply_shop_settings(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        """Storefront display policy — only when the workspace has none of its own."""
        settings_obj = self._settings()
        custom = dict(settings_obj.custom_settings or {})
        if custom.get('shop'):
            return [self._change(KEEP, 'shop_settings', 'shop', 'existing')]
        custom['shop'] = dict(plan['shop_settings'])
        settings_obj.custom_settings = custom
        settings_obj.save(update_fields=['custom_settings', 'updated_at'])
        return [self._change(CREATE, 'shop_settings', 'shop', ', '.join(
            f'{k}={v}' for k, v in sorted(plan['shop_settings'].items())))]

    def _apply_extension_settings(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        """Config the installed apps can derive from the country/industry pick.

        Only fills sub-keys the workspace has not set: an app pre-filling
        ``plugins.address_lookup`` from the chosen country must not clear the
        API key someone pasted in last week.
        """
        from .extensions import custom_settings_patch

        patch = custom_settings_patch(plan, self.workspace)
        if not patch:
            return []

        settings_obj = self._settings()
        custom = dict(settings_obj.custom_settings or {})
        changes: List[Dict[str, str]] = []

        for key, value in patch.items():
            existing = custom.get(key)
            if isinstance(value, dict) and isinstance(existing, dict):
                fresh = {k: v for k, v in value.items() if k not in existing}
                if not fresh:
                    changes.append(self._change(KEEP, 'extension_settings', key, 'already configured'))
                    continue
                custom[key] = {**existing, **fresh}
                changes.append(self._change(CREATE, 'extension_settings', key,
                                            ', '.join(sorted(fresh))))
            elif existing is None:
                custom[key] = value
                changes.append(self._change(CREATE, 'extension_settings', key, str(value)))
            else:
                changes.append(self._change(KEEP, 'extension_settings', key, 'already configured'))

        if any(change['action'] == CREATE for change in changes):
            settings_obj.custom_settings = custom
            settings_obj.save(update_fields=['custom_settings', 'updated_at'])
        return changes

    def _apply_site(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        """The ``web.Site`` row that decides the storefront's language and theme.

        Site.domain is globally unique, so this can only run once the workspace
        has a hostname of its own — inventing one would collide with whoever
        registers it for real later. Without a hostname the checklist keeps
        pointing at the domain step instead.
        """
        from bfg.web.models import Site, Theme

        hostname = self._workspace_hostname()
        if not hostname:
            return [self._change(KEEP, 'site', 'site', 'no hostname connected yet')]
        if Site.all_objects.filter(workspace=self.workspace, domain=hostname).exists():
            return [self._change(KEEP, 'site', hostname, hostname)]

        settings = plan['settings']
        name = settings['site_name'] or self.workspace.name
        theme, _created = Theme.objects.get_or_create(
            workspace=self.workspace, code=DEFAULT_THEME_CODE,
            defaults={'name': f'{name} {DEFAULT_THEME_CODE}',
                      'template_path': f'themes/{DEFAULT_THEME_CODE}', 'is_active': True},
        )
        site = Site.all_objects.create(
            workspace=self.workspace, domain=hostname, name=name, site_title=name,
            default_language=settings['default_language'],
            languages=settings['supported_languages'],
            theme=theme, is_active=True, is_default=True,
        )
        # One default Site per workspace, or the config endpoint picks arbitrarily.
        Site.all_objects.filter(workspace=self.workspace, is_default=True).exclude(pk=site.pk).update(is_default=False)
        return [self._change(CREATE, 'site', hostname, hostname)]

    def _apply_site_content(self, plan: Dict[str, Any]) -> List[Dict[str, str]]:
        """Pages, menus and categories — filtered to what is genuinely absent.

        Handing the unfiltered plan to ``SiteConfigService`` would republish a
        page the user rewrote and wipe a menu they reordered.
        """
        from bfg.shop.models import ProductCategory
        from bfg.web.services import SiteConfigService

        author = self._page_author()
        # ``Page.created_by`` is NOT NULL. A workspace with no staff and no
        # acting user (a script, a half-provisioned tenant) still gets its
        # categories and menus rather than a 500.
        pages = [p for p in self._pages_with_home(plan) if self._page_missing(p)] if author else []
        menus = [m for m in plan['menus'] if self._menu_empty(m)]
        existing_categories = set(
            ProductCategory.all_objects.filter(workspace=self.workspace).values_list('slug', 'language')
        )
        categories = [
            c for c in plan['categories'] if (c['slug'], c['language']) not in existing_categories
        ]

        changes = [self._change(CREATE, 'page', f"{p['slug']}:{p['language']}", p['title']) for p in pages]
        if not author:
            changes.append(self._change(KEEP, 'page', 'all', 'no author available — add a staff member first'))
        changes += [self._change(CREATE, 'menu', f"{m['slug']}:{m['language']}", m['name']) for m in menus]
        changes += [self._change(CREATE, 'category', f"{c['slug']}:{c['language']}", c['name']) for c in categories]
        if not (pages or menus or categories):
            return [self._change(KEEP, 'content', 'pages', 'nothing missing')]

        # No `site` key on purpose: SiteConfigService._upsert_site falls back to
        # a placeholder hostname and registers it as this workspace's primary
        # verified domain, which would hijack tenant routing.
        config: Dict[str, Any] = {}
        if pages:
            config['pages'] = pages
        if menus:
            config['menus'] = menus
        if categories:
            config['categories'] = categories

        SiteConfigService(workspace=self.workspace, user=author).load_from_config(
            config, created_by_user=author, mode='merge',
        )
        return changes

    # ── helpers ──────────────────────────────────────────────────────────

    def _settings(self):
        from bfg.common.models import Settings
        from bfg.common.constants import DEFAULT_CURRENCY_CODE

        settings_obj, _ = Settings.objects.get_or_create(
            workspace=self.workspace,
            defaults={
                'default_language': 'en',
                'default_currency': DEFAULT_CURRENCY_CODE,
                'default_timezone': 'UTC',
                'supported_languages': ['en'],
                'features': {},
            },
        )
        return settings_obj

    def _workspace_address(self) -> str:
        """One-line postal address for the legal-page placeholders, if there is one."""
        from bfg.common.models import Address

        address = Address.all_objects.filter(workspace=self.workspace).order_by('-is_default', 'id').first()
        if not address:
            return ''
        parts = [address.address_line1, address.address_line2, address.city,
                 address.state, address.postal_code, address.country]
        return ', '.join(part for part in parts if part)

    def _workspace_hostname(self) -> str:
        """The workspace's own hostname: its custom domain, else its subdomain."""
        from bfg.common.models import WorkspaceDomain

        domains = WorkspaceDomain.objects.filter(workspace=self.workspace)
        primary = domains.filter(
            kind=WorkspaceDomain.KIND_CUSTOM,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ).order_by('-is_primary', 'id').first()
        fallback = domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).first()
        chosen = primary or fallback
        return chosen.hostname if chosen else ''

    def _pages_with_home(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Template pages plus a home page per language.

        Home is not in ``base.json`` because it is blocks, not prose — the same
        layout ``provision_workspace --seed-home`` publishes.
        """
        site_name = plan['settings']['site_name'] or self.workspace.name
        home = [
            {
                'slug': 'home',
                'language': language,
                'status': 'published',
                'order': 1,
                'title': site_name,
                'blocks': home_page_blocks(),
            }
            for language in plan['settings']['supported_languages']
        ]
        return home + list(plan['pages'])

    def _page_author(self):
        """Who a generated page is attributed to; None when nobody can be."""
        from django.contrib.auth import get_user_model
        from bfg.common.utils import first_staff_user_for_workspace

        if self.user is not None and getattr(self.user, 'is_authenticated', False):
            return self.user
        staff = first_staff_user_for_workspace(self.workspace)
        if staff:
            return staff
        return get_user_model().objects.filter(is_superuser=True).order_by('pk').first()

    def _page_missing(self, page: Dict[str, Any]) -> bool:
        from bfg.web.models import Page

        return not Page.objects.filter(
            workspace=self.workspace, slug=page['slug'], language=page['language'],
        ).exists()

    def _menu_empty(self, menu: Dict[str, Any]) -> bool:
        """True when writing the menu would not destroy anything.

        ``_upsert_menu`` deletes every MenuItem before rebuilding, so a menu that
        already has items is off limits — even if it is the one we would have
        created.
        """
        from bfg.web.models import Menu, MenuItem

        existing = Menu.objects.filter(
            workspace=self.workspace, slug=menu['slug'], language=menu['language'],
        ).first()
        if existing is None:
            # A different menu already occupying the location counts as taken:
            # two active header menus and the storefront picks one arbitrarily.
            return not Menu.objects.filter(
                workspace=self.workspace, location=menu['location'],
                language=menu['language'], is_active=True,
            ).exists()
        return not MenuItem.objects.filter(menu=existing).exists()

    @staticmethod
    def _delivery_skipped(plan: Dict[str, Any]) -> bool:
        return 'delivery.warehouse' in (plan.get('checklist_skip') or [])

    def _record_state(self, plan: Dict[str, Any]) -> None:
        state = self.get_state()
        state.update({
            'country': plan['country']['code'],
            'industry': plan['industry']['key'],
            'applied_at': timezone.now().isoformat(),
        })
        # An industry with no shipping hides those rows rather than leaving a
        # step that can never reach 100%.
        state['hidden'] = sorted(set(plan.get('checklist_skip') or []))
        self._save_state(state)

    def _save_state(self, state: Dict[str, Any]) -> None:
        settings_obj = self._settings()
        custom = dict(settings_obj.custom_settings or {})
        custom['onboarding'] = state
        settings_obj.custom_settings = custom
        settings_obj.save(update_fields=['custom_settings', 'updated_at'])

    def _invalidate_caches(self) -> None:
        from bfg.common.middleware import invalidate_workspace_cache
        from bfg.common.storefront_cache import invalidate_storefront_config_cache

        invalidate_workspace_cache(self.workspace)
        invalidate_storefront_config_cache(self.workspace.id)


def options_payload() -> Dict[str, Any]:
    """Everything the wizard's first screen needs to render its two dropdowns."""
    from .catalog import INDUSTRIES, SUPPORTED_LANGUAGES, country_options
    from .extensions import contributed_industries

    # Contributed industries come last: BFG's own list is the familiar one, and
    # an app's addition reads as an addition rather than displacing it.
    industries = [dict(item) for item in INDUSTRIES]
    known = {item['key'] for item in industries}
    industries += [item for item in contributed_industries() if item['key'] not in known]

    return {
        'countries': country_options(),
        'industries': industries,
        'languages': list(SUPPORTED_LANGUAGES),
        'defaults': {'country': DEFAULT_COUNTRY, 'industry': DEFAULT_INDUSTRY},
    }
