/**
 * Roles management page — /admin/staff/roles
 *
 * Place in: src/app/admin/staff/roles/page.tsx
 *
 * Features:
 *  - List all workspace roles (name, code, staff count, system badge)
 *  - Create custom role (name + description)
 *  - Edit role: inline permission matrix editor
 *  - Delete non-system role (with confirmation)
 *  - Admin-only page (ProtectedPage wraps the whole thing)
 *
 * API calls:
 *  GET    /api/v1/staff-roles/          — list
 *  POST   /api/v1/staff-roles/          — create
 *  PATCH  /api/v1/staff-roles/{id}/     — update permissions / name
 *  DELETE /api/v1/staff-roles/{id}/     — delete
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { ProtectedPage } from '@/components/auth/ProtectedPage';
import { RolePermissionMatrix } from '@/components/admin/RolePermissionMatrix';

// ─── Types ───────────────────────────────────────────────────────

interface StaffRole {
  id: number;
  name: string;
  code: string;
  description: string;
  permissions: Record<string, string[] | boolean>;
  is_system: boolean;
  is_active: boolean;
  created_at: string;
}

// ─── API helpers (replace with your project's fetch wrapper) ─────

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiPost<T>(path: string, body: object): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    credentials: 'include',
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiPatch<T>(path: string, body: object): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    credentials: 'include',
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`/api/v1${path}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error(await res.text());
}

// ─── Sub-components ───────────────────────────────────────────────

function RoleBadge({ role }: { role: StaffRole }) {
  const color =
    role.code === 'admin'
      ? 'bg-red-100 text-red-700'
      : role.code === 'manager'
      ? 'bg-orange-100 text-orange-700'
      : role.is_system
      ? 'bg-gray-100 text-gray-600'
      : 'bg-blue-100 text-blue-700';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono font-medium ${color}`}>
      {role.code}
    </span>
  );
}

function CreateRoleModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (role: StaffRole) => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const role = await apiPost<StaffRole>('/staff-roles/', { name, description });
      onCreated(role);
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">新建角色</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              角色名称 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="例：内容编辑"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              描述
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="可选，说明该角色的职责范围"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving || !name.trim()}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? '创建中…' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────

export default function RolesPage() {
  const [roles, setRoles] = useState<StaffRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editingPermissions, setEditingPermissions] = useState<
    Record<number, Record<string, string[] | boolean>>
  >({});
  const [saving, setSaving] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ results: StaffRole[] }>('/staff-roles/');
      setRoles(data.results ?? (data as unknown as StaffRole[]));
    } catch {
      setError('加载角色列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function toggleExpand(id: number) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  async function handleSavePermissions(role: StaffRole) {
    const permissions = editingPermissions[role.id] ?? role.permissions;
    setSaving(role.id);
    try {
      const updated = await apiPatch<StaffRole>(`/staff-roles/${role.id}/`, { permissions });
      setRoles((prev) => prev.map((r) => (r.id === role.id ? updated : r)));
      setEditingPermissions((prev) => {
        const next = { ...prev };
        delete next[role.id];
        return next;
      });
    } catch {
      setError('保存失败，请重试');
    } finally {
      setSaving(null);
    }
  }

  async function handleDelete(role: StaffRole) {
    if (!confirm(`确认删除角色「${role.name}」？此操作不可恢复。`)) return;
    setDeleting(role.id);
    try {
      await apiDelete(`/staff-roles/${role.id}/`);
      setRoles((prev) => prev.filter((r) => r.id !== role.id));
      if (expandedId === role.id) setExpandedId(null);
    } catch {
      setError('删除失败');
    } finally {
      setDeleting(null);
    }
  }

  return (
    <ProtectedPage requireAdmin>
      <div className="max-w-5xl mx-auto py-8 px-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">角色权限</h1>
            <p className="text-sm text-gray-500 mt-1">
              管理工作区角色及其对各功能模块的访问权限
            </p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
          >
            <span className="text-lg leading-none">+</span>
            新建角色
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg flex justify-between">
            {error}
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">✕</button>
          </div>
        )}

        {/* Role list */}
        {loading ? (
          <div className="text-center py-16 text-gray-400">加载中…</div>
        ) : (
          <div className="space-y-3">
            {roles.map((role) => {
              const isExpanded = expandedId === role.id;
              const pendingPermissions = editingPermissions[role.id];
              const isDirty = pendingPermissions !== undefined;

              return (
                <div
                  key={role.id}
                  className="border border-gray-200 rounded-xl overflow-hidden bg-white shadow-sm"
                >
                  {/* Role row (click to expand) */}
                  <button
                    type="button"
                    onClick={() => toggleExpand(role.id)}
                    className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors text-left"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-semibold text-gray-900">{role.name}</span>
                      <RoleBadge role={role} />
                      {role.is_system && (
                        <span className="text-xs text-gray-400 border border-gray-200 rounded px-1.5 py-0.5">
                          系统
                        </span>
                      )}
                      {isDirty && (
                        <span className="text-xs text-amber-600 border border-amber-200 bg-amber-50 rounded px-1.5 py-0.5">
                          未保存
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      {role.description && (
                        <span className="text-sm text-gray-400 hidden sm:block">
                          {role.description}
                        </span>
                      )}
                      <span className="text-gray-400 text-sm">
                        {isExpanded ? '▲' : '▼'}
                      </span>
                    </div>
                  </button>

                  {/* Expanded: permission matrix */}
                  {isExpanded && (
                    <div className="border-t border-gray-200 px-5 py-4">
                      <RolePermissionMatrix
                        permissions={pendingPermissions ?? role.permissions}
                        readOnly={role.is_system}
                        onChange={(newPerms) =>
                          setEditingPermissions((prev) => ({
                            ...prev,
                            [role.id]: newPerms,
                          }))
                        }
                      />

                      {/* Action buttons */}
                      <div className="flex justify-between items-center mt-4">
                        <div>
                          {!role.is_system && (
                            <button
                              type="button"
                              onClick={() => handleDelete(role)}
                              disabled={deleting === role.id}
                              className="text-sm text-red-500 hover:text-red-700 disabled:opacity-50"
                            >
                              {deleting === role.id ? '删除中…' : '删除角色'}
                            </button>
                          )}
                        </div>
                        {!role.is_system && (
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                setEditingPermissions((prev) => {
                                  const next = { ...prev };
                                  delete next[role.id];
                                  return next;
                                });
                              }}
                              disabled={!isDirty}
                              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-30"
                            >
                              撤销修改
                            </button>
                            <button
                              type="button"
                              onClick={() => handleSavePermissions(role)}
                              disabled={!isDirty || saving === role.id}
                              className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
                            >
                              {saving === role.id ? '保存中…' : '保存权限'}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Create modal */}
        {showCreate && (
          <CreateRoleModal
            onClose={() => setShowCreate(false)}
            onCreated={(role) => {
              setRoles((prev) => [...prev, role]);
              setShowCreate(false);
              setExpandedId(role.id);
            }}
          />
        )}
      </div>
    </ProtectedPage>
  );
}
