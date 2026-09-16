# -*- coding: utf-8 -*-
"""
The console: workspaces and the extensions each one uses, for the people who run them.

GET   /api/v1/platform/console/workspaces/                                  ?search= matches name or slug
GET   /api/v1/platform/console/workspaces/{id}/                             also every extension, with its config
GET   /api/v1/platform/console/workspaces/{id}/usage/                       ?month=YYYY-MM, this month by default
GET   /api/v1/platform/console/workspaces/{id}/invoices/                    the platform bills, newest first
POST  /api/v1/platform/console/workspaces/{id}/invoices/{number}/pay/       optional body: {"gateway": <id>}
POST  /api/v1/platform/console/workspaces/{id}/extensions/{key}/acquire/    obtain an add-on, or be billed for it
POST  /api/v1/platform/console/workspaces/{id}/extensions/{key}/activate/   optional body: {"config": {...}}
POST  /api/v1/platform/console/workspaces/{id}/extensions/{key}/deactivate/
PATCH /api/v1/platform/console/workspaces/{id}/extensions/{key}/config/     body: {"config": {...}}

Shared by platform administrators, who reach every workspace, and workspace owners,
who reach the workspaces they own; see ``console_service``. Any other account is
refused. A workspace the caller does not reach is answered with 404
``workspace_not_found``, exactly as one that does not exist is. Each row's
``owned_by_viewer`` says whether the caller owns it. An owner only reads a workspace
that is suspended or inactive: changing its extensions is refused with 403
``workspace_suspended`` or ``workspace_inactive``.

What a workspace has spent and what it has been billed are read by whoever reaches
the workspace at all, suspended and inactive ones included: a suspended workspace is
one whose owner most needs to see the bill. Money and points are strings rather than
JSON numbers, so that nothing is rounded on the way to the console; see
``console_billing``.

Paying a bill is open to the same people, and for the same reason — a workspace that
has been stopped is the one with something to settle. It is the one write here that
a read-only workspace may still make, so it carries the mark that says so; see
``bill_payment`` for everything it refuses and ``bfg.platform.middleware`` for the
list the mark belongs to.

A change records the caller as the one who switched the extension on or off. Only a
platform administrator is told that person's email: an owner is told the id and
username of a changer who is active staff or the owner of the workspace, and for anyone
else only ``{"id": null, "username": null, "by_platform": true}``; see
``bfg.common.extensions.endpoints``. A change the extension refuses answers 400 with
the refusal's ``code``, or 404 ``unknown_extension`` for a key no app declares.

Platform paths are public, so no workspace is bound to these requests. What runs for
the workspace being looked at (extension hooks, prerequisite checks, the deployment's
entitlement check) may still read tenant-scoped models through ``objects``, so that
workspace is bound while it runs and the previous binding is put back afterwards. The
same goes for paying a bill, where what is bound is the *management* workspace: the
bill and the payment are its own.
"""
from datetime import date, datetime

from django.http import Http404
from django.utils.functional import cached_property
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from bfg.common.extensions import endpoints, services as extension_services
from bfg.core.read_only import exempt_from_read_only
from bfg.platform.services import acquisitions, bill_payment, console_billing
from bfg.platform.services.billing import PlatformWorkspaceMissing
from bfg.platform.services.console_service import ConsoleViewer, console_workspaces, workspace_entries
from bfg.platform.utils import bound_workspace

WORKSPACE_NOT_FOUND = 'workspace_not_found'
INVALID_MONTH = 'invalid_month'

_EXTENSION_PATH = r'extensions/(?P<key>[a-z][a-z0-9_]*)'
# An invoice number as ``billing`` writes one, and as ``finance.Invoice`` stores
# one: at most fifty characters of the alphabet a number is built from. Anything
# else never reaches the view, and anything shaped like this that is not one of
# this workspace's bills is answered as not found.
_INVOICE_PATH = r'invoices/(?P<number>[A-Za-z0-9][A-Za-z0-9_-]{0,49})'


