# -*- coding: utf-8 -*-
"""
The onboarding checklist: what "set up" means, in one place.

``provision_workspace --check`` answers the same question from the command line,
but for an operator: it lists infrastructure rows and the symptom each missing
one causes. This list is for the person who owns the shop. Every item names a
screen they can go and fix, and the ones a human must supply (card keys, a real
postal address) are separated from the ones a template can write.

Adding a check is adding one ``Item`` here. The API serialises this list and the
admin UI renders whatever it is sent, so the two cannot drift.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── deep links into the admin UI ─────────────────────────────────────────
# Tab values match the `value:` keys in the client's settings pages; the shells
# read `?tab=` on mount.
SETTINGS_GENERAL = '/admin/settings/general'
#: General settings splits across two rails and the split is not intuitive:
#: `workspace` holds locale (language, currency, timezone, country) while
#: `storefront` holds everything a shopper sees — shop name, logo, contact
#: details, analytics. Sending "set your contact email" to `workspace` landed
#: people on a screen with no email field on it.
GENERAL_LOCALE = f'{SETTINGS_GENERAL}?tab=workspace'
GENERAL_STOREFRONT = f'{SETTINGS_GENERAL}?tab=storefront'
SETTINGS_FINANCE = '/admin/settings/finance'
SETTINGS_DELIVERY = '/admin/settings/delivery'
SETTINGS_WEB = '/admin/settings/web'
SETTINGS_STORE = '/admin/settings/store'


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    label_zh: str
    href: str
    check: Callable[['Facts'], bool]
    required: bool = True
    #: Shown under the label when the item is not done — says what to do, not
    #: what is wrong.
    hint: str = ''
    hint_zh: str = ''
    #: True when applying a country/industry template fills this in. The wizard
    #: uses it to explain what the "one click" actually covers.
    from_template: bool = False
    #: What the setting is currently *set to*, rendered next to the label so the
    #: checklist answers "what did I configure" without opening seven screens.
    #: Only read when the item is done. ``value_zh`` is for the few values that
    #: are words rather than codes, names or numbers.
    value: Optional[Callable[['Facts'], str]] = None
    value_zh: Optional[Callable[['Facts'], str]] = None


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    title_zh: str
    description: str
    description_zh: str
    icon: str
    items: List[Item] = field(default_factory=list)


class Facts:
    """One read of the workspace, shared by every check.

    Each check used to be free to run its own query; with ~30 of them that is
    ~30 round trips per page load of a screen that polls. Everything the list
    needs is gathered here once instead — names and counts as well as the
    booleans, because the checklist shows what each setting is set to.
    """

    #: Names are joined into one line; past this many the rest becomes "+3".
    NAME_LIMIT = 3

    def __init__(self, workspace):
        from django.db.models import Count

        from bfg.common.models import EmailConfig, Settings, StaffMember, WorkspaceDomain
        from bfg.delivery.models import Carrier, DeliveryZone, Warehouse
        from bfg.finance.models import Currency, PaymentGateway, TaxRate
        from bfg.shop.models import Product, ProductCategory, Store
        from bfg.web.models import Menu, MenuItem, Page, Site

        self.workspace = workspace
        self.settings = Settings.objects.filter(workspace=workspace).first()
        custom = (getattr(self.settings, 'custom_settings', None) or {})
        self.general = custom.get('general') or {}
        self.analytics = custom.get('analytics') or {}
        self.invoice = custom.get('invoice') or {}
        self.delivery_settings = custom.get('delivery') or {}
        self.state = custom.get('onboarding') or {}

        currency_code = (getattr(self.settings, 'default_currency', '') or '').upper()
        self.currency_code = currency_code
        self.currency_row = bool(currency_code) and Currency.objects.filter(
            code=currency_code, is_active=True
        ).exists()

        self.logo = str(getattr(self.settings, 'logo', '') or self.general.get('logo') or '')
        self.has_logo = bool(self.logo)
        self.email_config = EmailConfig.objects.filter(
            workspace=workspace, is_active=True
        ).order_by('-is_default', 'id').first()
        self.has_email_config = self.email_config is not None
        self.staff_count = StaffMember.all_objects.filter(workspace=workspace, is_active=True).count()
        self.has_staff = self.staff_count > 1
        self.domain = WorkspaceDomain.objects.filter(
            workspace=workspace,
            kind=WorkspaceDomain.KIND_CUSTOM,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ).order_by('-is_primary', 'id').first()
        self.has_domain = self.domain is not None

        self.store_names = list(
            Store.all_objects.filter(workspace=workspace, is_active=True).values_list('name', flat=True)
        )
        self.has_store = bool(self.store_names)
        self.category_count = ProductCategory.all_objects.filter(workspace=workspace, is_active=True).count()
        self.has_category = self.category_count > 0
        self.product_count = Product.all_objects.filter(workspace=workspace, is_active=True).count()
        self.has_product = self.product_count > 0

        self.gateway_names = list(
            PaymentGateway.objects.filter(workspace=workspace, is_active=True).values_list('name', flat=True)
        )
        self.has_gateway = bool(self.gateway_names)
        self.tax_rates = list(
            TaxRate.objects.filter(workspace=workspace, is_active=True).values_list('name', 'rate')
        )
        self.has_tax_rate = bool(self.tax_rates)

        warehouses = list(
            Warehouse.all_objects.filter(workspace=workspace, is_active=True)
            .values_list('name', 'address_line1', 'city', 'country')
        )
        self.warehouse_names = [name for name, _line1, _city, _country in warehouses]
        self.has_warehouse = bool(self.warehouse_names)
        self.warehouse_address = next(
            (
                ', '.join(part for part in (line1, city, country) if part)
                for _name, line1, city, country in warehouses
                if line1 and city
            ),
            '',
        )
        self.carrier_names = list(
            Carrier.all_objects.filter(workspace=workspace, is_active=True).values_list('name', flat=True)
        )
        self.has_carrier = bool(self.carrier_names)
        self.zone_names = list(
            DeliveryZone.objects.filter(workspace=workspace, is_active=True).values_list('name', flat=True)
        )
        self.has_zone = bool(self.zone_names)

        self.site = Site.all_objects.filter(workspace=workspace, is_active=True).order_by('-is_default', '-id').first()

        # slug → the languages it is published in, so a page row can show
        # "en, zh-hans" rather than a bare tick that hides a missing translation.
        self.page_languages: Dict[str, List[str]] = {}
        for slug, language in Page.objects.filter(
            workspace=workspace, status='published'
        ).values_list('slug', 'language'):
            self.page_languages.setdefault(slug, []).append(language)
        for languages in self.page_languages.values():
            languages.sort()

        menus = list(
            Menu.objects.filter(workspace=workspace, is_active=True).values('id', 'location')
        )
        item_counts = dict(
            MenuItem.objects.filter(menu_id__in=[menu['id'] for menu in menus])
            .values('menu_id')
            .annotate(total=Count('id'))
            .values_list('menu_id', 'total')
        )
        self.menu_item_counts: Dict[str, int] = {}
        for menu in menus:
            location = menu['location']
            self.menu_item_counts[location] = self.menu_item_counts.get(location, 0) + item_counts.get(menu['id'], 0)
        self.menu_locations = set(self.menu_item_counts)

    # ── helpers the value accessors use ──────────────────────────────────

    def page(self, slug: str) -> bool:
        return slug in self.page_languages

    def page_value(self, slug: str) -> str:
        return ', '.join(self.page_languages.get(slug, ()))

    def names(self, values: List[str]) -> str:
        """``"Main, Auckland +2"`` — a line that stays one line."""
        shown = [value for value in values[: self.NAME_LIMIT] if value]
        extra = len(values) - len(shown)
        return ', '.join(shown) + (f' +{extra}' if extra > 0 else '')

    def setting(self, field: str) -> str:
        return str(getattr(self.settings, field, '') or '')


def _country_name(code: str, language: str) -> str:
    """`NZ` → `New Zealand` / `新西兰`, falling back to the raw code."""
    from .catalog import get_country_profile

    profile = get_country_profile(code)
    if not profile:
        return code
    return profile['name_zh'] if language == 'zh-hans' else profile['name']


def _has_page(slug: str) -> Callable[[Facts], bool]:
    return lambda facts: facts.page(slug)


def _page_value(slug: str) -> Callable[[Facts], str]:
    return lambda facts: facts.page_value(slug)


STEPS: List[Step] = [
    Step(
        key='basics',
        title='Where you trade',
        title_zh='经营地与语言',
        description='Country, currency, language and timezone. Everything else keys off these.',
        description_zh='国家、货币、语言与时区。后面所有设置都以此为准。',
        icon='tabler-world',
        items=[
            Item('basics.country', 'Country set', '已设置国家', GENERAL_LOCALE,
                 lambda f: bool(getattr(f.settings, 'country', '')), from_template=True,
                 value=lambda f: _country_name(f.setting('country'), 'en'),
                 value_zh=lambda f: _country_name(f.setting('country'), 'zh-hans'),
                 hint='Sets the tax defaults and the address format shoppers see.',
                 hint_zh='决定默认税率与买家看到的地址格式。'),
            Item('basics.currency', 'Currency set', '已设置货币', GENERAL_LOCALE,
                 lambda f: bool(f.currency_code), from_template=True,
                 value=lambda f: f.currency_code,
                 hint='Every price on the storefront is shown in this currency.',
                 hint_zh='店铺所有价格都以该货币展示。'),
            Item('basics.currency_row', 'Currency enabled in finance', '货币已在财务中启用',
                 f'{SETTINGS_FINANCE}?tab=currencies',
                 lambda f: f.currency_row, from_template=True,
                 value=lambda f: f.currency_code,
                 hint='Without the row, invoices fall back to whichever currency sorts first.',
                 hint_zh='缺少该记录时，发票会退回到排序最靠前的货币。'),
            Item('basics.language', 'Default language set', '已设置默认语言', GENERAL_LOCALE,
                 lambda f: bool(getattr(f.settings, 'default_language', '')), from_template=True,
                 # Both, because a default of `en` with `zh-hans` also enabled is
                 # a materially different shop from one that only speaks English.
                 value=lambda f: ', '.join(
                     dict.fromkeys([f.setting('default_language'),
                                    *(getattr(f.settings, 'supported_languages', None) or [])])
                 )),
            Item('basics.timezone', 'Timezone set', '已设置时区', GENERAL_LOCALE,
                 lambda f: bool(getattr(f.settings, 'default_timezone', '')), from_template=True,
                 value=lambda f: f.setting('default_timezone'),
                 hint='Order timestamps and scheduled campaigns use it.',
                 hint_zh='订单时间与定时营销活动都按此时区。'),
            Item('basics.site_name', 'Shop name set', '已设置店铺名称', GENERAL_STOREFRONT,
                 lambda f: bool(getattr(f.settings, 'site_name', '')), from_template=True,
                 value=lambda f: f.setting('site_name')),
        ],
    ),
    Step(
        key='brand',
        title='Brand and contact',
        title_zh='品牌与联系方式',
        description='What customers see in the header, the footer and on your invoices.',
        description_zh='买家在页头、页脚与发票上看到的信息。',
        icon='tabler-palette',
        items=[
            Item('brand.logo', 'Logo uploaded', '已上传 Logo', GENERAL_STOREFRONT,
                 lambda f: f.has_logo, required=False,
                 hint='Falls back to the shop name in plain text until you add one.',
                 hint_zh='未上传时页头只显示纯文字店名。'),
            Item('brand.contact_email', 'Contact email set', '已设置联系邮箱', GENERAL_STOREFRONT,
                 lambda f: bool(getattr(f.settings, 'contact_email', '')),
                 value=lambda f: f.setting('contact_email'),
                 hint='Printed on your legal pages and used as the reply-to address.',
                 hint_zh='会印在法务页面上，并作为邮件的回复地址。'),
            Item('brand.contact_phone', 'Contact phone set', '已设置联系电话', GENERAL_STOREFRONT,
                 lambda f: bool(getattr(f.settings, 'contact_phone', '')), required=False,
                 value=lambda f: f.setting('contact_phone')),
        ],
    ),
    Step(
        key='catalogue',
        title='Store and products',
        title_zh='店铺与商品',
        description='The store customers check out against, and something to sell.',
        description_zh='买家下单所对应的店铺，以及可售商品。',
        icon='tabler-building-store',
        items=[
            Item('catalogue.store', 'Active store', '已有启用的店铺', '/admin/store/stores',
                 lambda f: f.has_store, from_template=True,
                 value=lambda f: f.names(f.store_names),
                 hint='Checkout cannot complete without one.',
                 hint_zh='没有店铺时结算流程无法完成。'),
            Item('catalogue.category', 'Product categories', '已有商品分类', '/admin/store/categories',
                 lambda f: f.has_category, from_template=True,
                 value=lambda f: str(f.category_count),
                 hint='The wizard can create a starter set for your industry.',
                 hint_zh='向导可按你的行业创建一套初始分类。'),
            Item('catalogue.product', 'At least one product listed', '至少上架一个商品', '/admin/store/products',
                 lambda f: f.has_product,
                 value=lambda f: str(f.product_count),
                 hint='Only you can add these — the wizard will not invent stock.',
                 hint_zh='这一步只能你自己来，向导不会凭空生成商品。'),
        ],
    ),
    Step(
        key='payments',
        title='Getting paid',
        title_zh='收款',
        description='A payment method, and the tax you charge on top.',
        description_zh='支付方式，以及随单收取的税。',
        icon='tabler-credit-card',
        items=[
            Item('payments.gateway', 'Payment method enabled', '已启用支付方式',
                 f'{SETTINGS_FINANCE}?tab=gateways',
                 lambda f: f.has_gateway,
                 value=lambda f: f.names(f.gateway_names),
                 hint='Needs your own provider keys, so the wizard cannot do this for you.',
                 hint_zh='需要你自己的支付商密钥，向导无法代填。'),
            Item('payments.tax_rate', 'Tax rate configured', '已配置税率', f'{SETTINGS_FINANCE}?tab=tax',
                 lambda f: f.has_tax_rate, from_template=True,
                 value=lambda f: f.names([f'{name} {rate}%' for name, rate in f.tax_rates]),
                 hint='The wizard writes your country default — check it before you launch.',
                 hint_zh='向导会写入该国默认税率，上线前请自行复核。'),
            Item('payments.invoice_prefix', 'Invoice numbering set', '已设置发票编号规则',
                 f'{SETTINGS_FINANCE}?tab=invoice',
                 lambda f: bool(f.invoice.get('invoice_prefix')), required=False,
                 value=lambda f: str(f.invoice.get('invoice_prefix') or '')),
        ],
    ),
    Step(
        key='delivery',
        title='Delivery',
        title_zh='配送',
        description='Where orders ship from, who carries them, and where they can go.',
        description_zh='从哪里发货、谁来配送、能送到哪里。',
        icon='tabler-truck',
        items=[
            Item('delivery.warehouse', 'Warehouse added', '已添加仓库', f'{SETTINGS_DELIVERY}?tab=warehouses',
                 lambda f: f.has_warehouse, from_template=True,
                 value=lambda f: f.names(f.warehouse_names),
                 hint='Stock lives in a warehouse; freight quotes start from its address.',
                 hint_zh='库存挂在仓库上，运费也从仓库地址起算。'),
            # The wizard can create the warehouse row but cannot know where it
            # is, and an unaddressed warehouse quotes no freight and prints no
            # return address. Separate row so "created" and "usable" are not
            # conflated into one tick.
            Item('delivery.warehouse_address', 'Warehouse address filled in', '已填写仓库地址',
                 f'{SETTINGS_DELIVERY}?tab=warehouses',
                 lambda f: bool(f.warehouse_address),
                 value=lambda f: f.warehouse_address,
                 hint='Freight quotes start here, and it is the return address printed on your policies.',
                 hint_zh='运费从这个地址起算，也是印在退换货政策上的退货地址。'),
            Item('delivery.carrier', 'Carrier configured', '已配置承运商', f'{SETTINGS_DELIVERY}?tab=carriers',
                 lambda f: f.has_carrier,
                 value=lambda f: f.names(f.carrier_names),
                 hint='Live rates and tracking need the carrier’s own credentials.',
                 hint_zh='实时运费与轨迹查询需要承运商自己的凭据。'),
            Item('delivery.zone', 'Delivery zone defined', '已定义配送区域', f'{SETTINGS_DELIVERY}?tab=zones',
                 lambda f: f.has_zone, from_template=True,
                 value=lambda f: f.names(f.zone_names)),
            Item('delivery.freight', 'Free-shipping threshold set', '已设置包邮门槛',
                 f'{SETTINGS_DELIVERY}?tab=delivery',
                 lambda f: f.delivery_settings.get('free_shipping_threshold') is not None,
                 required=False,
                 value=lambda f: f'{f.delivery_settings.get("free_shipping_threshold")} {f.currency_code}'.strip()),
        ],
    ),
    Step(
        key='content',
        title='Pages and policies',
        title_zh='页面与政策',
        description='The pages shoppers look for before they trust you with a card.',
        description_zh='买家在付款前会去翻的那几页。',
        icon='tabler-file-text',
        items=[
            # Created automatically once the workspace has a hostname: web.Site
            # keys off a globally unique domain, so it cannot exist before one.
            Item('content.site', 'Storefront site configured', '已配置站点', f'{SETTINGS_WEB}?tab=sites',
                 lambda f: f.site is not None, required=False,
                 value=lambda f: getattr(f.site, 'domain', ''),
                 hint='Created for you as soon as a domain is connected.',
                 hint_zh='绑定域名后会自动创建。'),
            Item('content.home', 'Home page published', '首页已发布', f'{SETTINGS_WEB}?tab=pages',
                 _has_page('home'), from_template=True, value=_page_value('home'),
                 hint='Otherwise the storefront renders a bare welcome message.',
                 hint_zh='否则店铺首页只会显示一句欢迎语。'),
            Item('content.about', 'About page published', '关于我们已发布', f'{SETTINGS_WEB}?tab=pages',
                 _has_page('about'), required=False, from_template=True, value=_page_value('about')),
            Item('content.contact', 'Contact page published', '联系我们已发布', f'{SETTINGS_WEB}?tab=pages',
                 _has_page('contact'), from_template=True, value=_page_value('contact')),
            Item('content.privacy', 'Privacy policy published', '隐私政策已发布', f'{SETTINGS_WEB}?tab=pages',
                 _has_page('privacy'), from_template=True, value=_page_value('privacy'),
                 hint='Payment providers and app stores both ask for this URL.',
                 hint_zh='支付服务商与应用商店都会索取该页面链接。'),
            Item('content.terms', 'Terms of service published', '服务条款已发布', f'{SETTINGS_WEB}?tab=pages',
                 _has_page('terms'), from_template=True, value=_page_value('terms')),
            Item('content.returns', 'Returns policy published', '退换货政策已发布', f'{SETTINGS_WEB}?tab=pages',
                 _has_page('returns'), from_template=True, value=_page_value('returns')),
            Item('content.delivery', 'Delivery policy published', '配送说明已发布', f'{SETTINGS_WEB}?tab=pages',
                 _has_page('delivery'), from_template=True, value=_page_value('delivery')),
            Item('content.menu_header', 'Header navigation', '已配置顶部导航', f'{SETTINGS_WEB}?tab=menus',
                 lambda f: 'header' in f.menu_locations, from_template=True,
                 value=lambda f: str(f.menu_item_counts.get('header', 0)),
                 hint='An empty header is the most common "the site looks broken" report.',
                 hint_zh='导航为空是最常见的“页面看起来坏了”反馈。'),
            Item('content.menu_footer', 'Footer navigation', '已配置页脚导航', f'{SETTINGS_WEB}?tab=menus',
                 lambda f: 'footer' in f.menu_locations, from_template=True,
                 value=lambda f: str(f.menu_item_counts.get('footer', 0))),
        ],
    ),
    Step(
        key='launch',
        title='Go live',
        title_zh='上线',
        description='The last few things, none of which a template can guess.',
        description_zh='最后几项，都是模板猜不出来的。',
        icon='tabler-rocket',
        items=[
            Item('launch.email_config', 'Outgoing email configured', '已配置发信服务',
                 f'{SETTINGS_GENERAL}?tab=email',
                 lambda f: f.has_email_config,
                 value=lambda f: getattr(f.email_config, 'name', '') or getattr(f.email_config, 'backend_type', ''),
                 hint='Order confirmations and password resets silently go nowhere without it.',
                 hint_zh='未配置时订单确认与密码重置邮件会静默发不出去。'),
            Item('launch.domain', 'Custom domain connected', '已绑定自有域名', f'{SETTINGS_WEB}?tab=sites',
                 lambda f: f.has_domain,
                 value=lambda f: getattr(f.domain, 'hostname', ''),
                 hint='DNS and the hosting alias are set outside this admin — ask your operator.',
                 hint_zh='DNS 与托管别名需在后台之外配置，请联系运维。'),
            Item('launch.staff', 'Someone else invited', '已邀请其他成员', f'{SETTINGS_GENERAL}?tab=users',
                 lambda f: f.has_staff, required=False,
                 value=lambda f: str(f.staff_count),
                 hint='So the shop does not stop when you are on holiday.',
                 hint_zh='避免你休假时店铺无人打理。'),
            Item('launch.analytics', 'Analytics connected', '已接入统计分析',
                 GENERAL_STOREFRONT,
                 lambda f: bool(f.analytics.get('google_analytics_id')), required=False,
                 value=lambda f: str(f.analytics.get('google_analytics_id') or '')),
        ],
    ),
]

def resolved_steps() -> List[Step]:
    """BFG's steps plus whatever the installed apps contribute.

    Contributed rows are appended to the step they name, so an app's checks sit
    with the ones they belong next to rather than in a bolted-on section at the
    bottom. A contribution naming a step that does not exist becomes its own
    step instead of being dropped silently.
    """
    from .extensions import collect

    extra_steps, contributed_items, _patches = collect()
    known = {step.key for step in STEPS}

    merged = [
        Step(
            key=step.key, title=step.title, title_zh=step.title_zh,
            description=step.description, description_zh=step.description_zh,
            icon=step.icon,
            items=[*step.items, *contributed_items.get(step.key, ())],
        )
        for step in STEPS
    ]
    merged.extend(extra_steps)

    orphaned = {
        key: items for key, items in contributed_items.items()
        if key not in known and key not in {step.key for step in extra_steps}
    }
    for key, items in orphaned.items():
        merged.append(Step(
            key=key, title=key.replace('_', ' ').title(), title_zh=key,
            description='', description_zh='', icon='tabler-puzzle', items=list(items),
        ))
    return merged


def items_by_key() -> Dict[str, Item]:
    return {item.key: item for step in resolved_steps() for item in step.items}


def template_item_keys() -> tuple:
    """Items an ``apply`` of a country/industry template is expected to satisfy."""
    return tuple(key for key, item in items_by_key().items() if item.from_template)


#: BFG's own items only. Use ``items_by_key()`` for the full, contributed list.
ITEMS_BY_KEY: Dict[str, Item] = {
    item.key: item for step in STEPS for item in step.items
}


def _percent(done: int, total: int) -> int:
    """Round *down*, except never report 100% while something is outstanding.

    A checklist that says 100% with two red rows on screen destroys trust in the
    number; 99% with two red rows is merely annoying.
    """
    if total <= 0:
        return 100
    if done >= total:
        return 100
    return min(99, int(done * 100 / total))


#: Values in a step's one-line digest before it is truncated.
SUMMARY_LIMIT = 4


def _read_value(accessor, facts) -> str:
    """A value is cosmetic; a contributed accessor that throws must not 500 the page."""
    if accessor is None:
        return ''
    try:
        return str(accessor(facts) or '').strip()
    except Exception:  # pragma: no cover - defensive
        logger.exception('Onboarding value accessor failed')
        return ''


def _summarise(values) -> str:
    """Distinct values, in order, capped to one line.

    De-duplicated because neighbouring rows legitimately report the same thing —
    "currency set" and "currency enabled in finance" are both NZD, and seven
    published pages are all "en". Without this the digest spent its four slots
    saying NZD twice and dropped the timezone.
    """
    distinct = list(dict.fromkeys(value for value in values if value))
    shown = distinct[:SUMMARY_LIMIT]
    extra = len(distinct) - len(shown)
    return ' · '.join(shown) + (f' +{extra}' if extra > 0 else '')


def evaluate(workspace, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run every check against ``workspace`` and return the UI's whole payload.

    ``state`` is ``Settings.custom_settings['onboarding']`` — it carries the
    items the user chose to skip and the industry they picked. Skipped items
    count as satisfied for the percentage (the user made a decision; nagging
    them about it is how checklists get ignored) but stay flagged in the list.
    """
    facts = Facts(workspace)
    steps = resolved_steps()
    state = state if state is not None else facts.state
    skipped = set(state.get('skipped') or [])
    # An industry with no shipping (services) drops the delivery rows entirely
    # rather than leaving a step that can never go green.
    hidden = set(state.get('hidden') or [])

    steps_payload: List[Dict[str, Any]] = []
    required_done = required_total = 0
    optional_done = optional_total = 0

    for step in steps:
        items_payload = []
        step_done = step_total = 0
        for item in step.items:
            if item.key in hidden:
                continue
            is_skipped = item.key in skipped
            done = bool(item.check(facts))
            satisfied = done or is_skipped
            # Only read once the item is done: a value accessor may assume the
            # row it reads exists, which is exactly what `check` established.
            value = _read_value(item.value, facts) if done else ''
            value_zh = (_read_value(item.value_zh, facts) if done else '') or value
            items_payload.append({
                'key': item.key,
                'label': item.label,
                'label_zh': item.label_zh,
                'hint': item.hint,
                'hint_zh': item.hint_zh,
                'href': item.href,
                'required': item.required,
                'from_template': item.from_template,
                'done': done,
                'skipped': is_skipped,
                'value': value,
                'value_zh': value_zh,
            })
            if item.required:
                required_total += 1
                required_done += 1 if satisfied else 0
                step_total += 1
                step_done += 1 if satisfied else 0
            else:
                optional_total += 1
                optional_done += 1 if satisfied else 0

        if not items_payload:
            continue
        # A one-line digest of what the step is set to, so a collapsed category
        # already answers "what did I configure" — the whole point of a summary
        # is not having to open all seven of them.
        summary = _summarise(item['value'] for item in items_payload)
        summary_zh = _summarise(item['value_zh'] for item in items_payload)
        steps_payload.append({
            'key': step.key,
            'title': step.title,
            'title_zh': step.title_zh,
            'description': step.description,
            'description_zh': step.description_zh,
            'icon': step.icon,
            'summary': summary,
            'summary_zh': summary_zh,
            'percent': _percent(step_done, step_total),
            'done_count': step_done,
            'total_count': step_total,
            'complete': step_total > 0 and step_done >= step_total,
            'items': items_payload,
        })

    return {
        'percent': _percent(required_done, required_total),
        'required_done': required_done,
        'required_total': required_total,
        'optional_done': optional_done,
        'optional_total': optional_total,
        'complete': required_total > 0 and required_done >= required_total,
        'steps': steps_payload,
        'state': {
            'country': state.get('country') or getattr(facts.settings, 'country', '') or '',
            'industry': state.get('industry') or '',
            'applied_at': state.get('applied_at') or '',
            'dismissed': bool(state.get('dismissed')),
            'skipped': sorted(skipped),
        },
    }
