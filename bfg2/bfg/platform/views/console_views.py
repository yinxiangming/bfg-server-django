# -*- coding: utf-8 -*-
"""
The console: workspaces and the extensions each one uses, for the people who run them.

GET   /api/v1/platform/console/workspaces/                                  ?search= matches name or slug
GET   /api/v1/platform/console/workspaces/{id}/                             also every extension, with its config
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
from contextlib import contextmanager

from django.http import Http404
from django.utils.functional import cached_property
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from bfg.common.extensions import endpoints
from bfg.common.middleware import get_current_workspace, set_current_workspace
from bfg.platform.services.console_service import ConsoleViewer, console_workspaces, workspace_entries

WORKSPACE_NOT_FOUND = 'workspace_not_found'

_EXTENSION_PATH = r'extensions/(?P<key>[a-z][a-z0-9_]*)'


@contextmanager
def _bound(workspace):
    previous = get_current_workspace()
    set_current_workspace(workspace)
    try:
        yield
    finally:
        set_current_workspace(previous)


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
        with _bound(workspace):
            entry['extensions'] = endpoints.list_extensions(
                workspace, viewer_is_platform_admin=self.viewer.is_platform_admin
            )
        return Response(entry)

    @action(detail=True, methods=['post'], url_path=f'{_EXTENSION_PATH}/activate')
    def activate_extension(self, request, pk=None, key=None):
        workspace = self._workspace_to_change()
        with _bound(workspace):
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
        with _bound(workspace):
            return endpoints.deactivate(
                workspace, key, user=request.user, viewer_is_platform_admin=self.viewer.is_platform_admin
            )

    @action(detail=True, methods=['patch'], url_path=f'{_EXTENSION_PATH}/config')
    def extension_config(self, request, pk=None, key=None):
        workspace = self._workspace_to_change()
        with _bound(workspace):
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
