"""
Unit tests for BFG RBAC — permission classes and MeSerializer staff_member field.

Pure unit tests: no database, no HTTP. Dependencies are mocked with SimpleNamespace
and unittest.mock so these run without a running Django app (only settings needed).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_role(code='staff', permissions=None):
    return SimpleNamespace(
        id=1,
        code=code,
        name=code.title(),
        permissions=permissions or {},
    )


def _make_staff(role=None, is_active=True):
    return SimpleNamespace(
        id=10,
        pk=10,
        is_active=is_active,
        role=role or _make_role(),
    )


def _make_request(workspace=None, user=None):
    req = MagicMock()
    req.workspace = workspace or SimpleNamespace(id=1, name='Test WS')
    req.user = user or SimpleNamespace(id=99, is_authenticated=True, is_superuser=False)
    return req


# ═══════════════════════════════════════════════════════════════════
#  HasPermission — permission class unit tests
# ═══════════════════════════════════════════════════════════════════

class TestHasPermission:
    """Tests for bfg.core.permissions.HasPermission"""

    def _check(self, role_permissions, required_permission, is_admin=False):
        """Helper: run HasPermission.has_permission with mocked StaffMember."""
        from bfg.core.permissions import HasPermission

        role = _make_role(code='admin' if is_admin else 'staff', permissions=role_permissions)
        staff = _make_staff(role=role)
        request = _make_request()

        view = MagicMock()
        view.required_permission = required_permission

        perm = HasPermission()

        with patch('bfg.core.permissions._superuser_bypasses_workspace_permissions', return_value=False), \
             patch('bfg.common.models.StaffMember') as MockSM:
            MockSM.objects.select_related.return_value.get.return_value = staff
            result = perm.has_permission(request, view)

        return result

    def test_admin_role_bypasses_all(self):
        assert self._check({}, 'shop.product.create', is_admin=True) is True

    def test_exact_module_match_grants(self):
        perms = {'shop.product': ['create', 'view']}
        assert self._check(perms, 'shop.product.create') is True

    def test_exact_module_match_denies_missing_action(self):
        perms = {'shop.product': ['view']}
        assert self._check(perms, 'shop.product.create') is False

    def test_wildcard_action_in_module(self):
        perms = {'shop.product': ['*']}
        assert self._check(perms, 'shop.product.delete') is True

    def test_global_wildcard_grants_all(self):
        perms = {'*': ['*']}
        assert self._check(perms, 'finance.invoice.delete') is True

    def test_no_matching_module_denies(self):
        perms = {'delivery': ['view']}
        assert self._check(perms, 'shop.product.create') is False

    def test_missing_required_permission_attr_allows(self):
        """When view has no required_permission, HasPermission allows through."""
        from bfg.core.permissions import HasPermission

        role = _make_role(code='staff', permissions={})
        staff = _make_staff(role=role)
        request = _make_request()
        view = MagicMock(spec=[])  # no required_permission attribute

        perm = HasPermission()

        with patch('bfg.core.permissions._superuser_bypasses_workspace_permissions', return_value=False), \
             patch('bfg.common.models.StaffMember') as MockSM:
            MockSM.objects.select_related.return_value.get.return_value = staff
            result = perm.has_permission(request, view)

        assert result is True

    def test_no_workspace_denies(self):
        from bfg.core.permissions import HasPermission

        request = _make_request()
        del request.workspace  # simulate missing workspace
        request.workspace = None

        view = MagicMock()
        view.required_permission = 'shop.product.view'

        perm = HasPermission()
        result = perm.has_permission(request, view)
        assert result is False

    def test_unauthenticated_denies(self):
        from bfg.core.permissions import HasPermission

        request = _make_request()
        request.user = SimpleNamespace(is_authenticated=False)

        view = MagicMock()
        view.required_permission = 'shop.product.view'

        perm = HasPermission()
        result = perm.has_permission(request, view)
        assert result is False

    def test_nonexistent_staff_member_denies(self):
        from bfg.core.permissions import HasPermission
        from django.core.exceptions import ObjectDoesNotExist

        request = _make_request()
        view = MagicMock()
        view.required_permission = 'shop.product.create'

        perm = HasPermission()

        with patch('bfg.core.permissions._superuser_bypasses_workspace_permissions', return_value=False), \
             patch('bfg.common.models.StaffMember') as MockSM:
            MockSM.DoesNotExist = Exception
            MockSM.objects.select_related.return_value.get.side_effect = MockSM.DoesNotExist
            result = perm.has_permission(request, view)

        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  IsWorkspaceAdmin
# ═══════════════════════════════════════════════════════════════════

class TestIsWorkspaceAdmin:

    def _run(self, role_code, is_superuser=False):
        from bfg.core.permissions import IsWorkspaceAdmin

        role = _make_role(code=role_code)
        staff = _make_staff(role=role)
        request = _make_request()
        request.user.is_superuser = is_superuser

        perm = IsWorkspaceAdmin()

        with patch('bfg.core.permissions._superuser_bypasses_workspace_permissions', return_value=is_superuser), \
             patch('bfg.common.models.StaffMember') as MockSM:
            MockSM.objects.get.return_value = staff
            result = perm.has_permission(request, MagicMock())

        return result

    def test_admin_role_allowed(self):
        assert self._run('admin') is True

    def test_manager_role_denied(self):
        assert self._run('manager') is False

    def test_superuser_bypass(self):
        assert self._run('staff', is_superuser=True) is True


# ═══════════════════════════════════════════════════════════════════
#  MeSerializer — staff_member field
# ═══════════════════════════════════════════════════════════════════

class TestMeSerializerStaffMember:
    """Test that MeSerializer.to_representation() injects staff_member correctly."""

    def _run_repr(self, staff_obj):
        """Call to_representation on MeSerializer with mocked deps."""
        from bfg.common.serializers import MeSerializer

        user = SimpleNamespace(
            id=1, username='alice', email='alice@example.com',
            first_name='Alice', last_name='Smith', phone='',
            avatar=None, language='en', timezone_name='UTC',
            is_active=True, is_staff=False, is_superuser=False,
        )

        request = _make_request(user=user)
        serializer = MeSerializer(context={'request': request})

        # Patch super().to_representation to avoid DB calls
        base_data = {
            'id': 1, 'username': 'alice', 'email': 'alice@example.com',
            'first_name': 'Alice', 'last_name': 'Smith', 'phone': '',
            'avatar': None, 'language': 'en', 'timezone_name': 'UTC',
            'customer': None, 'is_active': True, 'is_staff': False, 'is_superuser': False,
        }

        # CustomerService and StaffMember are imported locally inside to_representation
        # via `from bfg.common.services import CustomerService` and
        # `from bfg.common.models import StaffMember`. Patch at the package-level
        # attribute so the in-function import picks up the mock.
        with patch('bfg.common.services.CustomerService') as MockCS, \
             patch('bfg.common.models.StaffMember') as MockSM, \
             patch('rest_framework.serializers.ModelSerializer.to_representation',
                   return_value=dict(base_data)):

            MockCS.return_value.get_customer_by_user.return_value = None

            if staff_obj is None:
                MockSM.DoesNotExist = Exception
                MockSM.all_objects.select_related.return_value.get.side_effect = MockSM.DoesNotExist
            else:
                MockSM.all_objects.select_related.return_value.get.return_value = staff_obj

            result = serializer.to_representation(user)

        return result

    def test_staff_member_present_for_staff(self):
        role = _make_role(code='manager', permissions={'shop': ['*']})
        staff = _make_staff(role=role)
        data = self._run_repr(staff)

        assert 'staff_member' in data
        sm = data['staff_member']
        assert sm is not None
        assert sm['id'] == 10
        assert sm['is_active'] is True
        assert sm['role']['code'] == 'manager'
        assert sm['role']['permissions'] == {'shop': ['*']}

    def test_staff_member_null_for_non_staff(self):
        data = self._run_repr(None)
        assert 'staff_member' in data
        assert data['staff_member'] is None

    def test_staff_member_includes_required_fields(self):
        role = _make_role(code='admin', permissions={'*': ['*']})
        staff = _make_staff(role=role)
        data = self._run_repr(staff)

        sm = data['staff_member']
        assert set(sm.keys()) == {'id', 'is_active', 'role'}
        assert set(sm['role'].keys()) == {'id', 'code', 'name', 'permissions'}


# ═══════════════════════════════════════════════════════════════════
#  StaffMemberViewSet — last-admin guard
# ═══════════════════════════════════════════════════════════════════

class TestStaffMemberViewSetLastAdminGuard:
    """Ensure StaffMemberViewSet.destroy() refuses to remove the last admin."""

    def _make_viewset(self, remaining_admins_count=1):
        from bfg.common.views import StaffMemberViewSet
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        request = factory.delete('/api/v1/staff-members/10/')
        request.workspace = SimpleNamespace(id=1)
        request.user = SimpleNamespace(id=99, is_authenticated=True, is_superuser=False)

        admin_role = _make_role(code='admin')
        instance = _make_staff(role=admin_role)

        viewset = StaffMemberViewSet()
        viewset.request = request
        viewset.kwargs = {}
        viewset.format_kwarg = None
        viewset.get_object = MagicMock(return_value=instance)

        with patch('bfg.common.models.StaffMember') as MockSM:
            MockSM.all_objects.filter.return_value.exclude.return_value.count.return_value = remaining_admins_count
            response = viewset.destroy(request)

        return response

    def test_destroy_blocked_when_last_admin(self):
        response = self._make_viewset(remaining_admins_count=0)
        assert response.status_code == 400
        assert 'last admin' in response.data['detail'].lower()

    def test_destroy_allowed_when_another_admin_exists(self):
        from unittest.mock import patch as _patch
        from bfg.common.views import StaffMemberViewSet

        admin_role = _make_role(code='admin')
        instance = _make_staff(role=admin_role)

        viewset = StaffMemberViewSet()
        viewset.request = MagicMock()
        viewset.request.workspace = SimpleNamespace(id=1)
        viewset.get_object = MagicMock(return_value=instance)
        viewset.perform_destroy = MagicMock()

        with _patch('bfg.common.models.StaffMember') as MockSM:
            MockSM.all_objects.filter.return_value.exclude.return_value.count.return_value = 1
            response = viewset.destroy(viewset.request)

        assert response.status_code == 204
        viewset.perform_destroy.assert_called_once_with(instance)
