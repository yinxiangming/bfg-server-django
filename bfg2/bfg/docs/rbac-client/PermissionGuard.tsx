/**
 * PermissionGuard — inline RBAC gate for conditional rendering.
 *
 * Place in: src/components/auth/PermissionGuard.tsx
 *
 * Usage:
 *   // Hide a button when user lacks "shop.product.create"
 *   <PermissionGuard permission="shop.product.create">
 *     <Button>Add Product</Button>
 *   </PermissionGuard>
 *
 *   // Show fallback when not admin
 *   <PermissionGuard requireAdmin fallback={<AccessDenied />}>
 *     <AdminPanel />
 *   </PermissionGuard>
 *
 *   // Require a specific role code
 *   <PermissionGuard role="manager">
 *     <ManagerTools />
 *   </PermissionGuard>
 */

import { ReactNode } from 'react';
import { usePermission, useIsAdmin, useRole } from '@/hooks/usePermission';

interface PermissionGuardProps {
  /** Permission key e.g. "shop.product.create". Checked when provided. */
  permission?: string;
  /** Role code that must match e.g. "manager". Checked when provided. */
  role?: string;
  /** When true, only admin role is allowed. */
  requireAdmin?: boolean;
  /** Rendered when access is denied. Defaults to null (renders nothing). */
  fallback?: ReactNode;
  children: ReactNode;
}

export function PermissionGuard({
  permission,
  role,
  requireAdmin,
  fallback = null,
  children,
}: PermissionGuardProps) {
  const hasPermission = usePermission(permission ?? '');
  const isAdmin = useIsAdmin();
  const currentRole = useRole();

  const permissionOk = permission ? hasPermission : true;
  const roleOk = role ? currentRole?.code === role : true;
  const adminOk = requireAdmin ? isAdmin : true;

  if (permissionOk && roleOk && adminOk) {
    return <>{children}</>;
  }
  return <>{fallback}</>;
}
