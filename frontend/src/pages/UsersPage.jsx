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

// 角色權限對照表（與 backend 路由的 require_regular / require_admin / require_owner 一致）
// 2026-05-09 起 guest 暫時放寬為與 regular 相同
const PERMISSION_MATRIX = [
  { label: '看雷達警報、市場、儀表板', roles: ['guest', 'regular', 'admin', 'owner'] },
  { label: '看分析報告（NLM / Gemini / Extension）', roles: ['guest', 'regular', 'admin', 'owner'] },
  { label: '看新聞 / 研究 / YouTube / 篩選前資料', roles: ['guest', 'regular', 'admin', 'owner'] },
  { label: '看主題追蹤、留意見回饋', roles: ['guest', 'regular', 'admin', 'owner'] },
  { label: '修改自己的密碼', roles: ['regular', 'admin', 'owner'] },
  { label: '標記警報已讀 / 儲存 / 刪除', roles: ['admin', 'owner'] },
  { label: '觸發 AI 分析 / 雷達掃描', roles: ['admin', 'owner'] },
  { label: '市場條件 / 觀察清單 CRUD', roles: ['admin', 'owner'] },
  { label: '刪除新聞 / 研究 / 回饋 / YT 頻道', roles: ['admin', 'owner'] },
  { label: '系統設定（來源 / 通知 / AI / 篩選）', roles: ['admin', 'owner'] },
  { label: '主題追蹤 CRUD', roles: ['admin', 'owner'] },
  { label: '使用者管理', roles: ['owner'] },
  { label: 'Service Keys 管理', roles: ['owner'] },
]

const ROLE_COLUMNS = [
  { key: 'guest', label: '訪客', headerClass: 'text-slate-400' },
  { key: 'regular', label: '一般', headerClass: 'text-sky-300' },
  { key: 'admin', label: '管理者', headerClass: 'text-amber-300' },
  { key: 'owner', label: '擁有者', headerClass: 'text-rose-300' },
]

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
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <h2 className="text-lg font-semibold text-slate-100">角色權限對照表</h2>
          <span className="text-xs text-amber-300 bg-amber-900/30 border border-amber-700/50 rounded px-2 py-1">
            目前「訪客」暫時放寬為與「一般」相同權限
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead>
              <tr className="text-slate-400 text-left">
                <th className="py-2 pr-3 font-medium border-b border-slate-700">功能</th>
                {ROLE_COLUMNS.map(col => (
                  <th key={col.key} className={`py-2 px-3 text-center font-medium border-b border-slate-700 ${col.headerClass}`}>
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PERMISSION_MATRIX.map((row, i) => (
                <tr key={i} className="hover:bg-slate-800/40">
                  <td className="py-2 pr-3 text-slate-200 border-b border-slate-800">{row.label}</td>
                  {ROLE_COLUMNS.map(col => {
                    const allowed = row.roles.includes(col.key)
                    return (
                      <td key={col.key} className="py-2 px-3 text-center border-b border-slate-800">
                        {allowed
                          ? <span className="text-emerald-400 font-bold">✓</span>
                          : <span className="text-slate-600">–</span>
                        }
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-500 mt-3">
          僅供檢視。要修改權限分配需動 backend 路由的 <code className="text-slate-300">require_regular</code> / <code className="text-slate-300">require_admin</code> / <code className="text-slate-300">require_owner</code> 設定。
        </p>
      </div>

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
