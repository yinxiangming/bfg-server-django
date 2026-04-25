/**
 * Admin sidebar menu configuration with per-item RBAC rules.
 *
 * Place in: src/config/adminMenuConfig.ts
 *
 * Each menu item optionally specifies a `permission` key or `requireAdmin` flag.
 * The sidebar component filters the list using the current user's role.
 *
 * Menu hiding is purely UX — the server enforces the same permissions via
 * DRF permission classes on every API endpoint.
 */

export interface MenuItem {
  label: string;
  href: string;
  /** Icon component name (import from your icon library) */
  icon?: string;
  /** If set, only render when hasPermission(permissions, permission) is true */
  permission?: string;
  /** If true, only the 'admin' role can see this item */
  requireAdmin?: boolean;
  children?: MenuItem[];
}

export const adminMenuConfig: MenuItem[] = [
  // Always visible to any staff member
  { label: '仪表盘', href: '/admin', icon: 'LayoutDashboard' },

  // Shop module
  {
    label: '商品管理',
    href: '/admin/products',
    icon: 'Package',
    permission: 'shop.product.view',
  },
  {
    label: '订单管理',
    href: '/admin/orders',
    icon: 'ShoppingCart',
    permission: 'shop.order.view',
  },
  {
    label: '客户管理',
    href: '/admin/customers',
    icon: 'Users',
    permission: 'shop.customer.view',
  },

  // Delivery module
  {
    label: '配送管理',
    href: '/admin/delivery',
    icon: 'Truck',
    permission: 'delivery.view',
  },

  // Marketing module
  {
    label: '营销活动',
    href: '/admin/marketing',
    icon: 'Megaphone',
    permission: 'marketing.view',
  },

  // Finance module
  {
    label: '财务',
    href: '/admin/finance',
    icon: 'CreditCard',
    permission: 'finance.invoice.view',
  },

  // Admin-only items
  {
    label: '员工管理',
    href: '/admin/staff',
    icon: 'UserCog',
    requireAdmin: true,
  },
  {
    label: '角色权限',
    href: '/admin/staff/roles',
    icon: 'Shield',
    requireAdmin: true,
  },
  {
    label: '系统设置',
    href: '/admin/settings',
    icon: 'Settings',
    requireAdmin: true,
  },
];
