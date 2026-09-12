# -*- coding: utf-8 -*-
"""
Setup wizard: the checklist, and applying a country/industry template.

The behaviour worth pinning down is the non-destructive one. ``SiteConfigService``
happily republishes any page it is handed and wipes a menu's items before
rebuilding them; a wizard someone runs twice must not do either.
"""

import pytest

from bfg.common.onboarding import OnboardingService, evaluate
from bfg.common.onboarding.templates import build_plan


@pytest.fixture
def workspace(db):
    from bfg.common.models import Workspace

    return Workspace.objects.create(name='Fresh Shop', slug='fresh-shop', is_active=True)


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username='owner', email='owner@fresh.example')


@pytest.fixture
def service(workspace, admin_user):
    return OnboardingService(workspace=workspace, user=admin_user)


# ── the checklist ────────────────────────────────────────────────────────

def test_a_bare_workspace_is_not_reported_as_ready(service):
    status = service.status()

    assert status['percent'] < 100
    assert status['complete'] is False
    assert {step['key'] for step in status['steps']} >= {
        'basics', 'brand', 'catalogue', 'payments', 'delivery', 'content', 'launch'
    }


def test_percent_never_reads_100_while_an_item_is_outstanding(workspace):
    """A checklist that says "done" next to a red row teaches people to ignore it."""
    from bfg.common.onboarding.checklist import _percent

    assert _percent(0, 10) == 0
    assert _percent(9, 10) == 90
    # 199/200 rounds to 99.5 → would print as 100 without the clamp.
    assert _percent(199, 200) == 99
    assert _percent(10, 10) == 100


def test_a_skipped_item_counts_as_settled_but_stays_visible(service):
    before = service.status()['percent']

    status = service.skip_item('brand.contact_phone')  # optional item
    status = service.skip_item('launch.domain')        # required item

    assert status['percent'] > before
    domain = next(
        item for step in status['steps'] for item in step['items'] if item['key'] == 'launch.domain'
    )
    assert domain['skipped'] is True
    assert domain['done'] is False


def test_skipping_an_unknown_item_is_an_error_not_a_silent_no_op(service):
    with pytest.raises(ValueError):
        service.skip_item('basics.nonexistent')


# ── templates ────────────────────────────────────────────────────────────

def test_a_country_pick_drives_currency_timezone_and_tax(service):
    plan = service.build(country='NZ', industry='general_retail')

    assert plan['settings']['default_currency'] == 'NZD'
    assert plan['settings']['default_timezone'] == 'Pacific/Auckland'
    assert plan['tax']['name'] == 'GST'
    assert plan['tax']['rate'] == '15.00'


def test_legal_copy_is_rendered_not_left_full_of_placeholders(service):
    plan = service.build(country='NZ', industry='fashion',
                         overrides={'site_name': 'Fresh Shop', 'contact_email': 'hi@fresh.example'})

    privacy = next(p for p in plan['pages'] if p['slug'] == 'privacy' and p['language'] == 'en')
    assert '{{' not in privacy['content']
    assert 'Fresh Shop' in privacy['content']
    assert 'hi@fresh.example' in privacy['content']
    assert 'New Zealand' in privacy['content']


def test_a_missing_contact_email_renders_as_something_a_human_will_notice(service):
    plan = service.build(country='NZ', industry='general_retail')

    contact = next(p for p in plan['pages'] if p['slug'] == 'contact' and p['language'] == 'en')
    # A plausible-looking fake address would ship to production unnoticed.
    assert '[email address]' in contact['content']


def test_only_languages_the_storefront_can_render_are_offered(service):
    plan = service.build(country='CN', industry='general_retail',
                         overrides={'languages': ['zh-hans', 'en', 'ja']})

    assert plan['settings']['supported_languages'] == ['zh-hans', 'en']


def test_content_is_emitted_for_every_supported_language(service):
    plan = service.build(country='CN', industry='fashion')
    languages = plan['settings']['supported_languages']

    assert len(languages) == 2
    for language in languages:
        assert any(p['language'] == language and p['slug'] == 'privacy' for p in plan['pages'])
        assert any(c['language'] == language for c in plan['categories'])


def test_an_industry_without_shipping_drops_the_delivery_rows(service):
    plan = service.build(country='NZ', industry='services')

    assert 'delivery.warehouse' in plan['checklist_skip']
    assert not any(p['slug'] == 'delivery' for p in plan['pages'])