class _DeploymentNotReady(APIException):
    """503 for something the deployment has not configured, not the caller's doing."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


def _month(request):
    """The month ``?month=YYYY-MM`` asks for, or ``None`` for the current one.

    Refused rather than guessed at: a console heading says which month it is
    showing, and reading an unparseable one as this month would put the wrong
    numbers under it.
    """
    wanted = (request.query_params.get('month') or '').strip()
    if not wanted:
        return None
    try:
        parsed = datetime.strptime(wanted, '%Y-%m')
    except ValueError:
        raise ValidationError(
            {'code': INVALID_MONTH, 'detail': 'month must be written as YYYY-MM.'}
        ) from None
    return date(parsed.year, parsed.month, 1)


class _MayUseConsole(BasePermission):
    message = 'Only platform administrators and workspace owners can use the console.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated) and view.viewer.may_use_console


class ConsoleWorkspaceViewSet(viewsets.GenericViewSet):
    """The workspaces the caller runs, and their extensions."""

    permission_classes = [_MayUseConsole]
    lookup_value_regex = r'[0-9]+'

    @cached_property
    def viewer(self):
        # Worked out once a request: the permission check, the queryset and every row ask.
        return ConsoleViewer.of(self.request.user)

    def get_queryset(self):
        search = self.request.query_params.get('search', '') if self.action == 'list' else ''
        return console_workspaces(self.viewer, search)

    def get_object(self):
        # The queryset holds only what the caller reaches, so a workspace outside it
        # answers exactly as one that does not exist.
        try:
            return super().get_object()
        except Http404:
            raise NotFound({'code': WORKSPACE_NOT_FOUND, 'detail': 'Workspace not found.'}) from None

    def list(self, request):
        workspaces = self.get_queryset()
        page = self.paginate_queryset(workspaces)
        if page is not None:
            return self.get_paginated_response(workspace_entries(page, self.viewer))
        return Response(workspace_entries(workspaces, self.viewer))

    def retrieve(self, request, pk=None):
        workspace = self.get_object()
        entry = workspace_entries([workspace], self.viewer)[0]
        with bound_workspace(workspace):
            entry['extensions'] = endpoints.list_extensions(
                workspace, viewer_is_platform_admin=self.viewer.is_platform_admin
            )
        return Response(entry)

    @action(detail=True, methods=['get'])
    def usage(self, request, pk=None):
        """A month of metered usage, against what the workspace may spend.

        ``?month=YYYY-MM`` picks the month, the current UTC one by default. Read by
        anyone who reaches the workspace, whether or not they may change it: a
        suspended workspace is one whose owner most needs to see what it has run up.

        Each entry under ``meters`` and under ``days[].meters`` names the extension
        that declares the meter — ``extension`` is its key and ``extension_name``
        the name on its manifest — and both are ``null`` for a meter that belongs to
        the base platform rather than to any extension.
        """
        workspace = self.get_object()
        return Response(console_billing.usage_report(workspace, month=_month(request)))

    @action(detail=True, methods=['get'])
    def invoices(self, request, pk=None):
        """The workspace's platform bills, newest first and bounded.

        ``status`` is one of ``draft``, ``sent``, ``paid``, ``overdue`` and
        ``cancelled``, and is not what says whether a bill is late: the ``overdue``
        field is, and nothing on the platform billing path writes the status of the
        same name. See ``console_billing.invoice_history`` for what each status
        means and for the rule the flag is worked out by.
        """
        return Response(console_billing.invoice_history(self.get_object()))

    # Read-only exemption: this is how a workspace settles what it owes, and
    # settling it is what ends read-only mode. Refusing it would leave a lapsed
    # workspace with no way back. The console is served outside any workspace, so
    # the middleware would not act on it in the ordinary course — but an API-key
    # caller is resolved to a workspace by the middleware itself, and the one
    # write that must never be refused should say so on itself rather than rely
    # on the path it happens to be mounted at.
    @exempt_from_read_only
    @action(detail=True, methods=['post'], url_path=f'{_INVOICE_PATH}/pay')
    def pay_invoice(self, request, pk=None, number=None):
        """Start paying one of this workspace's platform bills.

        Body: ``{"gateway": <id>}``, optional — one of the management workspace's
        active gateways, the lowest-numbered one by default. The deployment is
        what is being paid, so the gateway is its own and not the workspace's.

        Answers 201 with the bill, the payment raised against it, the gateway and
        whatever that gateway needs the payer to act on. The payment comes back
        ``pending``: money is never taken on the payer's word, so a card is
        settled by the gateway's callback and an offline payment by whoever
        reconciles it, and only then is the bill marked paid and what it bought
        renewed.

        Refusals, all with a ``code``: 404 ``workspace_not_found`` for a workspace
        the caller does not reach and 404 ``invoice_not_found`` for a number that
        is not one of *this* workspace's platform bills — another tenant's bill is
        answered exactly as one that does not exist; 400 ``invoice_already_paid``,
        ``invoice_cancelled``, ``invoice_nothing_to_pay``, ``no_payment_gateway``,
        ``payment_gateway_not_found``, ``payment_gateway_unavailable``,
        ``payment_in_progress``, or whatever ``finance`` refused the payment with;
        and 503 ``platform_workspace_missing`` where the deployment has no
        management workspace to be paid.

        Open to anyone who reaches the workspace, suspended and inactive ones
        included, rather than to ``_workspace_to_change``: a workspace that has
        been stopped is the one that most needs to settle up, and being unable to
        pay is what keeps it stopped.
        """
        workspace = self.get_object()
        try:
            paid = bill_payment.start_payment(
                workspace,
                number,
                gateway_id=self._gateway_id(request),
                user=request.user,
            )
        except bill_payment.BillNotFound as missing:
            raise NotFound({'code': missing.code, 'detail': missing.message}) from None
        except bill_payment.BillPaymentRefused as refusal:
            raise ValidationError({'code': refusal.code, 'detail': refusal.message}) from None
        except PlatformWorkspaceMissing as missing:
            raise _DeploymentNotReady({'code': missing.code, 'detail': missing.message}) from None
        return Response(paid, status=status.HTTP_201_CREATED)

    @staticmethod
    def _gateway_id(request):
        """The gateway the body names, or ``None`` for the deployment's own choice."""
        body = request.data if isinstance(request.data, dict) else {}
        wanted = body.get('gateway')
        if wanted in (None, ''):
            return None
        try:
            return int(wanted)
        except (TypeError, ValueError):
            raise ValidationError(
                {'code': bill_payment.PAYMENT_GATEWAY_NOT_FOUND, 'detail': 'gateway must be an id.'}
            ) from None
    @action(detail=True, methods=['post'], url_path=f'{_EXTENSION_PATH}/acquire')
    def acquire_extension(self, request, pk=None, key=None):
        """Obtain an add-on for the workspace, or bill it for one.

        Who may ask is who may switch an extension on: a platform administrator, or
        the owner of a workspace that is neither suspended nor inactive.

        The answer always carries ``entitled``, ``invoice`` and ``extension``. An
        add-on the deployment prices at nothing is entitled and switched on at once,
        so ``entitled`` is true and ``invoice`` is null. A priced one is invoiced
        and nothing else is written until the money arrives: ``entitled`` is false
        and ``invoice`` is the bill, in the shape the invoice list shows it, with
        ``issued`` saying whether it was written now or is one the workspace was
        already holding unpaid. ``extension`` is the extension as it now stands,
        which for a priced add-on is as it stood before.

        Refused with 400 and a ``code`` when the workspace already has the add-on,
        when the extension is part of the base plan rather than something sold
        separately, when the deployment has never priced it, and when a bill cannot
        be written for want of an owner, a currency or an exchange rate; with 404
        for a key no app declares. See ``services.acquisitions``.
        """
        workspace = self._workspace_to_change()
        try:
            with bound_workspace(workspace):
                acquired = acquisitions.acquire(workspace, key, user=request.user)
        except extension_services.ExtensionError as refused:
            return endpoints.error_response(refused)
        except acquisitions.AcquisitionRefused as refused:
            raise ValidationError({'code': refused.code, 'detail': refused.message}) from None
        with bound_workspace(workspace):
            state = endpoints.extension_state(
                workspace, key, viewer_is_platform_admin=self.viewer.is_platform_admin
            )
        return Response({
            'entitled': acquired.entitlement is not None,
            'invoice': (
                {**console_billing.invoice_entry(acquired.invoice), 'issued': acquired.invoice_is_new}
                if acquired.invoice is not None
                else None
            ),
            'extension': state,
        })

    @action(detail=True, methods=['post'], url_path=f'{_EXTENSION_PATH}/activate')
    def activate_extension(self, request, pk=None, key=None):
        workspace = self._workspace_to_change()
        with bound_workspace(workspace):
            return endpoints.activate(
                workspace,
                key,
                user=request.user,
                data=request.data,
                viewer_is_platform_admin=self.viewer.is_platform_admin,
            )

    @action(detail=True, methods=['post'], url_path=f'{_EXTENSION_PATH}/deactivate')
    def deactivate_extension(self, request, pk=None, key=None):
        workspace = self._workspace_to_change()
        with bound_workspace(workspace):
            return endpoints.deactivate(
                workspace, key, user=request.user, viewer_is_platform_admin=self.viewer.is_platform_admin
            )

    @action(detail=True, methods=['patch'], url_path=f'{_EXTENSION_PATH}/config')
    def extension_config(self, request, pk=None, key=None):
        workspace = self._workspace_to_change()
        with bound_workspace(workspace):
            return endpoints.update_config(
                workspace, key, data=request.data, viewer_is_platform_admin=self.viewer.is_platform_admin
            )

    def _workspace_to_change(self):
        workspace = self.get_object()
        refusal = self.viewer.refusal_to_change(workspace)
        if refusal is not None:
            code, detail = refusal
            raise PermissionDenied({'code': code, 'detail': detail})
        return workspace
