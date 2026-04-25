/**
 * ProtectedPage — route-level RBAC guard for Next.js pages.
 *
 * Place in: src/components/auth/ProtectedPage.tsx
 *
 * Usage (wrap the page content):
 *
 *   // Require any staff login
 *   export default function OrdersPage() {
 *     return (
 *       <ProtectedPage>
 *         <OrderList />
 *       </ProtectedPage>
 *     );
 *   }
 *
 *   // Require specific permission
 *   export default function CreateProductPage() {
 *     return (
 *       <ProtectedPage permission="shop.product.create">
 *         <CreateProductForm />
 *       </ProtectedPage>
 *     );
 *   }
 *
 *   // Admin-only page
 *   export default function StaffPage() {
 *     return (
 *       <ProtectedPage requireAdmin>
 *         <StaffList />
 *       </ProtectedPage>
 *     );
 *   }
 */

'use client';

import { ReactNode, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { usePermission, useIsAdmin, useIsStaff } from '@/hooks/usePermission';

interface ProtectedPageProps {
  /** Required permission key e.g. "shop.product.create". */
  permission?: string;
  /** When true, only the admin role can access. */
  requireAdmin?: boolean;
  /** Redirect path when unauthenticated. Defaults to "/login". */
  loginPath?: string;
  /** Redirect path when authenticated but not authorized. Defaults to "/403". */
  forbiddenPath?: string;
  children: ReactNode;
}

export function ProtectedPage({
  permission,
  requireAdmin,
  loginPath = '/login',
  forbiddenPath = '/403',
  children,
}: ProtectedPageProps) {
  const router = useRouter();
  const isStaff = useIsStaff();
  const isAdmin = useIsAdmin();
  const hasPermission = usePermission(permission ?? '');

  useEffect(() => {
    if (!isStaff) {
      router.replace(loginPath);
      return;
    }
    if (requireAdmin && !isAdmin) {
      router.replace(forbiddenPath);
      return;
    }
    if (permission && !hasPermission) {
      router.replace(forbiddenPath);
    }
  }, [isStaff, isAdmin, hasPermission]);

  // Render nothing while redirect is in progress
  if (!isStaff) return null;
  if (requireAdmin && !isAdmin) return null;
  if (permission && !hasPermission) return null;

  return <>{children}</>;
}