def test_an_unknown_country_falls_back_instead_of_raising():
    plan = build_plan(country_code='ZZ', industry_key='general_retail', site_name='X')

    assert plan['settings']['default_currency']


# ── apply ────────────────────────────────────────────────────────────────

def test_applying_a_template_satisfies_the_items_it_claims_to(service, workspace):
    from bfg.common.onboarding.checklist import items_by_key

    service.apply(country='NZ', industry='general_retail')
    status = service.status()

    by_key = {item['key']: item for step in status['steps'] for item in step['items']}
    unfulfilled = [
        key for key, item in items_by_key().items()
        if item.from_template and key in by_key and not by_key[key]['done']
    ]
    assert unfulfilled == []


def test_apply_writes_the_rows_a_storefront_cannot_run_without(service, workspace):
    from bfg.finance.models import Currency, TaxRate
    from bfg.shop.models import ProductCategory, Store
    from bfg.web.models import Menu, Page

    service.apply(country='NZ', industry='fashion')

    assert Currency.objects.filter(code='NZD', is_active=True).exists()
    assert TaxRate.objects.filter(workspace=workspace, name='GST').exists()
    assert Store.all_objects.filter(workspace=workspace, is_active=True).exists()
    assert ProductCategory.all_objects.filter(workspace=workspace, slug='womens').exists()
    assert Page.objects.filter(workspace=workspace, slug='privacy', status='published').exists()
    assert Page.objects.filter(workspace=workspace, slug='home', status='published').exists()
    assert Menu.objects.filter(workspace=workspace, location='header').exists()


def test_apply_is_idempotent(service, workspace):
    from bfg.web.models import Page

    service.apply(country='NZ', industry='fashion')
    first = Page.objects.filter(workspace=workspace).count()

    result = service.apply(country='NZ', industry='fashion')
    second = Page.objects.filter(workspace=workspace).count()

    assert first == second
    assert all(change['action'] == 'keep' for change in result['changes']), result['changes']


def test_apply_does_not_republish_a_page_the_user_rewrote(service, workspace):
    """``_upsert_page`` is an update_or_create — the filtering is the only guard."""
    from bfg.web.models import Page

    service.apply(country='NZ', industry='general_retail')
    page = Page.objects.get(workspace=workspace, slug='privacy', language='en')
    page.blocks = [{'id': 'mine', 'type': 'text_block_v1', 'data': {'content': {'en': 'My own words'}}}]
    page.title = 'Our privacy promise'
    page.save()

    service.apply(country='NZ', industry='general_retail')

    page.refresh_from_db()
    assert page.title == 'Our privacy promise'
    assert page.blocks[0]['id'] == 'mine'


def test_apply_does_not_wipe_a_menu_the_user_reordered(service, workspace):
    """``_upsert_menu`` deletes every MenuItem before rebuilding."""
    from bfg.web.models import Menu, MenuItem

    service.apply(country='NZ', industry='general_retail')
    menu = Menu.objects.filter(workspace=workspace, location='header').first()
    MenuItem.objects.filter(menu=menu).delete()
    MenuItem.objects.create(menu=menu, title='Only mine', url='/mine', order=1)

    service.apply(country='NZ', industry='general_retail')

    titles = list(MenuItem.objects.filter(menu=menu).values_list('title', flat=True))
    assert titles == ['Only mine']


def test_apply_leaves_an_existing_tax_rate_alone(service, workspace):
    """A second "GST 15%" row would quietly double-charge every order."""
    from bfg.finance.models import TaxRate

    TaxRate.objects.create(workspace=workspace, name='Reduced', rate='9.00', country='NZ', is_active=True)

    service.apply(country='NZ', industry='general_retail')

    assert TaxRate.objects.filter(workspace=workspace).count() == 1


def test_apply_never_registers_a_placeholder_domain(service, workspace):
    """SiteConfigService invents ``xmart-sales.local`` when handed a site with no domain.

    Registering that as the workspace's primary verified hostname would break
    tenant routing for whoever else claimed it.
    """
    from bfg.common.models import WorkspaceDomain

    service.apply(country='NZ', industry='general_retail')

    assert not WorkspaceDomain.objects.filter(workspace=workspace).exists()


def test_a_currency_the_seed_data_never_creates_still_gets_a_row(service):
    """OrderService falls back to the first active currency rather than creating one."""
    from bfg.finance.models import Currency

    service.apply(country='SG', industry='general_retail')

    row = Currency.objects.get(code='SGD')
    assert row.symbol == 'S$'
    assert row.is_active is True


