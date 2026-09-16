# -*- coding: utf-8 -*-
"""
What the platform listens for.

A settled platform bill is what writes the period it bought — the next one for
everything a month's bill renewed, or the first one for an add-on just acquired;
see ``services.renewals``. Everything here lives on the platform side rather than
finance calling into renewals: finance is the lower layer and knows nothing about
who sells to whom.

A bill is settled three ways, and each has its own way of being heard:

``payment.completed``  a payment settled through a gateway. Kept because it is the
                       event a deployment's own gateway integrations already emit.
``invoice.paid``       an invoice reached ``paid`` through one of finance's own
                       services. It is the event that means what is acted on here,
                       and the only one for money taken outside a gateway: a bank
                       transfer reconciled by hand has no ``Payment`` row for
                       ``payment.completed`` to carry. Emitted by both
                       ``InvoiceService.mark_as_paid`` and the gateway path, so a
                       card payment is heard on both events.
``post_save``          the status written straight onto the row — which is what the
                       invoice editor does, since ``status`` is a writable field on
                       ``InvoiceDetailSerializer``. No service is involved and no
                       event is emitted, so the model's own signal is the only
                       place to hear it. This is the ordinary way a transfer is
                       confirmed on this product, so it cannot be the path that is
                       left out.

Making ``status`` read-only on the serializer would have removed the third path
instead of covering it, and would have been a breaking change to a shared
library's public API: a deployment that has always settled bills by writing the
field would have started getting 400s. Hearing the write is additive and costs
whoever does not care nothing.

Hearing a bill settle more than once is free by design: ``renew_for_invoice`` is
idempotent, so an extra report finds the period already written. That is also why
the receiver does not try to tell "just became paid" from "was already paid and
something else about the row changed" — re-running on an unrelated edit of a paid
invoice writes nothing.

Only the invoice's id is carried across the commit. An event and a signal both
hand over a model instance, and by the time the renewal runs the row has been
written; reloading is what makes sure a bill cancelled in between is not renewed
anyway.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from bfg.core.events import after_commit, global_dispatcher
from bfg.platform.services.billing import is_platform_bill

logger = logging.getLogger(__name__)

INVOICE_PAID = "invoice.paid"
PAYMENT_COMPLETED = "payment.completed"

# The status that means the bill has been settled, as ``finance.Invoice`` spells it.
PAID = "paid"


def _renew(invoice_id):
    """Queue the renewal of one invoice for after the commit.

    Queued rather than run, like the rest of the library's listeners: the status
    that decides whether anything is renewed is written in the transaction this
    runs inside, and a renewal that read it before the commit would either see the
    bill unpaid or write a period for a payment that was then rolled back.
    ``after_commit`` also logs whatever the renewal raises rather than re-raising
    it, which is what keeps a failed renewal from being reported to the payer as a
    failed payment.
    """
    if not invoice_id:
        return

    from bfg.platform.services.renewals import renew_for_invoice

    after_commit(renew_for_invoice, invoice_id)


def on_invoice_paid(event_data):
    """Renew what a bill bought, whichever of finance's services settled it."""
    invoice = (event_data.get("data") or {}).get("invoice")
    _renew(getattr(invoice, "pk", None))


def on_payment_completed(event_data):
    """Renew what a paid bill bought, for money taken through a gateway.

    Every completed payment the deployment takes arrives here, so the cheap part
    comes first: a payment against an order rather than an invoice is not one of
    ours and costs nothing to rule out. Everything else is left to
    ``renew_for_invoice``, which reads the invoice back and leaves alone anything
    that is not a paid platform bill.
    """
    payment = (event_data.get("data") or {}).get("payment")
    _renew(getattr(payment, "invoice_id", None))


@receiver(post_save, sender="finance.Invoice", dispatch_uid="platform_renew_on_invoice_saved")
def on_invoice_saved(sender, instance, raw=False, **kwargs):
    """Renew what a bill bought when its status was written straight onto the row.

    This runs on every invoice every deployment saves, whosever it is, so it may
    not cost a query to say no. Both tests are on the instance already in hand: the
    status, and whether the number is one ``billing`` issued, of either shape —
    which is a string the invoice is carrying, not a workspace to look up. Only a
    paid platform bill gets as far as queueing anything, and the queued work is the
    same ``renew_for_invoice`` the events go through, so this path is a way of
    hearing rather than a second way of writing a period.

    Fixtures are skipped: ``raw`` means the row is being loaded rather than
    settled, and half a database is no state to renew from.

    A queryset ``update()`` sends no ``post_save``, so a bill settled that way is
    still only heard if something emits ``invoice.paid`` for it. Nothing in this
    library settles an invoice that way.
    """
    if raw or instance.status != PAID:
        return
    if not is_platform_bill(instance.invoice_number):
        return
    _renew(instance.pk)


def register_event_handlers():
    """Register the platform's event listeners.

    Run when this module is first imported, from ``PlatformConfig.ready``, which is
    how the rest of the library registers its listeners: the module cache is what
    keeps a second ``ready`` from subscribing the same listener twice. The signal
    receiver above needs no such care, since ``dispatch_uid`` is what keeps it to
    one subscription.
    """
    global_dispatcher.listen(INVOICE_PAID, on_invoice_paid)
    global_dispatcher.listen(PAYMENT_COMPLETED, on_payment_completed)


register_event_handlers()
