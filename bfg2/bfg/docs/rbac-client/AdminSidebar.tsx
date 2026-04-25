/**
 * Admin sidebar that filters menu items based on RBAC.
 *
 * Place in: src/components/layout/AdminSidebar.tsx
 *
 * Renders only the menu items the current user is allowed to see.
 */

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext'; // adjust to your auth hook
import { useIsAdmin } from '@/hooks/usePermission';
import { hasPermission } from '@/lib/permissions';
import { adminMenuConfig, MenuItem } from '@/config/adminMenuConfig';

export function AdminSidebar() {
  const pathname = usePathname();
  const { staffMember } = useAuth();
  const isAdmin = useIsAdmin();
  const permissions = staffMember?.role.permissions ?? {};

  function isVisible(item: MenuItem): boolean {
    if (item.requireAdmin) return isAdmin;
    if (item.permission) return hasPermission(permissions, item.permission);
    return true; // always visible (e.g. Dashboard)
  }

  const visibleItems = adminMenuConfig.filter(isVisible);

  return (
    <nav className="sidebar">
      {visibleItems.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={pathname === item.href ? 'active' : ''}
        >
          {/* Replace with your icon component */}
          <span className="icon">{item.icon}</span>
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}