def test_a_services_workspace_is_not_held_back_by_shipping_it_never_does(service):
    service.apply(country='NZ', industry='services')
    status = service.status()

    keys = {item['key'] for step in status['steps'] for item in step['items']}
    assert 'delivery.warehouse' not in keys
    assert 'delivery.carrier' not in keys


def test_preview_reports_the_same_work_apply_then_does(service):
    preview = service.preview(country='NZ', industry='fashion')
    creates = {(c['kind'], c['key']) for c in preview['changes'] if c['action'] == 'create'}

    result = service.apply(country='NZ', industry='fashion')
    applied = {(c['kind'], c['key']) for c in result['changes'] if c['action'] == 'create'}

    assert creates == applied


def test_preview_writes_nothing(service, workspace):
    from bfg.finance.models import Currency
    from bfg.web.models import Page

    service.preview(country='SG', industry='fashion')

    assert not Page.objects.filter(workspace=workspace).exists()
    assert not Currency.objects.filter(code='SGD').exists()


def test_apply_respects_a_shop_name_the_user_already_chose(service, workspace):
    from bfg.common.models import Settings

    Settings.objects.update_or_create(workspace=workspace, defaults={'site_name': 'Kept Name'})

    service.apply(country='NZ', industry='general_retail')

    assert Settings.objects.get(workspace=workspace).site_name == 'Kept Name'


def test_apply_does_overwrite_the_locale_the_user_just_picked(service, workspace):
    """Choosing New Zealand and still seeing USD would read as the wizard failing."""
    from bfg.common.models import Settings

    Settings.objects.update_or_create(workspace=workspace, defaults={'default_currency': 'USD'})

    service.apply(country='NZ', industry='general_retail')

    assert Settings.objects.get(workspace=workspace).default_currency == 'NZD'


def test_the_pick_is_remembered_so_the_wizard_reopens_where_it_was(service):
    service.apply(country='AU', industry='beauty')

    state = service.status()['state']
    assert state['country'] == 'AU'
    assert state['industry'] == 'beauty'
    assert state['applied_at']


def test_evaluate_works_without_any_saved_state(workspace):
    """The dashboard block calls this on workspaces that predate the wizard."""
    status = evaluate(workspace)

    assert 0 <= status['percent'] <= 100
    assert status['required_total'] > 0


def test_a_site_row_appears_once_the_workspace_has_a_hostname(service, workspace):
    from bfg.common.models import upsert_custom_workspace_domain
    from bfg.web.models import Site

    upsert_custom_workspace_domain(workspace, 'fresh.example.com', is_primary=True)

    service.apply(country='NZ', industry='general_retail')

    site = Site.all_objects.get(workspace=workspace, domain='fresh.example.com')
    assert site.default_language == 'en'
    assert site.is_default is True


def test_site_language_matches_the_workspace_language(service, workspace):
    """A zh-hans workspace behind an `en` Site returns an empty catalogue."""
    from bfg.common.models import Settings, upsert_custom_workspace_domain
    from bfg.web.models import Site

    upsert_custom_workspace_domain(workspace, 'zh.example.com', is_primary=True)

    service.apply(country='CN', industry='general_retail')

    site = Site.all_objects.get(workspace=workspace, domain='zh.example.com')
    assert site.default_language == Settings.objects.get(workspace=workspace).default_language


# ── notification templates ───────────────────────────────────────────────

def _notification_templates(workspace):
    from bfg.inbox.models import MessageTemplate

    return MessageTemplate.objects.filter(workspace=workspace)


def _template_changes(changes, action):
    return {c['key'] for c in changes if c['kind'] == 'notification_template' and c['action'] == action}


def test_apply_writes_notification_templates_in_the_language_it_picks(service, workspace):
    """A notification whose code has no template is skipped: the customer hears nothing."""
    from bfg.inbox.notification_templates import NOTIFICATION_CODES

    preview = service.preview(country='CN', industry='general_retail')
    result = service.apply(country='CN', industry='general_retail')

    templates = _notification_templates(workspace)
    assert sorted(templates.values_list('code', flat=True)) == sorted(NOTIFICATION_CODES)
    assert set(templates.values_list('language', flat=True)) == {'zh-hans'}
    assert '合计 ¥' in templates.get(code='order_created').app_message_body
    assert _template_changes(preview['changes'], 'create') == set(NOTIFICATION_CODES)
    assert _template_changes(result['changes'], 'create') == set(NOTIFICATION_CODES)


