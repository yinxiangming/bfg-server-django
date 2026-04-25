/**
 * Staff member management page — /admin/staff
 *
 * Place in: src/app/admin/staff/page.tsx
 *
 * Features:
 *  - List all staff members (name, email, role badge, status, joined date)
 *  - Invite user by email + assign role
 *  - Change a staff member's role (inline dropdown)
 *  - Deactivate / reactivate staff member
 *  - Remove staff member (with confirmation; refuses to remove last admin)
 *  - Admin-only page
 *
 * API calls:
 *  GET    /api/v1/staff-members/          — list staff
 *  GET    /api/v1/staff-roles/            — load role options
 *  POST   /api/v1/staff-members/          — invite (user_id + role_id)
 *  GET    /api/v1/users/?search=email     — look up user by email for invite
 *  PATCH  /api/v1/staff-members/{id}/     — change role / toggle active
 *  DELETE /api/v1/staff-members/{id}/     — remove
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { ProtectedPage } from '@/components/auth/ProtectedPage';

// ─── Types ───────────────────────────────────────────────────────

interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

interface StaffRole {
  id: number;
  name: string;
  code: string;
}

interface StaffMember {
  id: number;
  user: User;
  role: StaffRole;
  is_active: boolean;
  created_at: string;
}

// ─── API helpers ─────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
    credentials: 'include',
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? '请求失败');
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ─── Sub-components ───────────────────────────────────────────────

function RolePill({ role }: { role: StaffRole }) {
  const color =
    role.code === 'admin'
      ? 'bg-red-100 text-red-700 border-red-200'
      : role.code === 'manager'
      ? 'bg-orange-100 text-orange-700 border-orange-200'
      : 'bg-blue-100 text-blue-700 border-blue-200';
  return (
    <span className={`inline-block px-2 py-0.5 rounded border text-xs font-medium ${color}`}>
      {role.name}
    </span>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${
        active ? 'bg-green-500' : 'bg-gray-300'
      }`}
    />
  );
}

function Avatar({ user }: { user: User }) {
  const initials = `${user.first_name?.[0] ?? ''}${user.last_name?.[0] ?? ''}`.toUpperCase() || user.email[0].toUpperCase();
  return (
    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-indigo-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
      {initials}
    </div>
  );
}

// ─── Invite Modal ─────────────────────────────────────────────────

function InviteModal({
  roles,
  onClose,
  onInvited,
}: {
  roles: StaffRole[];
  onClose: () => void;
  onInvited: (member: StaffMember) => void;
}) {
  const [email, setEmail] = useState('');
  const [selectedRole, setSelectedRole] = useState<number>(roles[0]?.id ?? 0);
  const [searching, setSearching] = useState(false);
  const [foundUser, setFoundUser] = useState<User | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSearching(true);
    setFoundUser(null);
    setNotFound(false);
    setError('');
    try {
      const data = await apiFetch<{ results: User[] }>(`/users/?search=${encodeURIComponent(email)}`);
      const users = data.results ?? [];
      const match = users.find((u) => u.email === email);
      if (match) {
        setFoundUser(match);
      } else {
        setNotFound(true);
      }
    } catch {
      setError('查询用户失败');
    } finally {
      setSearching(false);
    }
  }

  async function handleInvite() {
    if (!foundUser) return;
    setSaving(true);
    setError('');
    try {
      const member = await apiFetch<StaffMember>('/staff-members/', {
        method: 'POST',
        body: JSON.stringify({ user_id: foundUser.id, role_id: selectedRole }),
      });
      onInvited(member);
    } catch (err) {
      setError(err instanceof Error ? err.message : '邀请失败');
    } finally {
      setSaving(false);
    }
  }

  const displayName =
    foundUser
      ? `${foundUser.first_name} ${foundUser.last_name}`.trim() || foundUser.username
      : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">邀请员工</h2>

        {/* Step 1: search by email */}
        <form onSubmit={handleSearch} className="flex gap-2 mb-4">
          <input
            type="email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); setFoundUser(null); setNotFound(false); }}
            placeholder="输入用户邮箱"
            required
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={searching}
            className="px-3 py-2 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200 disabled:opacity-50"
          >
            {searching ? '查询中…' : '查询'}
          </button>
        </form>

        {notFound && (
          <p className="text-sm text-amber-600 mb-4">
            未找到该邮箱对应的用户，请确认邮箱或让用户先注册。
          </p>
        )}

        {/* Step 2: confirm user + select role */}
        {foundUser && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
              <Avatar user={foundUser} />
              <div>
                <p className="text-sm font-medium text-gray-900">{displayName}</p>
                <p className="text-xs text-gray-500">{foundUser.email}</p>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                分配角色
              </label>
              <select
                value={selectedRole}
                onChange={(e) => setSelectedRole(Number(e.target.value))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} ({r.code})
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        {error && <p className="text-sm text-red-600 mt-3">{error}</p>}

        <div className="flex justify-end gap-2 mt-6">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleInvite}
            disabled={!foundUser || saving}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? '邀请中…' : '确认邀请'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────

