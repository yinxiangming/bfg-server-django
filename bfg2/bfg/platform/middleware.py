# -*- coding: utf-8 -*-
"""
Refusing writes from a workspace that is read only.

Install after ``bfg.common.middleware.WorkspaceMiddleware``, which is what binds
``request.workspace``::

    MIDDLEWARE = [
        ...
        'bfg.common.middleware.WorkspaceMiddleware',
        'bfg.platform.middleware.ReadOnlyWorkspaceMiddleware',
        ...
    ]

Installing it does not switch it on. It does nothing at all until
``BFG_READ_ONLY_WHEN_UNENTITLED`` is set, and a deployment that sets it without
first writing entitlement rows for its workspaces will lock every one of them —
see ``bfg.platform.services.read_only``.

A middleware rather than a DRF permission class because refusing writes has to be
the default. Nearly every view in this library names its own
``permission_classes``, which replaces the default list rather than adding to it,
so a permission class would guard the views that remembered to ask for it and
silently miss the rest — and the ones it missed would be the ones nobody thought
about. Here the refusal happens for every view there is, and the views that may
still be written to say so out loud with
``bfg.core.read_only.exempt_from_read_only``.

What is still allowed
---------------------

Two things pass without being marked at all:

* **Anything that only reads.** GET, HEAD, OPTIONS and TRACE are never refused,
  so the shop can still be browsed, the back office read, and **every export in
  this library used** — all of them are GETs (invoice and barcode PDFs, site and
  page exports). Nothing here has to be marked to keep exporting working.
* **Anything served outside a workspace.** Signing in, refreshing a token,
  registering an account and the whole platform console live under paths the
  workspace middleware treats as tenant-less, so there is no workspace for this
  middleware to speak for and it does not act.

The marks, and why each one is there — the whole list, kept here so that it can
be read in one place, with the reasoning repeated at each view:

* ``platform.WorkspaceViewSet.checkout`` — paying for the plan. It is the way
  out of read-only mode; refusing it would leave a lapsed workspace no way back.
* ``platform.WebhookViewSet.stripe`` — the gateway confirming that payment
  completed. The other half of ``checkout``: refuse it and a workspace that has
  paid stays locked, out of step with the gateway for good.
* ``platform.ConsoleWorkspaceViewSet.pay_invoice`` — settling a platform bill.
  It is the way out of read-only mode; refusing it would leave a lapsed
  workspace no way back. The console is served outside any workspace, so this
  middleware does not ordinarily reach it — but an API-key caller *is* resolved
  to a workspace below, and the one write that must never be refused should say
  so on itself rather than depend on the path it is mounted at. The gateway's
  half of the same payment is ``shop.StorefrontPaymentViewSet.callback``, marked
  below: refuse that and a workspace that has paid stays locked, out of step
  with the gateway for good.
* ``common.MeViewSet.change_password`` and ``.reset_password`` — account
  operations, not workspace data. Somebody has to be able to sign in and pay.
* ``shop.StorefrontPaymentViewSet.callback`` — a payment gateway reporting money
  that has already left an account, signature and all. Checkout is refused, so
  the only order callbacks that can arrive are for orders placed before the
  workspace lapsed; refusing them would take a shopper's money and leave the
  order unpaid. It is also where a card payment for a *platform bill* is
  confirmed, which is the half of ``pay_invoice`` that ends read-only mode. This
  is the gateway speaking, not the shop — ``mark-paid``, where the shop asserts
  a payment itself, stays refused.
* ``shop.OrderViewSet.update_status`` — **only for an order already paid for**
  (``order_in_url_is_paid``). Getting goods to shoppers who have already paid is
  a promise the shop must keep whatever it owes the deployment. An unpaid order
  cannot be moved along, so read-only mode cannot be worked around by trading on
  and settling up later.
* ``delivery.CarrierViewSet.ship_order`` — handing goods to a carrier.
* ``delivery.ConsignmentViewSet.update_status``, ``.add_tracking_event`` and
  ``.generate_label`` — moving an existing shipment along, recording where it
  has got to, and printing its label. Creating or deleting consignments is not
  exempt: read-only mode deletes nothing.

Deliberately *not* exempt, where somebody might expect otherwise: customer
registration and checkout (a read-only shop takes no new business), order
creation and editing, ``mark-paid``, refunds and cancellations, storefront
analytics collection (a write that costs the deployment storage, and a
storefront that works without it), and the assistant endpoints, whose calls cost
the deployment money on the workspace's behalf.
"""

