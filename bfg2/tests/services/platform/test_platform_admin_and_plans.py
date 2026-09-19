"""Platform admin access and the platform's plan listing, in both platform modes.

Platform endpoints are public paths, so these checks run with no workspace bound
to the request, which is exactly where the tenant-scoped managers come back empty.
"""
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, Workspace
from bfg.platform.permissions import IsPlatformAdmin, IsPlatformSuperuser
from bfg.shop.models import SubscriptionPlan

User = get_user_model()


def _embedded(settings, slug="platform"):
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = slug


def _workspace(slug):
    return Workspace.objects.create(name=slug.title(), slug=slug, is_active=True)


def _member(workspace, username, role_code, is_active=True):
    role, _ = StaffRole.objects.get_or_create(
        workspace=workspace, code=role_code, defaults={"name": role_code.title()}
    )
    user = User.objects.create_user(username=username, password="secret")
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=is_active)
    return user


def _is_platform_admin(user):
    return IsPlatformAdmin().has_permission(SimpleNamespace(user=user), view=None)


def _is_platform_superuser(user):
    return IsPlatformSuperuser().has_permission(SimpleNamespace(user=user), view=None)


def _plan_names(response):
    data = response.data
    items = data["results"] if isinstance(data, dict) else data
    return sorted(item["name"] for item in items)


def test_embedded_platform_admin_is_an_admin_of_the_platform_workspace(db, settings):
    _embedded(settings)
    platform = _workspace("platform")
    admin = _member(platform, "platform-admin", "admin")

    assert _is_platform_admin(admin)


def test_embedded_platform_admin_excludes_other_roles_of_the_platform_workspace(db, settings):
    _embedded(settings)
    platform = _workspace("platform")
    staff = _member(platform, "platform-staff", "staff")

    assert not _is_platform_admin(staff)


def test_embedded_platform_admin_excludes_admins_of_other_workspaces(db, settings):
    _embedded(settings)
    _workspace("platform")
    shop = _workspace("shop")
    shop_admin = _member(shop, "shop-admin", "admin")

    assert not _is_platform_admin(shop_admin)


def test_embedded_platform_admin_excludes_inactive_memberships(db, settings):
    _embedded(settings)
    platform = _workspace("platform")
    former = _member(platform, "former-admin", "admin", is_active=False)

    assert not _is_platform_admin(former)


def test_embedded_platform_admin_is_denied_without_a_platform_workspace(db, settings):
    _embedded(settings, slug="missing")
    shop = _workspace("shop")
    shop_admin = _member(shop, "shop-admin", "admin")

    assert not _is_platform_admin(shop_admin)


def test_platform_admin_rejects_anonymous_users(db, settings):
    _embedded(settings)

    assert not _is_platform_admin(AnonymousUser())


def test_standalone_platform_admin_is_superuser_or_staff(db, settings):
    settings.PLATFORM_EMBEDDED = False
    superuser = User.objects.create_superuser(username="root", password="secret", email="root@example.com")
    plain = User.objects.create_user(username="plain", password="secret")

    assert _is_platform_admin(superuser)
    assert not _is_platform_admin(plain)


def test_workspaces_me_reports_only_the_django_superuser_for_control_plane_access(db, settings):
    _embedded(settings)
    platform = _workspace("platform")
    admin = _member(platform, "platform-admin", "admin")
    staff = _member(platform, "platform-staff", "staff")
    superuser = User.objects.create_superuser(username="root", password="secret", email="root@example.test")

    client = APIClient()
    for user, expected in ((admin, False), (staff, False), (superuser, True)):
        client.force_authenticate(user=user)
        response = client.get("/api/v1/platform/workspaces/me/")
        assert response.status_code == 200
        assert response.data["is_platform_admin"] is expected
        assert response.data["is_platform_superuser"] is expected
        assert _is_platform_superuser(user) is expected


def test_embedded_plans_list_only_the_platform_workspace_plans(db, settings):
    _embedded(settings)
    platform = _workspace("platform")
    shop = _workspace("shop")
    SubscriptionPlan.objects.create(workspace=platform, name="Base", price=Decimal("40.00"))
    SubscriptionPlan.objects.create(workspace=platform, name="Retired", price=Decimal("10.00"), is_active=False)
    SubscriptionPlan.objects.create(workspace=shop, name="Coffee club", price=Decimal("25.00"))

    response = APIClient().get("/api/v1/platform/plans/")

    assert response.status_code == 200
    assert _plan_names(response) == ["Base"]


def test_embedded_plans_are_empty_without_a_platform_workspace(db, settings):
    _embedded(settings, slug="missing")
    shop = _workspace("shop")
    SubscriptionPlan.objects.create(workspace=shop, name="Coffee club", price=Decimal("25.00"))

    response = APIClient().get("/api/v1/platform/plans/")

    assert response.status_code == 200
    assert _plan_names(response) == []


def test_standalone_plans_list_every_active_plan(db, settings):
    settings.PLATFORM_EMBEDDED = False
    first = _workspace("first")
    second = _workspace("second")
    SubscriptionPlan.objects.create(workspace=first, name="Starter", price=Decimal("20.00"))
    SubscriptionPlan.objects.create(workspace=second, name="Growth", price=Decimal("60.00"))

    response = APIClient().get("/api/v1/platform/plans/")

    assert response.status_code == 200
    assert _plan_names(response) == ["Growth", "Starter"]
