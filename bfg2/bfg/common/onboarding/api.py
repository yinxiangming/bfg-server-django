# -*- coding: utf-8 -*-
"""
Setup-wizard endpoints.

Reads are open to any staff member (the dashboard block shows the progress bar
to everyone); writes are admin-only, because applying a template rewrites the
workspace's currency and publishes public pages.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff

from .service import OnboardingService, options_payload


class _Base(APIView):
    permission_classes = [IsAuthenticated]

    def service(self, request) -> OnboardingService:
        return OnboardingService(workspace=request.workspace, user=request.user)


class OnboardingStatusView(_Base):
    """GET /api/v1/onboarding/status/ — the checklist and the percentage."""

    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get(self, request):
        return Response(self.service(request).status())


class OnboardingOptionsView(APIView):
    """GET /api/v1/onboarding/options/ — countries, industries, languages, currencies.

    Static reference data, so it does not need the workspace at all.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(options_payload())


class OnboardingPreviewView(_Base):
    """POST /api/v1/onboarding/preview/ — what apply would change, writing nothing."""

    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]

    def post(self, request):
        data = request.data or {}
        return Response(self.service(request).preview(
            country=data.get('country', ''),
            industry=data.get('industry', ''),
            overrides=data.get('overrides') or {},
        ))


class OnboardingApplyView(_Base):
    """POST /api/v1/onboarding/apply/ — create everything that is missing."""

    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]

    def post(self, request):
        data = request.data or {}
        return Response(self.service(request).apply(
            country=data.get('country', ''),
            industry=data.get('industry', ''),
            overrides=data.get('overrides') or {},
        ))


class OnboardingSkipView(_Base):
    """POST /api/v1/onboarding/skip/ — {"item": "...", "skipped": true}."""

    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]

    def post(self, request):
        data = request.data or {}
        item = (data.get('item') or '').strip()
        try:
            return Response(self.service(request).skip_item(item, bool(data.get('skipped', True))))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class OnboardingDismissView(_Base):
    """POST /api/v1/onboarding/dismiss/ — hide the wizard prompts on the dashboard."""

    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]

    def post(self, request):
        data = request.data or {}
        return Response(self.service(request).dismiss(bool(data.get('dismissed', True))))
