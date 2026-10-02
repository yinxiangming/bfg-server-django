# -*- coding: utf-8 -*-
"""Private server capability used by platform-managed branded portals."""

from django.db import transaction
from django.utils import timezone

from bfg.common.extensions import (
    ACTIVATION_PLATFORM_ADMIN,
    SCOPE_WORKSPACE,
    VISIBILITY_PRIVATE,
    ExtensionManifest,
)


def _invalidate_profile(workspace, record):
    from apps.brand_portal.services import invalidate_profile_cache

    transaction.on_commit(lambda: invalidate_profile_cache(workspace.pk))


def _disable_profile(workspace, record):
    from apps.brand_portal.models import BrandPortalProfile
    from apps.brand_portal.services import invalidate_profile_cache

    BrandPortalProfile.objects.filter(workspace=workspace, registration_enabled=True).update(
        registration_enabled=False,
        updated_by_id=record.status_changed_by_id,
        updated_at=timezone.now(),
    )
    transaction.on_commit(lambda: invalidate_profile_cache(workspace.pk))


EXTENSION = ExtensionManifest(
    key='brand_portal',
    name='Brand portal',
    description='Serve a branded website and provision its customers into new workspaces.',
    name_zh='品牌门户',
    description_zh='为品牌网站提供内容，并为注册客户创建独立 Workspace。',
    icon='tabler-world-www',
    scope=SCOPE_WORKSPACE,
    surfaces=(),
    visibility=VISIBILITY_PRIVATE,
    activation_policy=ACTIVATION_PLATFORM_ADMIN,
    on_activate=_invalidate_profile,
    on_deactivate=_disable_profile,
)
