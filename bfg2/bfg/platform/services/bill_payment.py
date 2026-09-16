# -*- coding: utf-8 -*-
"""
Taking payment for a platform bill.

``billing`` issues the bills, ``console_billing`` shows them, and ``renewals``
writes what a settled one buys. This is the step in between, and the only one the
workspace's own side takes: starting a payment for a bill that has been issued.

Nothing here collects money itself. A platform bill is an ordinary
``finance.Invoice`` belonging to the management workspace, so it is paid the way
every other invoice on the deployment is — ``finance.PaymentService`` and the
gateway plugins — and it is the *management* workspace's gateways that take it,
because the management workspace is the one selling. Settling the payment is
therefore already wired: ``PaymentService`` marks the invoice paid and emits
``invoice.paid`` and ``payment.completed``, which is what ``bfg.platform.handlers``
turns into the next entitlement period. There is no second collection path here to
keep in step with the first.

Starting a payment is all this does. Whether the money has arrived is never the
payer's word: a card is confirmed by the gateway's callback, and an offline
gateway — a bank transfer, paying at the counter — by whoever reconciles it. So
the payment comes back ``pending`` and the caller is given what it needs to
finish: the gateway's own payload, and the details the gateway publishes for a
payer to act on.

Which bill a caller may pay is decided by its number and nothing else. A platform
invoice belongs to the management workspace, so the number is the only thing
tying one to the workspace it bills (see ``billing.invoice_number_for``); every
lookup here is therefore bounded by the billed workspace's own prefix, and a
number outside it is answered exactly as one that does not exist. Without that, a
tenant could read or pay another tenant's bill by guessing a number that differs
from its own by one digit.

Everything reads ``all_objects`` and filters by workspace itself: the console is a
platform path, so no workspace is bound to the thread. ``finance`` is written
against the scoped manager, so the management workspace is bound around the calls
into it and the previous binding put back afterwards.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from bfg.core.exceptions import BFGException
from bfg.finance.exceptions import PaymentFailed
from bfg.platform.services import billing
from bfg.common.middleware import bound_workspace
from bfg.platform.utils import get_platform_workspace

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

# Refusal codes. Spelled once here rather than in the view, so that the service
# and whatever calls it cannot drift apart, and so a test can assert the code a
# console will actually branch on.
INVOICE_NOT_FOUND = "invoice_not_found"
INVOICE_ALREADY_PAID = "invoice_already_paid"
INVOICE_CANCELLED = "invoice_cancelled"
INVOICE_NOTHING_TO_PAY = "invoice_nothing_to_pay"
NO_PAYMENT_GATEWAY = "no_payment_gateway"
PAYMENT_GATEWAY_NOT_FOUND = "payment_gateway_not_found"
PAYMENT_GATEWAY_UNAVAILABLE = "payment_gateway_unavailable"
PAYMENT_IN_PROGRESS = "payment_in_progress"

# A payment that has been started and not settled. Neither is a second attempt to
# be made alongside: ``finance.PaymentService`` refuses that outright, and this is
# what lets the refusal say something more useful first.
UNDER_WAY = ("pending", "processing")

# The status an attempt must still be in to be handed back to a caller asking
# again. ``processing`` means the gateway has been told to take the money, and
# what a repeat of that needs is the first attempt reconciled, not a second one.
RESUMABLE = "pending"


class BillPaymentRefused(BFGException):
    """A platform bill that cannot be paid, or cannot be paid the way asked."""

    default_message = "This bill cannot be paid."
    default_code = "bill_payment_refused"


class BillNotFound(BillPaymentRefused):
    """No platform bill of that number belongs to this workspace.

    Also what an invoice that is not a platform bill at all is answered with — a
    workspace's own invoice to one of its customers, or a number typed in by hand.
    Deliberately the same answer as a bill that does not exist: telling the two
    apart would let a tenant learn which numbers other tenants hold.
    """

    default_message = "Invoice not found."
    default_code = INVOICE_NOT_FOUND


def _money(value) -> str:
    """An amount as the string the console is given.

    Money is a Decimal and JSON has no decimal, so a number here would hand a
    console a float to do arithmetic on; the reasoning is ``console_billing``'s
    and the two reports have to agree on it.
    """
    return format(Decimal(value), "f")


def find_bill(workspace, invoice_number: str):
    """The platform bill ``invoice_number`` names for ``workspace``.

    Raises ``BillNotFound`` for anything else, which includes every number
    belonging to another workspace: the prefix is checked before the database is
    asked, so a guessed number is refused without so much as a query telling
    whether it exists.

    Raises ``billing.PlatformWorkspaceMissing`` when the deployment has no
    management workspace, since nothing has issued any platform bills there.
    """
    from bfg.finance.models import Invoice

    platform_workspace = get_platform_workspace()
    if platform_workspace is None:
        raise billing.PlatformWorkspaceMissing(
            "PLATFORM_WORKSPACE_SLUG names no workspace, so there are no platform bills."
        )

    number = (invoice_number or "").strip()
    if not number.startswith(billing.invoice_number_prefix(workspace.pk)):
        raise BillNotFound()

    invoice = (
        Invoice.all_objects.filter(workspace=platform_workspace, invoice_number=number)
        .select_related("currency", "customer")
        .first()
    )
    if invoice is None:
        raise BillNotFound()
    return invoice


def start_payment(workspace, invoice_number: str, *, gateway_id=None, user=None) -> dict:
    """Begin paying one of ``workspace``'s platform bills, and say how to finish.

    ``gateway_id`` picks one of the management workspace's active gateways; with
    none named the lowest-numbered one is used, which is the only one on a
    deployment that has configured a single way to be paid. The gateway belongs to
    the management workspace rather than to ``workspace``: the deployment is the
    one being paid.

    The payment is raised against the bill's own customer — the workspace's owner,
    as the bill was made out — whoever started it. A platform administrator paying
    on a workspace's behalf therefore settles the same debt rather than opening a
    second one in their own name.

    Asking twice is safe: an attempt already under way for the same gateway and
    the same amount is handed back rather than a second one being raised, so a
    console that retries or a payer who double-clicks gets the payload they
    already had. An attempt under way that this request does not match is refused
    with ``payment_in_progress`` rather than quietly abandoned, since it may be a
    card payment the gateway is in the middle of taking.

    Raises ``BillNotFound`` (see ``find_bill``) or ``BillPaymentRefused`` with one
    of the codes above. Nothing here settles the payment or touches the invoice's
    status; what the money buys is written when the gateway or an operator
    confirms it, through ``bfg.platform.handlers``.
    """
    from bfg.finance.gateways.loader import get_gateway_plugin
    from bfg.finance.services import PaymentService

    invoice = find_bill(workspace, invoice_number)
    _refuse_unpayable(invoice)

    platform_workspace = get_platform_workspace()
    gateway = _gateway(platform_workspace, gateway_id)

    # ``finance`` reads the scoped manager and binds whatever workspace it is
    # given, so the management workspace is bound for the whole of it and the
    # binding this request arrived with — none, on a platform path — is restored.
    with bound_workspace(platform_workspace):
        payment = _resume_or_raise(platform_workspace, invoice, gateway, user)

        plugin = get_gateway_plugin(gateway)
        if plugin is None:
            raise BillPaymentRefused(
                f"{gateway.name} is not a gateway this deployment can take money through.",
                code=PAYMENT_GATEWAY_UNAVAILABLE,
            )
        payload = _payment_intent(plugin, payment)
        instructions = plugin.get_payment_page_display_params()

    return {
        "invoice": {
            "id": invoice.pk,
            "number": invoice.invoice_number,
            "status": invoice.status,
            "total": _money(invoice.total),
            "currency": invoice.currency.code,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        },
        "payment": {
            "id": payment.pk,
            "number": payment.payment_number,
            "status": payment.status,
            "amount": _money(payment.amount),
            "currency": payment.currency.code,
        },
        "gateway": {
            "id": gateway.pk,
            "type": gateway.gateway_type,
            "name": gateway.name,
            # What the gateway publishes for a payer to act on: a card processor's
            # publishable key, or the account a transfer should go to. The same
            # thing a storefront shows at checkout, and no more.
            "instructions": instructions,
        },
        "gateway_payload": payload,
    }


def _refuse_unpayable(invoice) -> None:
    """Refuse a bill there is nothing to pay on, each with its own code.

    A console shows these to whoever pressed the button, so they are told apart:
    a bill that has been settled, one that was written off, and one that came to
    nothing are three different things to say, and none of them is a server error.
    """
    if invoice.status == "paid":
        raise BillPaymentRefused(
            f"Invoice {invoice.invoice_number} has already been paid.",
            code=INVOICE_ALREADY_PAID,
        )
    if invoice.status == "cancelled":
        raise BillPaymentRefused(
            f"Invoice {invoice.invoice_number} was cancelled and is not owed.",
            code=INVOICE_CANCELLED,
        )
    if Decimal(invoice.total) <= ZERO:
        # A month covered entirely by the trial credit is worth an invoice as a
        # record of what was used, but there is nothing to collect on it — the
        # same rule ``has_overdue_invoice`` applies when deciding what is a debt.
        raise BillPaymentRefused(
            f"Invoice {invoice.invoice_number} comes to nothing, so there is nothing to pay.",
            code=INVOICE_NOTHING_TO_PAY,
        )


def _gateway(platform_workspace, gateway_id) -> Optional[object]:
    """The management workspace's gateway this payment goes through.

    ``PaymentGateway`` is not tenant-scoped, so the workspace is part of every
    filter here by hand — without it, naming an id would reach any workspace's
    gateway on the deployment and take the money into somebody else's account.
    """
    from bfg.finance.models import PaymentGateway

    gateways = PaymentGateway.objects.filter(workspace=platform_workspace, is_active=True)
    if gateway_id is not None:
        gateway = gateways.filter(pk=gateway_id).first()
        if gateway is None:
            raise BillPaymentRefused(
                "That is not a gateway this deployment takes platform bills through.",
                code=PAYMENT_GATEWAY_NOT_FOUND,
            )
        return gateway

    gateway = gateways.order_by("id").first()
    if gateway is None:
        raise BillPaymentRefused(
            "This deployment has no active payment gateway to take the bill through.",
            code=NO_PAYMENT_GATEWAY,
        )
    return gateway


def _resume_or_raise(platform_workspace, invoice, gateway, user):
    """The attempt already under way for this bill, or a new one.

    Called with the management workspace bound, since ``PaymentService`` works
    through the scoped manager.
    """
    from bfg.finance.models import Payment
    from bfg.finance.services import PaymentService

    under_way = (
        Payment.all_objects.filter(
            workspace=platform_workspace, invoice=invoice, status__in=UNDER_WAY
        )
        .select_related("currency", "customer", "gateway")
        .order_by("id")
        .first()
    )
    if under_way is not None:
        if (
            under_way.status == RESUMABLE
            and under_way.gateway_id == gateway.pk
            and under_way.amount == invoice.total
            and under_way.currency_id == invoice.currency_id
        ):
            return under_way
        raise BillPaymentRefused(
            f"Invoice {invoice.invoice_number} already has a payment under way "
            f"through {under_way.gateway_display_name or 'another gateway'}; "
            "finish or reconcile that one first.",
            code=PAYMENT_IN_PROGRESS,
            details={"payment_number": under_way.payment_number, "status": under_way.status},
        )

    try:
        return PaymentService(workspace=platform_workspace, user=user).create_payment(
            # The bill's own customer, not the caller's: the debt is the owner's
            # however it comes to be settled, and ``create_payment`` refuses a
            # customer who does not hold the invoice in any case.
            customer=invoice.customer,
            amount=invoice.total,
            currency=invoice.currency,
            gateway=gateway,
            invoice=invoice,
        )
    except PaymentFailed as refusal:
        # Everything finance refuses a payment for that is worth saying to a
        # payer — a bill settled between the check above and this call, a second
        # attempt raised at the same moment — carries its own code and message.
        raise BillPaymentRefused(refusal.message, code=refusal.code) from refusal


def _payment_intent(plugin, payment) -> dict:
    """Ask the gateway for whatever the payer needs to finish, and remember it.

    The id the gateway answers with is what a callback names the payment by, so
    it is stored on the payment before the payer is given anything to act on.
    """
    payload = plugin.create_payment_intent(
        customer=payment.customer,
        amount=payment.amount,
        currency=payment.currency,
        metadata={
            "payment_id": str(payment.pk),
            "payment_number": payment.payment_number,
        },
        # Stable across retries of the same attempt, so a caller asking twice
        # does not open a second intent at the gateway for one payment.
        idempotency_key=f"bfg-platform-bill-{payment.pk}",
    )
    intent_id = payload.get("payment_intent_id") or payload.get("id")
    if intent_id and payment.gateway_transaction_id != intent_id:
        payment.gateway_transaction_id = intent_id
        payment.save(update_fields=["gateway_transaction_id"])
    return payload