def test_templates_seeded_before_the_pick_are_rewritten_for_it(service, workspace):
    """Platform provisioning seeds them in the settings defaults, before anyone picks a country.

    Left as they were, a Chinese shop would write to its customers in English, in dollars.
    """
    from bfg.inbox.notification_templates import NOTIFICATION_CODES, ensure_notification_templates

    ensure_notification_templates(workspace)

    preview = service.preview(country='CN', industry='general_retail')
    result = service.apply(country='CN', industry='general_retail')

    templates = _notification_templates(workspace)
    assert templates.count() == len(NOTIFICATION_CODES)
    assert set(templates.values_list('language', flat=True)) == {'zh-hans'}
    assert '合计 ¥' in templates.get(code='order_created').app_message_body
    assert _template_changes(preview['changes'], 'update') == set(NOTIFICATION_CODES)
    assert _template_changes(result['changes'], 'update') == set(NOTIFICATION_CODES)


def test_apply_leaves_a_template_the_shop_changed(service, workspace):
    from bfg.inbox.notification_templates import NOTIFICATION_CODES, ensure_notification_templates

    ensure_notification_templates(workspace)
    _notification_templates(workspace).filter(code='order_shipped').update(
        app_message_body='On its way: {{ order_number }}',
    )

    service.apply(country='CN', industry='general_retail')

    templates = _notification_templates(workspace)
    own = templates.get(code='order_shipped')
    assert (own.language, own.app_message_body) == ('en', 'On its way: {{ order_number }}')
    # And no Chinese copy is added beside the shop's own.
    assert templates.count() == len(NOTIFICATION_CODES)


# ── contributions from installed apps ────────────────────────────────────

@pytest.fixture
def contributing_app(monkeypatch):
    """Install a synthetic ``onboarding_setup`` provider for the duration of a test.

    Discovery walks ``apps.get_app_configs()`` and imports ``<app>.onboarding_setup``;
    faking the import is enough to exercise the merge without adding an app to
    INSTALLED_APPS for every case.
    """
    import types

    from bfg.common.onboarding import extensions
    from bfg.common.onboarding.checklist import Item, Step

    module = types.ModuleType('fake.onboarding_setup')
    module.ONBOARDING_ITEMS = {
        'launch': [
            Item('fake.connected', 'Marketplace connected', '已连接渠道', '/admin/fake',
                 lambda facts: False, required=False, hint='Connect a channel.', hint_zh='连接一个渠道。')
        ]
    }
    module.ONBOARDING_STEPS = [
        Step(key='fake_step', title='Extras', title_zh='附加', description='', description_zh='',
             icon='tabler-puzzle',
             items=[Item('fake.thing', 'A thing', '一件事', '/admin/fake', lambda facts: True,
                         value=lambda facts: 'all good')])
    ]
    module.get_custom_settings_patch = lambda plan, workspace: {
        'fake_plugin': {'country_code': plan['settings']['country'], 'enabled': True}
    }
    module.ONBOARDING_INDUSTRIES = [
        {'key': 'consignment', 'name': 'Consignment', 'name_zh': '寄卖',
         'icon': 'tabler-recycle', 'description': '', 'description_zh': ''}
    ]
    module.get_template_fragment = lambda country, industry, plan: {
        'categories': [
            {'slug': 'preloved', 'name': 'Preloved', 'language': 'en', 'order': 5,
             'icon': '', 'description': ''},
            # Same slug the base template already emits: must not double up.
            {'slug': 'sale', 'name': 'Duplicate', 'language': 'en', 'order': 5,
             'icon': '', 'description': ''},
            # A language this workspace does not render.
            {'slug': 'preloved', 'name': '二手', 'language': 'ja', 'order': 5,
             'icon': '', 'description': ''},
        ],
        'shop_settings': {'sku_display': 'full'},
        'checklist_skip': ['payments.invoice_prefix'],
    }

    def fake_iter():
        yield types.SimpleNamespace(name='fake'), module

    monkeypatch.setattr(extensions, '_iter_provider_modules', fake_iter)
    extensions.reset_cache()
    yield module
    extensions.reset_cache()


def test_an_app_can_add_a_row_to_a_step_bfg_owns(service, contributing_app):
    status = service.status()

    launch = next(step for step in status['steps'] if step['key'] == 'launch')
    assert 'fake.connected' in {item['key'] for item in launch['items']}