export default function StaffPage() {
  const [members, setMembers] = useState<StaffMember[]>([]);
  const [roles, setRoles] = useState<StaffRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [showInvite, setShowInvite] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [membersData, rolesData] = await Promise.all([
        apiFetch<{ results: StaffMember[] }>('/staff-members/'),
        apiFetch<{ results: StaffRole[] }>('/staff-roles/'),
      ]);
      setMembers(membersData.results ?? (membersData as unknown as StaffMember[]));
      setRoles(rolesData.results ?? (rolesData as unknown as StaffRole[]));
    } catch {
      setError('加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleRoleChange(member: StaffMember, roleId: number) {
    setUpdatingId(member.id);
    try {
      const updated = await apiFetch<StaffMember>(`/staff-members/${member.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ role_id: roleId }),
      });
      setMembers((prev) => prev.map((m) => (m.id === member.id ? updated : m)));
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新失败');
    } finally {
      setUpdatingId(null);
    }
  }

  async function handleToggleActive(member: StaffMember) {
    setUpdatingId(member.id);
    try {
      const updated = await apiFetch<StaffMember>(`/staff-members/${member.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !member.is_active }),
      });
      setMembers((prev) => prev.map((m) => (m.id === member.id ? updated : m)));
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新失败');
    } finally {
      setUpdatingId(null);
    }
  }

  async function handleRemove(member: StaffMember) {
    const name =
      `${member.user.first_name} ${member.user.last_name}`.trim() ||
      member.user.email;
    if (!confirm(`确认移除员工「${name}」？`)) return;
    setUpdatingId(member.id);
    try {
      await apiFetch(`/staff-members/${member.id}/`, { method: 'DELETE' });
      setMembers((prev) => prev.filter((m) => m.id !== member.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : '移除失败');
    } finally {
      setUpdatingId(null);
    }
  }

  const activeCount = members.filter((m) => m.is_active).length;

  return (
    <ProtectedPage requireAdmin>
      <div className="max-w-5xl mx-auto py-8 px-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">员工管理</h1>
            <p className="text-sm text-gray-500 mt-1">
              {activeCount} 名活跃员工 · 共 {members.length} 名
            </p>
          </div>
          <div className="flex gap-2">
            <a
              href="/admin/staff/roles"
              className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              角色权限
            </a>
            <button
              onClick={() => setShowInvite(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
            >
              <span className="text-lg leading-none">+</span>
              邀请员工
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg flex justify-between">
            {error}
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">✕</button>
          </div>
        )}

        {/* Staff table */}
        {loading ? (
          <div className="text-center py-16 text-gray-400">加载中…</div>
        ) : members.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            还没有员工，点击「邀请员工」添加。
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-5 py-3 text-left font-medium text-gray-600">员工</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">角色</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">状态</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">加入时间</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member, idx) => {
                  const name =
                    `${member.user.first_name} ${member.user.last_name}`.trim() ||
                    member.user.username;
                  const isUpdating = updatingId === member.id;
                  const joinedDate = new Date(member.created_at).toLocaleDateString('zh-CN');

                  return (
                    <tr
                      key={member.id}
                      className={`border-t border-gray-100 ${
                        idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
                      } ${isUpdating ? 'opacity-50' : ''}`}
                    >
                      {/* User info */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar user={member.user} />
                          <div>
                            <p className="font-medium text-gray-900">{name}</p>
                            <p className="text-xs text-gray-500">{member.user.email}</p>
                          </div>
                        </div>
                      </td>

                      {/* Role selector */}
                      <td className="px-4 py-3">
                        <select
                          value={member.role.id}
                          onChange={(e) => handleRoleChange(member, Number(e.target.value))}
                          disabled={isUpdating}
                          className="border border-gray-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white disabled:opacity-50"
                        >
                          {roles.map((r) => (
                            <option key={r.id} value={r.id}>{r.name}</option>
                          ))}
                        </select>
                      </td>

                      {/* Active status */}
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => handleToggleActive(member)}
                          disabled={isUpdating}
                          className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50"
                          title={member.is_active ? '点击停用' : '点击启用'}
                        >
                          <StatusDot active={member.is_active} />
                          {member.is_active ? '活跃' : '已停用'}
                        </button>
                      </td>

                      {/* Joined date */}
                      <td className="px-4 py-3 text-gray-500">{joinedDate}</td>

                      {/* Actions */}
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => handleRemove(member)}
                          disabled={isUpdating}
                          className="text-sm text-red-400 hover:text-red-600 disabled:opacity-30"
                        >
                          移除
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Invite modal */}
        {showInvite && (
          <InviteModal
            roles={roles}
            onClose={() => setShowInvite(false)}
            onInvited={(member) => {
              setMembers((prev) => [member, ...prev]);
              setShowInvite(false);
            }}
          />
        )}
      </div>
    </ProtectedPage>
  );
}
