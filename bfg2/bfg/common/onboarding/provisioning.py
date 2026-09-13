# -*- coding: utf-8 -*-
"""
The rows a workspace needs before its storefront works, one idempotent step each.

``WorkspaceService.create_workspace`` leaves a workspace with default settings,
no store and possibly no row for its currency, and each gap fails quietly (see
``provision_workspace``). The ``provision_workspace`` command and the platform's
``POST /api/v1/platform/workspaces/`` fill them in with these steps.

Every step names the workspace it works on and reaches tenant-scoped models
through ``all_objects``, so none depends on a workspace being bound to the
thread: the command runs outside any request, and platform endpoints bind none.
"""

from typing import TYPE_CHECKING, Iterable, List, Optional, Tuple

from bfg.common.models import Settings
from bfg.common.onboarding.catalog import get_currency_profile

if TYPE_CHECKING:
    from bfg.shop.models import Store

DEFAULT_STORE_CODE = 'main'
DEFAULT_STORE_NAME = 'Main'


def ensure_settings(
    workspace,
    *,
    country: str = '',
    currency: str = '',
    language: str = '',
    languages: Iterable[str] = (),
    site_name: str = '',
    dry_run: bool = False,
) -> Tuple[Settings, List[str]]:
    """Set the workspace's country, currency and language.

    A blank value leaves its field alone, ``languages`` replaces the supported
    languages when it lists any, and ``site_name`` only fills a blank one.
    Returns the settings row and what changed on it, as ``field=value`` or, for
    the name, ``site_name``. With ``dry_run`` the changes are made to the row but
    not saved, though a workspace with no settings row still gets one.
    """
    settings_obj, _ = Settings.objects.get_or_create(workspace=workspace)
    changed = []
    for field, value in (
        ('country', (country or '').strip().upper()[:2]),
        ('default_currency', (currency or '').strip().upper()[:3]),
        ('default_language', (language or '').strip()),
    ):
        if value and getattr(settings_obj, field) != value:
            setattr(settings_obj, field, value)
            changed.append(f'{field}={value}')
    languages = list(languages)
    if languages and settings_obj.supported_languages != languages:
        settings_obj.supported_languages = languages
        changed.append(f'supported_languages={languages}')
    if not settings_obj.site_name and site_name:
        settings_obj.site_name = site_name[:255]
        changed.append('site_name')
    if changed and not dry_run:
        settings_obj.save()
    return settings_obj, changed


def ensure_currency(code: str, *, dry_run: bool = False) -> bool:
    """Make sure ``code`` exists as an active ``finance.Currency`` row.

    ``OrderService`` looks the code up and, when it is missing, falls back to the
    first active currency instead of creating it — so an NZD workspace writes CNY
    invoices. The row is global, not per workspace, so a disabled one is switched
    back on rather than duplicated. Returns whether the row had to be written;
    with ``dry_run`` nothing is.
    """
    from bfg.finance.models import Currency

    code = (code or '').strip().upper()[:3]
    if not code or Currency.objects.filter(code=code, is_active=True).exists():
        return False
    if not dry_run:
        profile = get_currency_profile(code)
        Currency.objects.update_or_create(
            code=code,
            defaults={
                'name': profile['name'],
                'symbol': profile['symbol'],
                'decimal_places': profile['decimal_places'],
                'is_active': True,
            },
        )
    return True


def ensure_store(
    workspace,
    *,
    name: str = DEFAULT_STORE_NAME,
    code: str = DEFAULT_STORE_CODE,
    dry_run: bool = False,
) -> Tuple[Optional['Store'], bool]:
    """Make sure the workspace has a store with ``code``.

    Without one, ``/store/cart/default_store/`` 404s and checkout cannot complete.
    Returns ``(store, created)``. With ``dry_run`` a missing store is not created
    and comes back as ``(None, True)``.
    """
    from bfg.shop.models import Store

    store = Store.all_objects.filter(workspace=workspace, code=code).first()
    if store:
        return store, False
    if dry_run:
        return None, True
    return Store.all_objects.create(workspace=workspace, name=name, code=code, is_active=True), True
