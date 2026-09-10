# -*- coding: utf-8 -*-
"""
Country and industry profiles the setup wizard picks defaults from.

Everything here is a *default*, not a fact the platform enforces: tax rates in
particular move, and several countries (US, MY) have no single national rate at
all. The wizard writes them as an editable ``finance.TaxRate`` row and tells the
user to check it, rather than pretending to be a tax engine.

Only languages the client actually ships translations for ('en', 'zh-hans') are
ever suggested — offering 'ja' here would produce a storefront whose category
queries return nothing, which is exactly the failure ``provision_workspace``
documents.
"""

from typing import Any, Dict, List, Optional

SUPPORTED_LANGUAGES = ('en', 'zh-hans')

#: ISO 4217 → the fields ``finance.Currency`` needs to create a row.
#: ``finance.seed_data`` only creates USD/EUR/GBP/CNY and ``OrderService`` falls
#: back to "first active currency" rather than creating the missing one, so a
#: NZD workspace silently invoices in CNY unless the row is made up front.
CURRENCY_PROFILES: Dict[str, Dict[str, Any]] = {
    'AED': {'name': 'UAE Dirham', 'symbol': 'د.إ', 'decimal_places': 2},
    'AUD': {'name': 'Australian Dollar', 'symbol': 'A$', 'decimal_places': 2},
    'CAD': {'name': 'Canadian Dollar', 'symbol': 'C$', 'decimal_places': 2},
    'CHF': {'name': 'Swiss Franc', 'symbol': 'CHF', 'decimal_places': 2},
    'CNY': {'name': 'Chinese Yuan', 'symbol': '¥', 'decimal_places': 2},
    'EUR': {'name': 'Euro', 'symbol': '€', 'decimal_places': 2},
    'GBP': {'name': 'Pound Sterling', 'symbol': '£', 'decimal_places': 2},
    'HKD': {'name': 'Hong Kong Dollar', 'symbol': 'HK$', 'decimal_places': 2},
    'IDR': {'name': 'Indonesian Rupiah', 'symbol': 'Rp', 'decimal_places': 0},
    'INR': {'name': 'Indian Rupee', 'symbol': '₹', 'decimal_places': 2},
    'JPY': {'name': 'Japanese Yen', 'symbol': '¥', 'decimal_places': 0},
    'KRW': {'name': 'South Korean Won', 'symbol': '₩', 'decimal_places': 0},
    'MYR': {'name': 'Malaysian Ringgit', 'symbol': 'RM', 'decimal_places': 2},
    'NZD': {'name': 'New Zealand Dollar', 'symbol': 'NZ$', 'decimal_places': 2},
    'PHP': {'name': 'Philippine Peso', 'symbol': '₱', 'decimal_places': 2},
    'SGD': {'name': 'Singapore Dollar', 'symbol': 'S$', 'decimal_places': 2},
    'THB': {'name': 'Thai Baht', 'symbol': '฿', 'decimal_places': 2},
    'TWD': {'name': 'New Taiwan Dollar', 'symbol': 'NT$', 'decimal_places': 2},
    'USD': {'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2},
    'VND': {'name': 'Vietnamese Dong', 'symbol': '₫', 'decimal_places': 0},
}


def _country(name, name_zh, currency, timezone, language, tax_name, tax_rate,
             jurisdiction=None, tax_note='', tax_note_zh=''):
    return {
        'name': name,
        'name_zh': name_zh,
        'currency': currency,
        'timezone': timezone,
        'default_language': language,
        # Every shop gets English alongside its own language: the admin UI and
        # half the block copy fall back to 'en', and a single-language zh-hans
        # site loses the fallback entirely.
        'languages': [language] if language == 'en' else [language, 'en'],
        'tax': {
            'name': tax_name,
            'rate': tax_rate,
            'note': tax_note,
            'note_zh': tax_note_zh,
        },
        'jurisdiction': jurisdiction or name,
    }


#: ISO 3166-1 alpha-2 → storefront defaults. Ordered roughly by how often this
#: platform is deployed into each market.
COUNTRY_PROFILES: Dict[str, Dict[str, Any]] = {
    'NZ': _country('New Zealand', '新西兰', 'NZD', 'Pacific/Auckland', 'en', 'GST', '15.00'),
    'AU': _country('Australia', '澳大利亚', 'AUD', 'Australia/Sydney', 'en', 'GST', '10.00'),
    'CN': _country('China', '中国大陆', 'CNY', 'Asia/Shanghai', 'zh-hans', '增值税', '13.00',
                   jurisdiction='the People’s Republic of China',
                   tax_note='13% is the standard rate for goods; services and small-scale taxpayers differ.',
                   tax_note_zh='13% 为货物标准税率，服务业与小规模纳税人适用其他税率。'),
    'HK': _country('Hong Kong SAR', '中国香港', 'HKD', 'Asia/Hong_Kong', 'zh-hans', 'Sales Tax', '0.00',
                   tax_note='Hong Kong levies no general sales tax or VAT.',
                   tax_note_zh='香港不征收一般销售税或增值税。'),
    'TW': _country('Taiwan', '中国台湾', 'TWD', 'Asia/Taipei', 'zh-hans', '營業稅', '5.00'),
    'SG': _country('Singapore', '新加坡', 'SGD', 'Asia/Singapore', 'en', 'GST', '9.00'),
    'MY': _country('Malaysia', '马来西亚', 'MYR', 'Asia/Kuala_Lumpur', 'en', 'SST', '10.00',
                   tax_note='Sales tax on goods is 5% or 10% depending on the tariff code; service tax differs again.',
                   tax_note_zh='货物销售税按税则为 5% 或 10%，服务税另计。'),
    'US': _country('United States', '美国', 'USD', 'America/New_York', 'en', 'Sales Tax', '0.00',
                   tax_note='There is no federal sales tax; rates are set per state and often per city.',
                   tax_note_zh='美国无联邦销售税，税率按州甚至按市设定。'),
    'CA': _country('Canada', '加拿大', 'CAD', 'America/Toronto', 'en', 'GST', '5.00',
                   tax_note='5% federal GST; most provinces add PST or charge a combined HST.',
                   tax_note_zh='联邦 GST 为 5%，多数省份另征 PST 或合并为 HST。'),
    'GB': _country('United Kingdom', '英国', 'GBP', 'Europe/London', 'en', 'VAT', '20.00'),
    'IE': _country('Ireland', '爱尔兰', 'EUR', 'Europe/Dublin', 'en', 'VAT', '23.00'),
    'DE': _country('Germany', '德国', 'EUR', 'Europe/Berlin', 'en', 'VAT', '19.00'),
    'FR': _country('France', '法国', 'EUR', 'Europe/Paris', 'en', 'VAT', '20.00'),
    'NL': _country('Netherlands', '荷兰', 'EUR', 'Europe/Amsterdam', 'en', 'VAT', '21.00'),
    'ES': _country('Spain', '西班牙', 'EUR', 'Europe/Madrid', 'en', 'VAT', '21.00'),
    'IT': _country('Italy', '意大利', 'EUR', 'Europe/Rome', 'en', 'VAT', '22.00'),
    'CH': _country('Switzerland', '瑞士', 'CHF', 'Europe/Zurich', 'en', 'VAT', '8.10'),
    'JP': _country('Japan', '日本', 'JPY', 'Asia/Tokyo', 'en', '消費税', '10.00',
                   tax_note='8% reduced rate applies to food and drink other than alcohol and dining out.',
                   tax_note_zh='食品饮料（酒类与堂食除外）适用 8% 轻减税率。'),
    'KR': _country('South Korea', '韩国', 'KRW', 'Asia/Seoul', 'en', 'VAT', '10.00'),
    'AE': _country('United Arab Emirates', '阿联酋', 'AED', 'Asia/Dubai', 'en', 'VAT', '5.00'),
    'TH': _country('Thailand', '泰国', 'THB', 'Asia/Bangkok', 'en', 'VAT', '7.00'),
    'VN': _country('Vietnam', '越南', 'VND', 'Asia/Ho_Chi_Minh', 'en', 'VAT', '10.00'),
    'ID': _country('Indonesia', '印度尼西亚', 'IDR', 'Asia/Jakarta', 'en', 'PPN', '11.00'),
    'PH': _country('Philippines', '菲律宾', 'PHP', 'Asia/Manila', 'en', 'VAT', '12.00'),
    'IN': _country('India', '印度', 'INR', 'Asia/Kolkata', 'en', 'GST', '18.00',
                   tax_note='GST is slabbed at 0/5/12/18/28% by HSN code; 18% is the most common.',
                   tax_note_zh='GST 按 HSN 编码分为 0/5/12/18/28% 档，18% 最常见。'),
}

#: Industry keys the wizard offers. ``template`` is the JSON file under
#: ``data/industry/`` that supplies categories and page copy; several industries
#: deliberately share one.
INDUSTRIES: List[Dict[str, Any]] = [
    {'key': 'general_retail', 'name': 'General retail', 'name_zh': '综合零售',
     'icon': 'tabler-building-store',
     'description': 'A bit of everything — the safe default.',
     'description_zh': '什么都卖一点，拿不准时选它。'},
    {'key': 'fashion', 'name': 'Fashion & accessories', 'name_zh': '服饰鞋包',
     'icon': 'tabler-shirt',
     'description': 'Clothing, footwear, bags. Size and colour variants.',
     'description_zh': '服装、鞋履、箱包，商品多规格多颜色。'},
    {'key': 'beauty', 'name': 'Beauty & personal care', 'name_zh': '美妆个护',
     'icon': 'tabler-sparkles',
     'description': 'Cosmetics and skincare, with batch and expiry tracking.',
     'description_zh': '彩妆护肤，关注批次与保质期。'},
    {'key': 'food', 'name': 'Food & grocery', 'name_zh': '食品生鲜',
     'icon': 'tabler-apple',
     'description': 'Perishables and packaged food; delivery windows matter.',
     'description_zh': '生鲜与包装食品，重视配送时效。'},
    {'key': 'electronics', 'name': 'Electronics', 'name_zh': '数码家电',
     'icon': 'tabler-device-laptop',
     'description': 'High-value goods with serial numbers and warranties.',
     'description_zh': '高客单价，需要序列号与保修管理。'},
    {'key': 'home_living', 'name': 'Home & living', 'name_zh': '家居生活',
     'icon': 'tabler-sofa',
     'description': 'Furniture and homeware; bulky freight.',
     'description_zh': '家具家居，大件物流。'},
    {'key': 'health', 'name': 'Health & supplements', 'name_zh': '保健营养',
     'icon': 'tabler-heartbeat',
     'description': 'Supplements and wellness, often cross-border.',
     'description_zh': '保健品与营养品，常涉及跨境。'},
    {'key': 'sports_outdoor', 'name': 'Sports & outdoor', 'name_zh': '运动户外',
     'icon': 'tabler-ball-football',
     'description': 'Gear and apparel for sport and the outdoors.',
     'description_zh': '运动装备与户外用品。'},
    {'key': 'mother_baby', 'name': 'Mother & baby', 'name_zh': '母婴用品',
     'icon': 'tabler-baby-carriage',
     'description': 'Formula, nappies, toys. Trust and traceability first.',
     'description_zh': '奶粉、纸尿裤、玩具，重视溯源与信任。'},
    {'key': 'services', 'name': 'Services & bookings', 'name_zh': '服务预约',
     'icon': 'tabler-calendar-check',
     'description': 'Appointments rather than parcels — no shipping step.',
     'description_zh': '以预约为主，没有实物发货。'},
    {'key': 'b2b_wholesale', 'name': 'B2B wholesale', 'name_zh': 'B2B 批发',
     'icon': 'tabler-forklift',
     'description': 'Trade pricing, quotes and invoices over card checkout.',
     'description_zh': '批发定价、报价与对公开票为主。'},
]

INDUSTRY_KEYS = tuple(item['key'] for item in INDUSTRIES)

DEFAULT_COUNTRY = 'NZ'
DEFAULT_INDUSTRY = 'general_retail'


def get_country_profile(code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Profile for an ISO alpha-2 code, or None when it is not one we know."""
    if not code:
        return None
    return COUNTRY_PROFILES.get(code.strip().upper()[:2])


def get_industry(key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    key = key.strip().lower()
    for item in INDUSTRIES:
        if item['key'] == key:
            return item
    return None


def get_currency_profile(code: Optional[str]) -> Dict[str, Any]:
    """Never returns None: an unknown code becomes a row using the code itself.

    A row with a clumsy symbol is still a working currency; no row at all sends
    invoices to whatever currency happens to sort first.
    """
    code = (code or '').strip().upper()[:3]
    profile = CURRENCY_PROFILES.get(code)
    if profile:
        return {'code': code, **profile}
    return {'code': code, 'name': code, 'symbol': code, 'decimal_places': 2}


def country_options() -> List[Dict[str, Any]]:
    """Country list for the wizard's first dropdown, alphabetical by code."""
    return [
        {
            'code': code,
            'name': profile['name'],
            'name_zh': profile['name_zh'],
            'currency': profile['currency'],
            'timezone': profile['timezone'],
            'default_language': profile['default_language'],
            'languages': profile['languages'],
            'tax': profile['tax'],
        }
        for code, profile in sorted(COUNTRY_PROFILES.items())
    ]