def test_an_app_can_add_a_whole_step(service, contributing_app):
    status = service.status()

    assert 'fake_step' in {step['key'] for step in status['steps']}


def test_a_contributed_row_can_be_skipped_like_any_other(service, contributing_app):
    status = service.skip_item('fake.connected')

    item = next(i for step in status['steps'] for i in step['items'] if i['key'] == 'fake.connected')
    assert item['skipped'] is True


def test_an_app_can_prefill_its_own_config_from_the_country_pick(service, workspace, contributing_app):
    from bfg.common.models import Settings

    service.apply(country='NZ', industry='general_retail')

    custom = Settings.objects.get(workspace=workspace).custom_settings
    assert custom['fake_plugin'] == {'country_code': 'NZ', 'enabled': True}


def test_prefilling_never_clobbers_a_value_the_user_set(service, workspace, contributing_app):
    """An app deriving `country_code` from the pick must not wipe a pasted API key."""
    from bfg.common.models import Settings

    settings_obj = Settings.objects.get(workspace=workspace)
    settings_obj.custom_settings = {'fake_plugin': {'enabled': False, 'api_key': 'secret'}}
    settings_obj.save()

    service.apply(country='NZ', industry='general_retail')

    custom = Settings.objects.get(workspace=workspace).custom_settings
    assert custom['fake_plugin']['api_key'] == 'secret'
    assert custom['fake_plugin']['enabled'] is False
    assert custom['fake_plugin']['country_code'] == 'NZ'


def test_a_broken_provider_does_not_take_the_checklist_down(service, monkeypatch):
    """A contributed provider is third-party code; the checklist still has to render."""
    import types

    from bfg.common.onboarding import extensions

    module = types.ModuleType('broken.onboarding_setup')

    def explode(plan, workspace):
        raise RuntimeError('provider is broken')

    module.get_custom_settings_patch = explode

    monkeypatch.setattr(
        extensions, '_iter_provider_modules',
        lambda: iter([(types.SimpleNamespace(name='broken'), module)]),
    )
    extensions.reset_cache()
    try:
        assert service.apply(country='NZ', industry='general_retail')['status']['percent'] >= 0
    finally:
        extensions.reset_cache()


def test_contact_details_typed_into_the_wizard_are_saved_not_just_printed(service, workspace):
    """They are quoted in the generated legal pages *and* are real Settings fields.

    Rendering them into a published privacy policy while leaving
    ``Settings.contact_email`` empty left `brand.contact_email` red immediately
    after the user had supplied it.
    """
    from bfg.common.models import Settings

    service.apply(country='NZ', industry='general_retail', overrides={
        'contact_email': 'hi@fresh.example', 'contact_phone': '+64 9 555 0000',
    })

    settings_obj = Settings.objects.get(workspace=workspace)
    assert settings_obj.contact_email == 'hi@fresh.example'
    assert settings_obj.contact_phone == '+64 9 555 0000'
    # The General settings page reads custom_settings.general first.
    assert settings_obj.custom_settings['general']['contact_email'] == 'hi@fresh.example'

    status = service.status()
    email_item = next(
        i for step in status['steps'] for i in step['items'] if i['key'] == 'brand.contact_email'
    )
    assert email_item['done'] is True


def test_leaving_contact_blank_does_not_wipe_what_is_already_there(service, workspace):
    from bfg.common.models import Settings

    Settings.objects.update_or_create(workspace=workspace, defaults={'contact_email': 'kept@example.com'})

    service.apply(country='NZ', industry='general_retail')

    assert Settings.objects.get(workspace=workspace).contact_email == 'kept@example.com'


# ── values shown on the checklist ────────────────────────────────────────

def test_a_done_row_reports_what_it_is_set_to(service, workspace):
    """The checklist has to answer "what did I configure", not just "is it done"."""
    service.apply(country='NZ', industry='fashion', overrides={'contact_email': 'hi@fresh.example'})

    by_key = {i['key']: i for step in service.status()['steps'] for i in step['items']}

    assert by_key['basics.currency']['value'] == 'NZD'
    assert by_key['basics.timezone']['value'] == 'Pacific/Auckland'
    assert by_key['brand.contact_email']['value'] == 'hi@fresh.example'
    assert by_key['payments.tax_rate']['value'] == 'GST 15.00%'
    assert by_key['catalogue.category']['value'] == '7'


