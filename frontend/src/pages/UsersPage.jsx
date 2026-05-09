import { useEffect, useState } from 'react'
import { usersAPI } from '../services/api'

const ROLE_LABEL = {
  owner: '擁有者',
  admin: '管理者',
  regular: '一般',
}

const ROLE_COLOR = {
  owner: 'bg-rose-900/40 text-rose-200 border-rose-700',
  admin: 'bg-amber-900/40 text-amber-200 border-amber-700',
  regular: 'bg-sky-900/40 text-sky-200 border-sky-700',
}

export default function UsersPage() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState('regular')
  const [resetResult, setResetResult] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await usersAPI.list()
      setUsers(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const create = async (e) => {
    e.preventDefault()
    if (!newUsername.trim() || newPassword.length < 8) {
      alert('帳號不可空白，密碼至少 8 字元')
      return
    }
    setCreating(true)
    try {
      await usersAPI.create(newUsername.trim(), newPassword, newRole)
      setNewUsername(''); setNewPassword(''); setNewRole('regular')
      await load()
    } catch (err) {
      alert('建立失敗：' + (err?.response?.data?.detail || err.message))
    } finally {
      setCreating(false)
    }
  }

  const updateRole = async (u, role) => {
    if (u.role === role) return
    if (!confirm(`將 ${u.username} 改為「${ROLE_LABEL[role]}」？`)) return
    try {
      await usersAPI.update(u.id, { role })
      await load()
    } catch (err) {
      alert('變更失敗：' + (err?.response?.data?.detail || err.message))
    }
  }

  const toggleActive = async (u) => {
    try {
      await usersAPI.update(u.id, { is_active: !u.is_active })
      await load()
    } catch (err) {
      alert('變更失敗：' + (err?.response?.data?.detail || err.message))
    }
  }

  const resetPassword = async (u) => {
    if (!confirm(`重設 ${u.username} 的密碼？將產生一組臨時密碼，請轉交給對方。`)) return
    try {
      const { data } = await usersAPI.resetPassword(u.id)
      setResetResult(data)
    } catch (err) {
      alert('重設失敗：' + (err?.response?.data?.detail || err.message))
    }
  }

  const remove = async (u) => {
    if (!confirm(`真的刪除 ${u.username}？此動作無法復原。`)) return
    try {
      await usersAPI.delete(u.id)
      await load()
    } catch (err) {
      alert('刪除失敗：' + (err?.response?.data?.detail || err.message))
    }
  }

  return (
    <div className="space-y-6">
      <div className="card">
        <h2 className="text-lg font-semibold text-slate-100 mb-3">建立新使用者</h2>
        <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <input className="input" placeholder="帳號" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} />
          <input className="input" type="password" placeholder="密碼（≥ 8 字元）" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          <select className="input" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            <option value="regular">一般</option>
            <option value="admin">管理者</option>
            <option value="owner">擁有者</option>
          </select>
          <button type="submit" disabled={creating} className="btn-primary">
            {creating ? '建立中…' : '建立'}
          </button>
        </form>
        <p className="text-xs text-slate-500 mt-2">新帳號預設 must_change_password=true，使用者首次登入後應立即修改密碼。</p>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-100 mb-3">使用者列表（{users.length}）</h2>
        {loading ? (
          <p className="text-slate-400 text-sm">載入中…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-400 text-left">
                <tr className="border-b border-slate-700">
                  <th className="py-2 pr-3">ID</th>
                  <th className="py-2 pr-3">帳號</th>
                  <th className="py-2 pr-3">角色</th>
                  <th className="py-2 pr-3">啟用</th>
                  <th className="py-2 pr-3">最後登入</th>
                  <th className="py-2 pr-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.id} className="border-b border-slate-800">
                    <td className="py-2 pr-3 text-slate-400">{u.id}</td>
                    <td className="py-2 pr-3 text-slate-200">
                      {u.username}
                      {u.must_change_password && <span className="ml-1 text-xs text-amber-400">(待改密碼)</span>}
                    </td>
                    <td className="py-2 pr-3">
                      <select
                        value={u.role}
                        onChange={(e) => updateRole(u, e.target.value)}
                        className={`text-xs rounded border px-2 py-1 ${ROLE_COLOR[u.role] || ''}`}
                      >
                        <option value="regular">一般</option>
                        <option value="admin">管理者</option>
                        <option value="owner">擁有者</option>
                      </select>
                    </td>
                    <td className="py-2 pr-3">
                      <button
                        onClick={() => toggleActive(u)}
                        className={`text-xs rounded px-2 py-1 ${u.is_active ? 'bg-emerald-900/40 text-emerald-200' : 'bg-slate-800 text-slate-400'}`}
                      >
                        {u.is_active ? '✔ 啟用' : '✖ 停用'}
                      </button>
                    </td>
                    <td className="py-2 pr-3 text-slate-400 text-xs">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString('zh-TW') : '—'}
                    </td>
                    <td className="py-2 pr-3 space-x-2">
                      <button onClick={() => resetPassword(u)} className="text-xs text-indigo-400 hover:text-indigo-300">重設密碼</button>
                      <button onClick={() => remove(u)} className="text-xs text-red-400 hover:text-red-300">刪除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {resetResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-[min(92vw,520px)] rounded-lg border border-amber-700 bg-slate-900 p-5">
            <h3 className="text-amber-200 font-semibold mb-2">已重設 {resetResult.username} 的密碼</h3>
            <p className="text-sm text-slate-300 mb-3">{resetResult.note}</p>
            <div className="rounded bg-slate-800 px-3 py-2 font-mono text-amber-300 select-all break-all">
              {resetResult.temporary_password}
            </div>
            <div className="text-right mt-4">
              <button onClick={() => setResetResult(null)} className="btn-primary">我已記下，關閉</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
