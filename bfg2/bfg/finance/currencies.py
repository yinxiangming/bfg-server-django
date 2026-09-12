"""
Which currencies a workspace offers.

Currency rows are platform-wide. A workspace picks from them through
``Settings.enabled_currencies``:

* An empty list means every active currency. That is how every workspace
  behaved before shops could choose.
* The workspace's default currency is always in the list; ``Settings.save``
  sees to that.
"""

from typing import List, Optional, Set

from bfg.finance.models import Currency


def enabled_currency_codes(workspace) -> Optional[Set[str]]:
    """The codes the workspace offers, or None when it offers every active currency."""
    from bfg.common.models import Settings

    if workspace is None:
        return None
    codes = Settings.objects.filter(workspace=workspace).values_list('enabled_currencies', flat=True).first()
    return set(codes) if codes else None


def set_currency_enabled(workspace, currency: Currency, enabled: bool) -> List[str]:
    """Switch one currency on or off for the workspace and return the codes it now offers.

    An empty result still means every active currency. Raises ValueError when asked to
    switch off the workspace's default currency.
    """
    from bfg.common.models import Settings

    settings_obj, _ = Settings.objects.get_or_create(workspace=workspace)
    if not enabled and currency.code == settings_obj.default_currency:
        raise ValueError(
            f"{currency.code} is this shop's default currency. "
            f"Choose another default currency before switching it off."
        )

    codes = list(settings_obj.enabled_currencies or [])
    if not codes:
        if enabled:
            return []  # every active currency is already offered
        # The first currency switched off turns "all of them" into an explicit list.
        codes = list(Currency.objects.filter(is_active=True).values_list('code', flat=True))

    if enabled and currency.code not in codes:
        codes.append(currency.code)
    elif not enabled:
        codes = [code for code in codes if code != currency.code]

    settings_obj.enabled_currencies = codes
    settings_obj.save(update_fields=['enabled_currencies', 'updated_at'])
    return settings_obj.enabled_currencies
