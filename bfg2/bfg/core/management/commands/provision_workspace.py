# -*- coding: utf-8 -*-
"""
Create a workspace and complete every setting a storefront needs, or audit an
existing one.

``init`` bootstraps the *first* workspace of a fresh install. This command is for
every workspace after that: it creates the rows that nothing else creates
automatically, and — with ``--check`` — reports which of them a workspace is
still missing.

The gaps it closes exist because ``WorkspaceService.create_workspace`` (and the
platform ``POST /api/v1/platform/workspaces/``) only make the workspace, its
roles and its owner. Everything a shopper actually touches is left unset, and
each one fails quietly rather than loudly:

  * no ``shop.Store``           → ``/store/cart/default_store/`` 404s and checkout dies
  * no ``finance.Currency`` row → invoices and payments are written in whatever
                                  currency happens to sort first, not the one the
                                  workspace is configured for
  * ``Settings`` default USD/en → prices and copy in the wrong currency/language
  * no ``web.Site``             → the storefront asks for categories in ``en`` and a
                                  zh-hans catalogue returns nothing
  * no primary ``WorkspaceDomain`` → the hostname resolves to no tenant
  * no published ``home`` page  → the storefront renders a bare welcome message

Usage:

    # audit — prints a readiness table, exits 1 when something is missing
    python manage.py provision_workspace --slug geeker --check

    # create or complete, idempotent
    python manage.py provision_workspace \\
        --slug yamei --name 'Yamei' \\
        --domain yamei.surlex.com \\
        --country NZ --currency NZD --language zh-hans --languages zh-hans,en \\
        --admin-user admin --seed-home

CORS on the API app and the Vercel domain/alias live outside Django; the command
prints them as remaining steps rather than pretending to have done them.
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction

from bfg.common.middleware import set_current_workspace
from bfg.common.models import (
    Settings,
    StaffMember,
    StaffRole,
    Workspace,
    WorkspaceDomain,
    upsert_custom_workspace_domain,
)

User = get_user_model()

DEFAULT_STORE_CODE = 'main'
DEFAULT_STORE_NAME = 'Main'
DEFAULT_THEME_CODE = 'store'

# Symbols for the currencies BFG does not seed. ``finance.seed_data`` only creates
# USD/EUR/GBP/CNY, and the order service falls back to "first active currency"
# rather than creating the one it wants — so a NZD workspace silently invoices in CNY.
CURRENCY_SYMBOLS = {
    'AUD': 'A$', 'CAD': 'C$', 'CHF': 'CHF', 'HKD': 'HK$', 'JPY': '¥',
    'KRW': '₩', 'NZD': 'NZ$', 'SGD': 'S$', 'TWD': 'NT$',
}
CURRENCY_NAMES = {
    'AUD': 'Australian Dollar', 'CAD': 'Canadian Dollar', 'CHF': 'Swiss Franc',
    'HKD': 'Hong Kong Dollar', 'JPY': 'Japanese Yen', 'KRW': 'South Korean Won',
    'NZD': 'New Zealand Dollar', 'SGD': 'Singapore Dollar', 'TWD': 'New Taiwan Dollar',
}


def home_page_blocks():
    """The block list a storefront home page needs to show anything.

    ``source: "promo"`` resolves against the workspace's home Campaign at render
    time and ``source: "auto"`` against the storefront product API, so the same
    blocks work for a workspace with no content yet — the rails just render their
    empty message until products are flagged.
    """

    def product_grid(block_id, product_type, title_en, title_zh, empty_en, empty_zh, alt=False):
        return {
            'id': block_id,
            'type': 'product_grid_v1',
            'settings': {'columns': 4, 'limit': 8, 'showTitle': True, 'altBackground': alt},
            'data': {
                'source': 'auto',
                'productType': product_type,
                'title': {'en': title_en, 'zh-hans': title_zh},
                'emptyMessage': {'en': empty_en, 'zh-hans': empty_zh},
            },
        }

    return [
        {
            'id': 'hero-carousel',
            'type': 'hero_carousel_v1',
            'settings': {'autoPlay': True, 'interval': 5000, 'showArrows': True,
                         'showDots': True, 'height': '500px'},
            'data': {'source': 'promo', 'slides': []},
        },
        {
            'id': 'content-section',
            'type': 'section_v1',
            'settings': {},
            'data': {
                'width': 'container',
                'children': [
                    {
                        'id': 'category-grid',
                        'type': 'category_grid_v1',
                        'settings': {'columns': 4, 'limit': 12, 'showCount': True,
                                     'imageHeight': '180px'},
                        'data': {'source': 'promo'},
                    },
                    product_grid('featured-products', 'featured', 'Featured', '精选商品',
                                 'No featured products yet.', '暂无精选商品。', alt=True),
                    product_grid('new-products', 'new', 'New Arrivals', '新品上架',
                                 'No new products yet.', '暂无新品。'),
                    product_grid('bestseller-products', 'bestseller', 'Bestsellers', '畅销榜',
                                 'No bestsellers yet.', '暂无畅销商品。', alt=True),
                ],
            },
        },
    ]


class Command(BaseCommand):
    help = 'Create a workspace with every storefront setting filled in, or audit an existing one'

    def add_arguments(self, parser):
        parser.add_argument('--slug', required=True, help='Workspace slug (the identity; everything keys off it)')
        parser.add_argument('--name', default='', help='Workspace display name (required when creating)')
        parser.add_argument('--check', action='store_true',
                            help='Audit only — report readiness and exit 1 if anything is missing')
        parser.add_argument('--dry-run', action='store_true', help='Report what would change, write nothing')

        parser.add_argument('--domain', default='', help='Public storefront hostname, e.g. shop.example.com')
        parser.add_argument('--country', default='', help='ISO 3166-1 alpha-2, e.g. NZ')
        parser.add_argument('--currency', default='', help='ISO 4217, e.g. NZD')
        parser.add_argument('--language', default='', help='Default language, e.g. en or zh-hans')
        parser.add_argument('--languages', default='', help='Comma-separated language list for the Site')
        parser.add_argument('--theme', default=DEFAULT_THEME_CODE, help=f'Storefront theme id (default: {DEFAULT_THEME_CODE})')
        parser.add_argument('--store-name', default=DEFAULT_STORE_NAME)
        parser.add_argument('--store-code', default=DEFAULT_STORE_CODE)
        parser.add_argument('--admin-user', default='',
                            help='Username to add as workspace admin (must already exist)')
        parser.add_argument('--seed-home', action='store_true',
                            help='Create a published home page with the standard block layout')
        parser.add_argument('--site-config', default='',
                            help='Path to a site-config JSON; pages/menus/categories are loaded from it')

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        slug = options['slug'].strip()
        workspace = Workspace.objects.filter(slug=slug).first()

        if options['check']:
            if not workspace:
                raise CommandError(f'No workspace with slug {slug!r}')
            return self.audit(workspace)

        if not workspace and not options['name']:
            raise CommandError('--name is required when creating a new workspace')

        with transaction.atomic():
            workspace = self.ensure_workspace(workspace, slug, options['name'])
            # The tenant-scoped managers read a thread-local that only the request
            # middleware normally sets; without it ``Store.objects`` is empty here
            # and get_or_create would happily create a duplicate.
            set_current_workspace(workspace)
            try:
                self.ensure_settings(workspace, options)
                self.ensure_currency(workspace, options['currency'])
                self.ensure_store(workspace, options['store_name'], options['store_code'])
                self.ensure_admin(workspace, options['admin_user'])
                self.ensure_domain(workspace, options['domain'])
                self.ensure_site(workspace, options)
                if options['seed_home']:
                    self.ensure_home_page(workspace, options)
                if options['site_config']:
                    self.load_site_config(workspace, options['site_config'])
            finally:
                set_current_workspace(None)

            if self.dry_run:
                transaction.set_rollback(True)

        if not workspace.pk:
            # --dry-run on a slug that does not exist yet: there is nothing to audit.
            self.stdout.write('')
            self.stdout.write('Dry run — nothing was written.')
            return

        self.invalidate_caches(workspace)
        self.stdout.write('')
        self.audit(workspace, exit_on_missing=False)
        self.report_manual_steps(workspace, options['domain'])

    def invalidate_caches(self, workspace):
        """Both the storefront config and the hostname→workspace routing are cached."""
        from bfg.common.middleware import invalidate_workspace_cache
        from bfg.common.storefront_cache import invalidate_storefront_config_cache

        invalidate_workspace_cache(workspace)
        invalidate_storefront_config_cache(workspace.id)

    # ── steps ────────────────────────────────────────────────────────────

    def ensure_workspace(self, workspace, slug, name):
        if workspace:
            self.ok(f'workspace {workspace.name} (id={workspace.id}) already exists')
            return workspace
        if self.dry_run:
            self.change(f'would create workspace {name} ({slug})')
            # Nothing downstream can run without a row; build an unsaved stand-in
            # so --dry-run on a brand-new slug still prints the full plan.
            return Workspace(name=name, slug=slug, is_active=True)

        from bfg.common.services.workspace_service import WorkspaceService

        # Goes through the service so ``workspace.created`` fires and every module
        # gets its system roles; creating the row directly skips that.
        workspace = WorkspaceService(user=None).create_workspace(name=name, slug=slug)
        self.change(f'created workspace {workspace.name} (id={workspace.id})')
        return workspace

    def ensure_settings(self, workspace, options):
        if not workspace.pk:
            self.change('would set country / currency / language on the new settings row')
            return
        settings_obj, _ = Settings.objects.get_or_create(workspace=workspace)
        changed = []
        for field, value in (
            ('country', options['country'].strip().upper()[:2]),
            ('default_currency', options['currency'].strip().upper()[:3]),
            ('default_language', options['language'].strip()),
        ):
            if value and getattr(settings_obj, field) != value:
                setattr(settings_obj, field, value)
                changed.append(f'{field}={value}')
        languages = [x.strip() for x in options['languages'].split(',') if x.strip()]
        if languages and settings_obj.supported_languages != languages:
            settings_obj.supported_languages = languages
            changed.append(f'supported_languages={languages}')
        if not settings_obj.site_name and options['name']:
            settings_obj.site_name = options['name'][:255]
            changed.append('site_name')
        if changed:
            if not self.dry_run:
                settings_obj.save()
            self.change(f'settings: {", ".join(changed)}')
        else:
            self.ok('settings already match')

    def ensure_currency(self, workspace, code):
        """Make sure the workspace's currency exists as an active row.

        ``OrderService`` looks the code up and, when it is missing, falls back to
        the first active currency instead of creating it — so an NZD workspace
        writes CNY invoices. The row is global, not per workspace.
        """
        code = (code or '').strip().upper()[:3]
        if not code:
            return
        from bfg.finance.models import Currency

        if Currency.objects.filter(code=code, is_active=True).exists():
            self.ok(f'currency {code} exists')
            return
        if self.dry_run:
            self.change(f'would create currency {code}')
            return
        Currency.objects.update_or_create(
            code=code,
            defaults={
                'name': CURRENCY_NAMES.get(code, code),
                'symbol': CURRENCY_SYMBOLS.get(code, code),
                'is_active': True,
            },
        )
        self.change(f'created currency {code}')

    def ensure_store(self, workspace, name, code):
        if not workspace.pk:
            self.change(f'would create store {code}')
            return
        from bfg.shop.models import Store

        store = Store.all_objects.filter(workspace=workspace, code=code).first()
        if store:
            self.ok(f'store {store.code} (id={store.id}) exists')
            return
        if self.dry_run:
            self.change(f'would create store {code}')
            return
        store = Store.all_objects.create(workspace=workspace, name=name, code=code, is_active=True)
        self.change(f'created store {store.code} (id={store.id})')

    def ensure_admin(self, workspace, username):
        if not username:
            return
        if not workspace.pk:
            self.change(f'would add {username} as workspace admin')
            return
        user = User.objects.filter(username=username).first()
        if not user:
            raise CommandError(f'No user named {username!r}; create the account first')
        role = StaffRole.objects.filter(workspace=workspace, code='admin').first()
        if not role:
            raise CommandError(f'Workspace {workspace.slug} has no admin role — roles were not provisioned')
        member = StaffMember.all_objects.filter(workspace=workspace, user=user).first()
        if member:
            self.ok(f'{username} is already staff on this workspace')
            return
        if self.dry_run:
            self.change(f'would add {username} as workspace admin')
            return
        StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=True)
        self.change(f'added {username} as workspace admin')

    def ensure_domain(self, workspace, hostname):
        if not hostname:
            return
        if not workspace.pk:
            self.change(f'would point {hostname} at this workspace')
            return
        hostname = hostname.strip()
        existing = WorkspaceDomain.objects.filter(hostname=hostname).first()
        if existing and existing.workspace_id != workspace.id:
            raise CommandError(
                f'{hostname} already belongs to workspace {existing.workspace_id}; '
                'hostname is unique across the install'
            )
        if self.dry_run:
            self.change(f'would point {hostname} at this workspace')
            return
        # verified + primary + kind=custom is exactly what
        # resolve_workspace_public_frontend_base_url looks for; ssl_status is not read.
        domain = upsert_custom_workspace_domain(
            workspace, hostname, is_primary=True,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
            ssl_status=WorkspaceDomain.SSL_ACTIVE,
        )
        self.change(f'domain {domain.hostname} → workspace {workspace.id} (primary, verified)')

    def ensure_site(self, workspace, options):
        hostname = options['domain'].strip()
        if not hostname:
            return
        if not workspace.pk:
            self.change(f'would upsert site {hostname}')
            return
        from bfg.web.models import Site, Theme

        language = options['language'].strip() or 'en'
        languages = [x.strip() for x in options['languages'].split(',') if x.strip()] or [language]
        name = options['name'] or workspace.name

        if self.dry_run:
            self.change(f'would upsert site {hostname} (lang={language}, theme={options["theme"]})')
            return

        theme, _ = Theme.objects.get_or_create(
            workspace=workspace, code=options['theme'],
            defaults={'name': f'{name} {options["theme"]}',
                      'template_path': f'themes/{options["theme"]}', 'is_active': True},
        )
        site, created = Site.all_objects.get_or_create(
            workspace=workspace, domain=hostname,
            defaults={'name': name, 'site_title': name, 'default_language': language,
                      'languages': languages, 'theme': theme, 'is_active': True, 'is_default': True},
        )
        if not created:
            site.default_language = language
            site.languages = languages
            site.theme = theme
            site.is_active = True
            site.is_default = True
            site.save()
        # One default Site per workspace, or the config endpoint picks arbitrarily.
        Site.all_objects.filter(workspace=workspace, is_default=True).exclude(pk=site.pk).update(is_default=False)
        self.change(f'site {site.domain} (lang={site.default_language}, theme={theme.code})')

    def ensure_home_page(self, workspace, options):
        if not workspace.pk:
            self.change('would publish a home page with the standard block layout')
            return
        from bfg.web.models import Page

        language = options['language'].strip() or 'en'
        if self.dry_run:
            self.change(f'would publish home page (language={language})')
            return
        # Page.created_by is NOT NULL, so the row has to be attributed to someone.
        author = (
            User.objects.filter(staff_memberships__workspace=workspace).order_by('pk').first()
            or User.objects.filter(is_superuser=True).order_by('pk').first()
        )
        if not author:
            self.warn('no user available to author the home page — skipped (use --admin-user)')
            return
        page, _ = Page.objects.get_or_create(
            workspace=workspace, slug='home', language=language,
            defaults={'title': options['name'] or workspace.name, 'created_by': author},
        )
        page.blocks = home_page_blocks()
        page.status = 'published'
        if page.created_by_id is None:
            page.created_by = author
        page.save()
        self.change(f'home page published (id={page.id}, language={language})')

    def load_site_config(self, workspace, path):
        import json
        from pathlib import Path

        if not workspace.pk:
            self.change(f'would load site config {path}')
            return
        config_path = Path(path).resolve()
        if not config_path.exists():
            raise CommandError(f'Site config not found: {config_path}')
        if self.dry_run:
            self.change(f'would load site config {config_path.name}')
            return
        from bfg.common.utils import first_staff_user_for_workspace
        from bfg.web.services import SiteConfigService

        with open(config_path, 'r', encoding='utf-8') as handle:
            config = json.load(handle)
        author = first_staff_user_for_workspace(workspace)
        result = SiteConfigService(workspace=workspace, user=author).load_from_config(
            config, created_by_user=author, mode='merge',
        )
        self.change(
            f'site config loaded: {len(result.get("pages", []))} page(s), '
            f'{result.get("menus_count", 0)} menu(s), {result.get("categories_count", 0)} category(ies)'
        )

    # ── audit ────────────────────────────────────────────────────────────

    def audit(self, workspace, exit_on_missing=True):
        """Report every requirement, with the symptom each one causes when absent."""
        from bfg.finance.models import Currency
        from bfg.shop.models import Store
        from bfg.web.models import Menu, Page, Site

        settings_obj = Settings.objects.filter(workspace=workspace).first()
        currency = (getattr(settings_obj, 'default_currency', '') or '').upper()
        site = Site.all_objects.filter(workspace=workspace, is_active=True).order_by('-is_default', '-id').first()
        site_language = getattr(site, 'default_language', '')
        settings_language = getattr(settings_obj, 'default_language', '')

        checks = [
            ('workspace active', workspace.is_active, 'every request 404s'),
            ('settings row', settings_obj is not None, 'no locale, currency or branding'),
            ('country set', bool(getattr(settings_obj, 'country', '')),
             'address lookup off, no hreflang region'),
            ('currency row exists', bool(currency) and Currency.objects.filter(code=currency, is_active=True).exists(),
             f'invoices and payments fall back to another currency, not {currency or "the configured one"}'),
            ('active store', Store.all_objects.filter(workspace=workspace, is_active=True).exists(),
             'default_store 404s — checkout cannot complete'),
            ('primary verified domain',
             workspace.domains.filter(kind=WorkspaceDomain.KIND_CUSTOM,
                                      verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
                                      is_primary=True).exists(),
             'the hostname resolves to no tenant'),
            ('site row', site is not None, 'storefront language and theme fall back to defaults'),
            ('site language matches settings',
             not (site and settings_language) or site_language == settings_language,
             f'categories are filtered by the Site language ({site_language or "?"}), '
             f'not the workspace one ({settings_language or "?"})'),
            ('published home page',
             Page.objects.filter(workspace=workspace, slug='home', status='published').exists(),
             'the storefront home renders a bare welcome message'),
            ('header menu', Menu.objects.filter(workspace=workspace, location='header', is_active=True).exists(),
             'empty navigation'),
            ('workspace admin', StaffMember.all_objects.filter(workspace=workspace, is_active=True).exists(),
             'nobody can administer this workspace'),
        ]

        self.stdout.write(f'workspace {workspace.slug} (id={workspace.pk or "unsaved"})')
        missing = 0
        for label, passed, consequence in checks:
            if passed:
                self.stdout.write(self.style.SUCCESS(f'  ok      {label}'))
            else:
                missing += 1
                self.stdout.write(self.style.ERROR(f'  MISSING {label} — {consequence}'))
        if missing and exit_on_missing:
            raise CommandError(f'{missing} setting(s) missing')
        return None

    def report_manual_steps(self, workspace, hostname):
        """The parts that are not rows in this database."""
        if not hostname:
            return
        self.stdout.write('')
        self.stdout.write('Still to do outside Django:')
        self.stdout.write(f'  1. DNS: A {hostname} → 76.76.21.21')
        self.stdout.write(f'  2. Vercel: add {hostname} to the storefront project and to the domain')
        self.stdout.write('     list in .github/workflows/deploy-client.yml, then redeploy')
        self.stdout.write(f'  3. API: dokku config:set <app> CORS_ALLOWED_ORIGINS="…,https://{hostname}"')

    # ── output helpers ───────────────────────────────────────────────────

    def ok(self, message):
        self.stdout.write(f'  = {message}')

    def change(self, message):
        prefix = '  ~' if self.dry_run else '  +'
        self.stdout.write(self.style.SUCCESS(f'{prefix} {message}'))

    def warn(self, message):
        self.stdout.write(self.style.WARNING(f'  ! {message}'))