from __future__ import annotations

import logging

from django.http import JsonResponse

from bfg.core.read_only import is_exempt
from bfg.platform.services import read_only

logger = logging.getLogger(__name__)

# Nothing that only reads is ever refused: a read-only workspace is one whose
# shop can still be browsed and whose back office can still be looked at. DRF's
# own list, plus TRACE, which changes nothing either and would otherwise be
# refused with a message about an unpaid plan.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

READ_ONLY_CODE = "workspace_read_only"
READ_ONLY_RESPONSE = {
    "code": READ_ONLY_CODE,
    "detail": (
        "This workspace is read only because its plan has not been renewed. "
        "Existing data is kept and can still be viewed and exported; renewing "
        "the plan restores it."
    ),
}


class ReadOnlyWorkspaceMiddleware:
    """403 ``workspace_read_only`` for a write a read-only workspace may not make.

    The work happens in ``process_view``, after the URL has been resolved, which
    is the earliest point at which the view being called is known — and the view
    is what carries the exemption mark. Ordered so that the cheapest questions
    are asked first and the switch is the very first of them: with it off, a
    request costs one ``getattr`` on the settings object.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not read_only.enabled():
            return None
        if request.method in SAFE_METHODS:
            return None
        if is_exempt(view_func, request, view_kwargs):
            return None

        workspace = self._workspace(request)
        if workspace is None:
            # No tenant to speak for: a platform or sign-up endpoint, or a
            # request the workspace middleware has already decided about. Not
            # this middleware's to refuse.
            return None

        if not read_only.is_read_only(workspace):
            return None

        logger.info(
            "read_only: refusing %s %s for workspace %s",
            request.method, request.path, getattr(workspace, "pk", workspace),
        )
        return JsonResponse(READ_ONLY_RESPONSE, status=403)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _workspace(request):
        """The workspace this write would change, if it can be named yet.

        Usually ``request.workspace``, bound by ``WorkspaceMiddleware`` from the
        token, the session or the hostname.

        An API-key request is the exception, and an important one: that
        middleware deliberately leaves such a request tenant-less
        (``WORKSPACE_DELEGATING_HEADERS``) and lets DRF's authentication class
        bind the workspace from the key — which happens inside the view, after
        every middleware has had its say. A guard that trusted
        ``request.workspace`` alone would therefore let every API-key write
        through, which is exactly the path an integration writes on. So the key
        is looked up here, one indexed read of a unique column, and only for an
        unsafe method on a view that is not exempt while the switch is on.

        A key that does not resolve gives ``None`` and the request continues:
        authentication is about to reject it anyway, and inventing a refusal for
        it here would only obscure that.
        """
        workspace = getattr(request, "workspace", None)
        if workspace is not None:
            return workspace

        prefix = request.headers.get("X-API-Key")
        if not prefix:
            return None

        try:
            from bfg.common.models import APIKey

            key = (
                APIKey.all_objects.select_related("workspace")
                .filter(prefix=prefix)
                .first()
            )
        except Exception:
            # Same bargain as ``is_read_only``: a workspace that cannot be named
            # is treated as writable rather than having its integrations stopped
            # by whatever is wrong with the database.
            logger.exception("Could not resolve the workspace of an API key; treating it as writable")
            return None
        return key.workspace if key is not None else None
