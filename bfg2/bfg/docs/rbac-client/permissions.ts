/**
 * RBAC permission utilities for bfg-client-react.
 *
 * Permission format: "module.resource.action"
 *   e.g.  "shop.product.create"
 *         "delivery.view"
 *         "finance.invoice.delete"
 *
 * Role.permissions JSON (from GET /api/v1/me/ → staff_member.role.permissions):
 *   { "shop": ["*"], "delivery": ["view", "list"], "*": ["*"] }
 */

export type PermissionMap = Record<string, string[] | boolean>;

/**
 * Check whether a permission map grants the given permission key.
 *
 * Resolution order:
 *  1. Wildcard module "*" — grants everything
 *  2. Exact module match (all parts except last) — checks action in list
 *  3. Parent module match — e.g. key "shop.product.create" also checked against "shop"
 */
export function hasPermission(permissions: PermissionMap, key: string): boolean {
  if (!key || !permissions) return false;

  const parts = key.split('.');
  const action = parts[parts.length - 1];

  // Wildcard module grants all
  if (checkModuleAction(permissions['*'], action)) return true;

  // Walk from most-specific module down to least-specific
  // e.g. "shop.product.create" → try "shop.product", then "shop"
  for (let i = parts.length - 1; i >= 1; i--) {
    const module = parts.slice(0, i).join('.');
    if (checkModuleAction(permissions[module], action)) return true;
  }

  return false;
}

function checkModuleAction(moduleValue: string[] | boolean | undefined, action: string): boolean {
  if (moduleValue === undefined || moduleValue === false) return false;
  if (moduleValue === true) return true;
  if (Array.isArray(moduleValue)) {
    return moduleValue.includes('*') || moduleValue.includes(action);
  }
  return false;
}

/** Returns true if the user holds ANY of the given permission keys. */
export function hasAnyPermission(permissions: PermissionMap, keys: string[]): boolean {
  return keys.some((k) => hasPermission(permissions, k));
}

/** Returns true if the user holds ALL of the given permission keys. */
export function hasAllPermissions(permissions: PermissionMap, keys: string[]): boolean {
  return keys.every((k) => hasPermission(permissions, k));
}
