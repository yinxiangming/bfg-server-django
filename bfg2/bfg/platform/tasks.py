# -*- coding: utf-8 -*-
"""
The billing month, as work a scheduler can run.

Each of these is a thin wrapper over the service the matching management command
calls, so a deployment with a scheduler and one without do the same thing and
there is one implementation to reason about. Nothing here decides *when*: the
schedule belongs to the deployment, which is what knows its own timezone, its
month end, and whether it wants any of this automatic at all. See
``bfg/docs/reference/server-switches.md``.

All three are safe to run twice, because the work underneath is: an entitlement
lapses on time rather than on being swept, a rate is stored under the day the
bank published it, and an invoice number is unique per workspace and month.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def close_entitlement_periods():
    """Move entitlements past their period into grace, and past their grace into ended.

    Running it late delays the pause, not the expiry.
    """
    from bfg.platform.services.entitlements import close_due_periods

    return close_due_periods()


@shared_task
def refresh_exchange_rates():
    """Store the day's published reference rates.

    Answers how many were stored. A refresh that fails writes nothing and leaves
    the rates already on file, which is what conversions then use — so this is
    worth running well before bills are issued rather than beside them.
    """
    from bfg.platform.services.exchange_rates import refresh_rates

    return refresh_rates()


@shared_task
def issue_monthly_bills(month=None):
    """Bill every workspace for the month that has just ended.

    ``month`` is any date inside the month to bill; left empty, the one before
    this, which is what a run at the start of a month wants. A workspace already
    billed for that month is not billed again — the invoice number says which
    month it is for, and the database refuses the second. Answers the invoice ids
    it wrote, because an invoice does not survive being handed to a result backend.
    """
    from bfg.platform.services.billing import issue_monthly_bills as issue

    return [invoice.pk for invoice in issue(month)]
