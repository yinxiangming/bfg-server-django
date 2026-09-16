# -*- coding: utf-8 -*-
"""
The console: workspaces and the extensions each one uses, for the people who run them.

GET   /api/v1/platform/console/workspaces/                                  ?search= matches name or slug
GET   /api/v1/platform/console/workspaces/{id}/                             also every extension, with its config
GET   /api/v1/platform/console/workspaces/{id}/usage/                       ?month=YYYY-MM, this month by default
GET   /api/v1/platform/console/workspaces/{id}/invoices/                    the platform bills, newest first
POST  /api/v1/platform/console/workspaces/{id}/extensions/{key}/acquire/    obtain an add-on, or be billed for it
POST  /api/v1/platform/console/workspaces/{id}/extensions/{key}/activate/   optional body: {"config": {...}}
POST  /api/v1/platform/console/workspaces/{id}/extensions/{key}/deactivate/
POST  /api/v1/platform/console/workspaces/{id}/extensions/{key}/restore/     archived data back
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

A change records the caller as the one who switched the extension on or off. Only a
platform administrator is told that person's email: an owner is told the id and
username of a changer who is active staff or the owner of the workspace, and for anyone
else only ``{"id": null, "username": null, "by_platform": true}``; see
``bfg.common.extensions.endpoints``. A change the extension refuses answers 400 with
the refusal's ``code``, or 404 ``unknown_extension`` for a key no app declares.

Platform paths are public, so no workspace is bound to these requests. What runs for
the workspace being looked at (extension hooks, prerequisite checks, the deployment's
entitlement check) may still read tenant-scoped models through ``objects``, so that
workspace is bound while it runs and the previous binding is put back afterwards.
"""
from datetime import date, datetime

from django.http import Http404
from django.utils.functional import cached_property
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from bfg.common.extensions import endpoints
from bfg.common.extensions import services as extension_services
from bfg.common.middleware import bound_workspace
from bfg.platform.services import acquisitions, console_billing
from bfg.platform.services.console_service import ConsoleViewer, console_workspaces, workspace_entries

WORKSPACE_NOT_FOUND = 'workspace_not_found'
INVALID_MONTH = 'invalid_month'

_EXTENSION_PATH = r'extensions/(?P<key>[a-z][a-z0-9_]*)'


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

    @action(detail=True, methods=['post'], url_path=f'{_EXTENSION_PATH}/restore')
    def restore_extension(self, request, pk=None, key=None):
        """Bring back the data of an extension that was archived, and switch it on.

        The way back for an extension whose rows were exported and deleted after long
        enough switched off: activating one is refused, because the rows are not there to
        activate. Answered with the extension's state, which is ``active`` once the rows
        are back, or ``restoring`` while a worker is still loading them on a deployment
        that restores in the background. A restore that fails leaves it ``archived`` with
        the reason on it, and asking again runs it again — loading an archive twice writes
        the same rows rather than a second copy.

        409 ``archive_not_configured`` when the deployment has given archiving nowhere to
        write, in which case nothing was ever archived either.
        """
        workspace = self._workspace_to_change()
        with _bound(workspace):
            return endpoints.restore(
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