def test_country_reads_as_a_name_in_both_languages(service):
    service.apply(country='NZ', industry='general_retail')

    country = next(
        i for step in service.status()['steps'] for i in step['items'] if i['key'] == 'basics.country'
    )
    assert country['value'] == 'New Zealand'
    assert country['value_zh'] == '新西兰'


def test_a_page_row_shows_which_languages_it_is_published_in(service):
    """A bare tick would hide a policy that exists in English only."""
    service.apply(country='CN', industry='general_retail')

    privacy = next(
        i for step in service.status()['steps'] for i in step['items'] if i['key'] == 'content.privacy'
    )
    assert privacy['value'] == 'en, zh-hans'


def test_an_unset_row_reports_no_value(service):
    gateway = next(
        i for step in service.status()['steps'] for i in step['items'] if i['key'] == 'payments.gateway'
    )
    assert gateway['done'] is False
    assert gateway['value'] == ''


def test_each_category_carries_a_one_line_digest(service):
    service.apply(country='NZ', industry='general_retail')

    basics = next(step for step in service.status()['steps'] if step['key'] == 'basics')

    assert 'NZD' in basics['summary']
    assert '新西兰' in basics['summary_zh']
    # Capped, or the digest wraps to three lines and stops being a digest.
    assert basics['summary'].count(' · ') <= 4


def test_a_value_accessor_that_throws_does_not_break_the_page():
    """Values are cosmetic, and a contributed one is third-party code."""
    from bfg.common.onboarding.checklist import _read_value

    def explode(facts):
        raise RuntimeError('boom')

    assert _read_value(explode, None) == ''
    assert _read_value(None, None) == ''
    assert _read_value(lambda facts: None, None) == ''
    assert _read_value(lambda facts: '  NZD  ', None) == 'NZD'


def test_a_contributed_row_can_report_its_value_too(service, contributing_app):
    status = service.status()

    thing = next(
        i for step in status['steps'] for i in step['items'] if i['key'] == 'fake.thing'
    )
    assert thing['value'] == 'all good'


# ── extensions contributing to the template itself ───────────────────────

def test_an_app_can_offer_its_own_industry(service, contributing_app):
    from bfg.common.onboarding.service import options_payload

    keys = [item['key'] for item in options_payload()['industries']]

    assert 'consignment' in keys
    # Appended, not substituted for BFG's own list.
    assert 'general_retail' in keys
    assert keys.index('general_retail') < keys.index('consignment')


def test_a_contributed_fragment_adds_categories_to_the_plan(service, contributing_app):
    plan = service.build(country='NZ', industry='fashion')

    slugs = [c['slug'] for c in plan['categories'] if c['language'] == 'en']
    assert 'preloved' in slugs
    # The base template's own categories survive.
    assert 'womens' in slugs


def test_a_fragment_cannot_duplicate_a_row_the_template_already_has(service, contributing_app):
    """ProductCategory is unique on (workspace, slug, language); a duplicate here
    becomes two rows racing through update_or_create."""
    plan = service.build(country='NZ', industry='fashion')

    slugs = [c['slug'] for c in plan['categories'] if c['language'] == 'en']
    assert slugs.count('sale') == 1


def test_a_fragment_cannot_introduce_a_language_the_storefront_lacks(service, contributing_app):
    plan = service.build(country='NZ', industry='fashion')

    assert not any(c['language'] == 'ja' for c in plan['categories'])


def test_a_fragment_can_override_display_defaults_and_hide_rows(service, contributing_app):
    plan = service.build(country='NZ', industry='fashion')

    assert plan['shop_settings']['sku_display'] == 'full'
    assert 'payments.invoice_prefix' in plan['checklist_skip']


def test_contributed_categories_are_actually_written(service, workspace, contributing_app):
    from bfg.shop.models import ProductCategory

    service.apply(country='NZ', industry='fashion')

    assert ProductCategory.all_objects.filter(workspace=workspace, slug='preloved').exists()


def test_a_broken_fragment_provider_does_not_break_the_wizard(service, monkeypatch):
    import types

    from bfg.common.onboarding import extensions

    module = types.ModuleType('broken.onboarding_setup')
    module.get_template_fragment = lambda country, industry, plan: 1 / 0

    monkeypatch.setattr(
        extensions, '_iter_provider_modules',
        lambda: iter([(types.SimpleNamespace(name='broken'), module)]),
    )
    extensions.reset_cache()
    try:
        assert service.build(country='NZ', industry='fashion')['categories']
    finally:
        extensions.reset_cache()
