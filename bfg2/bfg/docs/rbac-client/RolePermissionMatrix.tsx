/**
 * RolePermissionMatrix — visual checkbox grid for editing role permissions.
 *
 * Place in: src/components/admin/RolePermissionMatrix.tsx
 *
 * Renders a table where rows = modules, columns = actions.
 * Each cell is a checkbox. Row header has a "全选" toggle.
 * Grouped by module category (商城, 财务, ...) with section dividers.
 *
 * Usage:
 *   <RolePermissionMatrix
 *     permissions={role.permissions}
 *     onChange={(newPermissions) => setPermissions(newPermissions)}
 *     readOnly={role.is_system}
 *   />
 */

'use client';

import { useState, useEffect } from 'react';
import {
  PERMISSION_ACTIONS,
  groupModules,
  matrixToPermissions,
  permissionsToMatrix,
  type PermissionModule,
} from '@/config/permissionModules';

type PermissionMap = Record<string, string[] | boolean>;

interface RolePermissionMatrixProps {
  permissions: PermissionMap;
  onChange?: (permissions: PermissionMap) => void;
  readOnly?: boolean;
}

export function RolePermissionMatrix({
  permissions,
  onChange,
  readOnly = false,
}: RolePermissionMatrixProps) {
  const [matrix, setMatrix] = useState<Record<string, Set<string>>>(() =>
    permissionsToMatrix(permissions)
  );

  // Sync when external permissions change (e.g. after save/reload)
  useEffect(() => {
    setMatrix(permissionsToMatrix(permissions));
  }, [permissions]);

  function toggle(moduleKey: string, actionKey: string) {
    if (readOnly) return;
    setMatrix((prev) => {
      const next = { ...prev, [moduleKey]: new Set(prev[moduleKey]) };
      if (next[moduleKey].has(actionKey)) {
        next[moduleKey].delete(actionKey);
      } else {
        next[moduleKey].add(actionKey);
      }
      onChange?.(matrixToPermissions(next));
      return next;
    });
  }

  function toggleRow(mod: PermissionModule) {
    if (readOnly) return;
    setMatrix((prev) => {
      const current = prev[mod.key] ?? new Set();
      const allSelected = PERMISSION_ACTIONS.every((a) => current.has(a.key));
      const next = {
        ...prev,
        [mod.key]: allSelected
          ? new Set<string>()
          : new Set(PERMISSION_ACTIONS.map((a) => a.key)),
      };
      onChange?.(matrixToPermissions(next));
      return next;
    });
  }

  function toggleColumn(actionKey: string) {
    if (readOnly) return;
    setMatrix((prev) => {
      const allSelected = Object.values(prev).every((s) => s.has(actionKey));
      const next: Record<string, Set<string>> = {};
      for (const [k, s] of Object.entries(prev)) {
        const copy = new Set(s);
        if (allSelected) copy.delete(actionKey);
        else copy.add(actionKey);
        next[k] = copy;
      }
      onChange?.(matrixToPermissions(next));
      return next;
    });
  }

  const groups = groupModules();

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            <th className="px-4 py-3 text-left font-medium text-gray-600 w-40">
              权限模块
            </th>
            <th className="px-3 py-3 text-center font-medium text-gray-600 w-16">
              全选
            </th>
            {PERMISSION_ACTIONS.map((action) => (
              <th
                key={action.key}
                className="px-3 py-3 text-center font-medium text-gray-600 w-20"
              >
                <button
                  type="button"
                  onClick={() => toggleColumn(action.key)}
                  disabled={readOnly}
                  className="hover:text-blue-600 disabled:cursor-default"
                  title={readOnly ? undefined : `全选/取消 ${action.label}`}
                >
                  {action.label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map(({ group, modules }) => (
            <>
              {/* Group header row */}
              <tr key={`group-${group}`} className="bg-gray-100">
                <td
                  colSpan={2 + PERMISSION_ACTIONS.length}
                  className="px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  {group}
                </td>
              </tr>

              {/* Module rows */}
              {modules.map((mod, idx) => {
                const current = matrix[mod.key] ?? new Set();
                const allSelected = PERMISSION_ACTIONS.every((a) =>
                  current.has(a.key)
                );
                const someSelected =
                  !allSelected && PERMISSION_ACTIONS.some((a) => current.has(a.key));

                return (
                  <tr
                    key={mod.key}
                    className={`border-t border-gray-100 ${
                      idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
                    } hover:bg-blue-50/30 transition-colors`}
                  >
                    {/* Module label */}
                    <td className="px-4 py-2.5 text-gray-700 font-medium">
                      <div>{mod.label}</div>
                      <div className="text-xs text-gray-400 font-mono">{mod.key}</div>
                    </td>

                    {/* Row "全选" toggle */}
                    <td className="px-3 py-2.5 text-center">
                      <button
                        type="button"
                        onClick={() => toggleRow(mod)}
                        disabled={readOnly}
                        className={`w-5 h-5 rounded border-2 inline-flex items-center justify-center transition-colors
                          ${readOnly ? 'cursor-default' : 'cursor-pointer hover:border-blue-500'}
                          ${
                            allSelected
                              ? 'bg-blue-600 border-blue-600'
                              : someSelected
                              ? 'bg-blue-200 border-blue-400'
                              : 'bg-white border-gray-300'
                          }`}
                        title={allSelected ? '取消全选' : '全选'}
                      >
                        {allSelected && (
                          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                        {someSelected && !allSelected && (
                          <span className="w-2 h-0.5 bg-blue-600 rounded" />
                        )}
                      </button>
                    </td>

                    {/* Action checkboxes */}
                    {PERMISSION_ACTIONS.map((action) => {
                      const checked = current.has(action.key);
                      return (
                        <td key={action.key} className="px-3 py-2.5 text-center">
                          <button
                            type="button"
                            onClick={() => toggle(mod.key, action.key)}
                            disabled={readOnly}
                            className={`w-5 h-5 rounded border-2 inline-flex items-center justify-center transition-colors
                              ${readOnly ? 'cursor-default' : 'cursor-pointer hover:border-blue-500'}
                              ${checked ? 'bg-blue-600 border-blue-600' : 'bg-white border-gray-300'}`}
                            aria-checked={checked}
                            role="checkbox"
                          >
                            {checked && (
                              <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                              </svg>
                            )}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </>
          ))}
        </tbody>
      </table>

      {readOnly && (
        <div className="px-4 py-2 text-xs text-gray-400 border-t border-gray-200 bg-gray-50">
          系统角色权限不可修改
        </div>
      )}
    </div>
  );
}
