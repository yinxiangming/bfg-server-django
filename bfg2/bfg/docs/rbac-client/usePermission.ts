/**
 * RBAC hooks for bfg-client-react.
 *
 * Place in: src/hooks/usePermission.ts
 *
 * Requires:
 *  - useAuth() hook that returns { staffMember } from auth context/store.
 *  - staffMember shape matches GET /api/v1/me/ → staff_member field.
 */

import { hasPermission, hasAnyPermission, hasAllPermissions, PermissionMap } from '@/lib/permissions';

interface StaffRole {
  id: number;
  code: string;
  name: string;
  permissions: PermissionMap;
}

interface StaffMember {
  id: number;
  is_active: boolean;
  role: StaffRole;
}

// Replace with your actual auth hook/selector
// e.g. from AuthContext, Redux store, Zustand, etc.
declare function useAuth(): { staffMember: StaffMember | null };

/** Returns true when the current user has the given permission. */
export function usePermission(permission: string): boolean {
  const { staffMember } = useAuth();
  if (!staffMember?.is_active) return false;
  return hasPermission(staffMember.role.permissions, permission);
}

/** Returns true when the user has ANY of the given permissions. */
export function useAnyPermission(permissions: string[]): boolean {
  const { staffMember } = useAuth();
  if (!staffMember?.is_active) return false;
  return hasAnyPermission(staffMember.role.permissions, permissions);
}

/** Returns true when the user has ALL of the given permissions. */
export function useAllPermissions(permissions: string[]): boolean {
  const { staffMember } = useAuth();
  if (!staffMember?.is_active) return false;
  return hasAllPermissions(staffMember.role.permissions, permissions);
}

/** Returns true when the current user's role code is 'admin'. */
export function useIsAdmin(): boolean {
  const { staffMember } = useAuth();
  return staffMember?.is_active === true && staffMember.role.code === 'admin';
}

/** Returns true when the user is an active staff member of this workspace. */
export function useIsStaff(): boolean {
  const { staffMember } = useAuth();
  return staffMember?.is_active === true;
}

/** Returns the current user's role object, or null if not a staff member. */
export function useRole(): StaffRole | null {
  const { staffMember } = useAuth();
  return staffMember?.is_active ? staffMember.role : null;
}
