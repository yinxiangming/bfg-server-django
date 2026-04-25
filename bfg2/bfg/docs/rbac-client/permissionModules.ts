/**
 * RBAC permission module definitions.
 *
 * Place in: src/config/permissionModules.ts
 *
 * Defines the modules and actions rendered in the permission matrix editor.
 * Add/remove entries here to extend the matrix without touching UI code.
 */

export interface PermissionAction {
  key: string;
  label: string;
}

export interface PermissionModule {
  key: string;         // matches the key in StaffRole.permissions JSON
  label: string;       // display name
  group: string;       // section heading in the matrix
}

export const PERMISSION_ACTIONS: PermissionAction[] = [
  { key: 'view',   label: '查看' },
  { key: 'list',   label: '列表' },
  { key: 'create', label: '新建' },
  { key: 'update', label: '编辑' },
  { key: 'delete', label: '删除' },
];

export const PERMISSION_MODULES: PermissionModule[] = [
  // Shop
  { key: 'shop.product',  label: '商品',     group: '商城' },
  { key: 'shop.order',    label: '订单',     group: '商城' },
  { key: 'shop.customer', label: '客户',     group: '商城' },
  { key: 'shop.category', label: '分类',     group: '商城' },
  // Delivery
  { key: 'delivery',      label: '配送',     group: '配送' },
  // Finance
  { key: 'finance.invoice', label: '发票',   group: '财务' },
  { key: 'finance.payment', label: '支付',   group: '财务' },
  // Marketing
  { key: 'marketing',     label: '营销',     group: '营销' },
  // Web / CMS
  { key: 'web',           label: 'CMS 内容', group: '内容' },
  // Support
  { key: 'support',       label: '工单支持', group: '支持' },
];

/** Group modules by their `group` field for rendering section headers. */
export function groupModules(): { group: string; modules: PermissionModule[] }[] {
  const map = new Map<string, PermissionModule[]>();
  for (const mod of PERMISSION_MODULES) {
    if (!map.has(mod.group)) map.set(mod.group, []);
    map.get(mod.group)!.push(mod);
  }
  return Array.from(map.entries()).map(([group, modules]) => ({ group, modules }));
}

/**
 * Convert a matrix state (Record<moduleKey, Set<actionKey>>) to the
 * permissions JSON stored in StaffRole.permissions.
 *
 * Optimisation: if all actions are selected for a module, store ["*"].
 */
export function matrixToPermissions(
  matrix: Record<string, Set<string>>
): Record<string, string[]> {
  const result: Record<string, string[]> = {};
  for (const [moduleKey, actions] of Object.entries(matrix)) {
    const list = Array.from(actions);
    if (list.length === 0) continue;
    result[moduleKey] =
      list.length === PERMISSION_ACTIONS.length ? ['*'] : list;
  }
  return result;
}

/**
 * Convert a permissions JSON (from the API) back to matrix state.
 * Expands ["*"] to all actions.
 */
export function permissionsToMatrix(
  permissions: Record<string, string[] | boolean>
): Record<string, Set<string>> {
  const allActions = PERMISSION_ACTIONS.map((a) => a.key);
  const matrix: Record<string, Set<string>> = {};

  for (const mod of PERMISSION_MODULES) {
    matrix[mod.key] = new Set();
  }

  for (const [moduleKey, value] of Object.entries(permissions)) {
    if (moduleKey === '*') {
      // Wildcard module: grant specified actions to all modules
      const actions =
        value === true || (Array.isArray(value) && value.includes('*'))
          ? allActions
          : Array.isArray(value)
          ? value
          : [];
      for (const mod of PERMISSION_MODULES) {
        matrix[mod.key] = new Set(actions);
      }
      continue;
    }

    // Exact module or prefix match
    const targets = PERMISSION_MODULES.filter(
      (m) => m.key === moduleKey || m.key.startsWith(moduleKey + '.')
    );
    const actions =
      value === true || (Array.isArray(value) && value.includes('*'))
        ? allActions
        : Array.isArray(value)
        ? value
        : [];

    for (const t of targets) {
      matrix[t.key] = new Set(actions);
    }
  }

  return matrix;
}
