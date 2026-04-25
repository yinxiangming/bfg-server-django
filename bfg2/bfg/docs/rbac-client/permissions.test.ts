/**
 * Jest unit tests for src/lib/permissions.ts
 *
 * Copy this file to bfg-client-react as:
 *   src/lib/__tests__/permissions.test.ts
 *
 * Run with: npx jest src/lib/__tests__/permissions.test.ts
 */

import { hasPermission, hasAnyPermission, hasAllPermissions } from '../permissions';

// ─── hasPermission ────────────────────────────────────────────────

describe('hasPermission', () => {
  test('returns false for empty permissions map', () => {
    expect(hasPermission({}, 'shop.product.create')).toBe(false);
  });

  test('returns false for empty key', () => {
    expect(hasPermission({ '*': ['*'] }, '')).toBe(false);
  });

  // Global wildcard
  test('global wildcard grants any permission', () => {
    expect(hasPermission({ '*': ['*'] }, 'shop.product.create')).toBe(true);
    expect(hasPermission({ '*': ['*'] }, 'finance.invoice.delete')).toBe(true);
    expect(hasPermission({ '*': ['*'] }, 'delivery.view')).toBe(true);
  });

  test('global wildcard with specific actions grants matching action', () => {
    const perms = { '*': ['view', 'list'] };
    expect(hasPermission(perms, 'shop.product.view')).toBe(true);
    expect(hasPermission(perms, 'shop.product.list')).toBe(true);
    expect(hasPermission(perms, 'shop.product.create')).toBe(false);
  });

  // Exact module match
  test('exact module grants listed action', () => {
    const perms = { 'shop.product': ['create', 'view'] };
    expect(hasPermission(perms, 'shop.product.create')).toBe(true);
    expect(hasPermission(perms, 'shop.product.view')).toBe(true);
  });

  test('exact module denies unlisted action', () => {
    const perms = { 'shop.product': ['view'] };
    expect(hasPermission(perms, 'shop.product.create')).toBe(false);
    expect(hasPermission(perms, 'shop.product.delete')).toBe(false);
  });

  test('wildcard action in module grants any action', () => {
    const perms = { 'shop.product': ['*'] };
    expect(hasPermission(perms, 'shop.product.create')).toBe(true);
    expect(hasPermission(perms, 'shop.product.delete')).toBe(true);
  });

  // Parent module (shorter prefix) match
  test('parent module wildcard covers child resources', () => {
    // {"shop": ["*"]} should grant "shop.product.create"
    const perms = { shop: ['*'] };
    expect(hasPermission(perms, 'shop.product.create')).toBe(true);
    expect(hasPermission(perms, 'shop.order.view')).toBe(true);
  });

  test('parent module specific actions checked against child key', () => {
    const perms = { shop: ['view', 'list'] };
    expect(hasPermission(perms, 'shop.product.view')).toBe(true);
    expect(hasPermission(perms, 'shop.product.create')).toBe(false);
  });

  test('module mismatch denies', () => {
    const perms = { delivery: ['*'] };
    expect(hasPermission(perms, 'shop.product.create')).toBe(false);
  });

  // boolean value
  test('boolean true grants all', () => {
    const perms = { 'shop.product': true as unknown as string[] };
    expect(hasPermission(perms, 'shop.product.create')).toBe(true);
  });

  test('boolean false denies all', () => {
    const perms = { 'shop.product': false as unknown as string[] };
    expect(hasPermission(perms, 'shop.product.create')).toBe(false);
  });

  // admin role typical shape
  test('admin role {"*":["*"]} grants everything', () => {
    const adminPerms = { '*': ['*'] };
    expect(hasPermission(adminPerms, 'shop.product.create')).toBe(true);
    expect(hasPermission(adminPerms, 'finance.payment.delete')).toBe(true);
    expect(hasPermission(adminPerms, 'delivery.shipment.view')).toBe(true);
  });

  // manager role typical shape
  test('manager role grants shop and delivery but not finance', () => {
    const managerPerms = { shop: ['*'], delivery: ['*'] };
    expect(hasPermission(managerPerms, 'shop.order.create')).toBe(true);
    expect(hasPermission(managerPerms, 'delivery.view')).toBe(true);
    expect(hasPermission(managerPerms, 'finance.invoice.view')).toBe(false);
  });

  // staff role typical shape
  test('staff role only allows view/list', () => {
    const staffPerms = { shop: ['view', 'list'], delivery: ['view', 'list'] };
    expect(hasPermission(staffPerms, 'shop.product.view')).toBe(true);
    expect(hasPermission(staffPerms, 'shop.product.create')).toBe(false);
    expect(hasPermission(staffPerms, 'delivery.view')).toBe(true);
    expect(hasPermission(staffPerms, 'delivery.delete')).toBe(false);
  });
});

// ─── hasAnyPermission ─────────────────────────────────────────────

describe('hasAnyPermission', () => {
  test('returns true if at least one key matches', () => {
    const perms = { shop: ['view'] };
    expect(hasAnyPermission(perms, ['shop.product.view', 'shop.product.create'])).toBe(true);
  });

  test('returns false when none match', () => {
    const perms = { delivery: ['*'] };
    expect(hasAnyPermission(perms, ['shop.product.view', 'finance.invoice.view'])).toBe(false);
  });

  test('empty keys array returns false', () => {
    expect(hasAnyPermission({ '*': ['*'] }, [])).toBe(false);
  });
});

// ─── hasAllPermissions ────────────────────────────────────────────

describe('hasAllPermissions', () => {
  test('returns true when all keys match', () => {
    const perms = { shop: ['*'], delivery: ['view'] };
    expect(hasAllPermissions(perms, ['shop.product.create', 'delivery.view'])).toBe(true);
  });

  test('returns false when any key is missing', () => {
    const perms = { shop: ['view'] };
    expect(hasAllPermissions(perms, ['shop.product.view', 'shop.product.create'])).toBe(false);
  });

  test('empty keys array returns true (vacuous truth)', () => {
    expect(hasAllPermissions({}, [])).toBe(true);
  });
});
