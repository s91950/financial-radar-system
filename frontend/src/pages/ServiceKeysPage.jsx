import { useEffect, useState } from 'react'
import { serviceKeysAPI } from '../services/api'

export default function ServiceKeysPage() {
  const [keys, setKeys] = useState([])
  const [loading, setLoading] = useState(true)
  const [name, setName] = useState('')
  const [role, setRole] = useState('admin')
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState(null)  // { full_key, ... }

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await serviceKeysAPI.list()
      setKeys(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const create = async (e) => {
    e.preventDefault()
    if (!name.trim()) { alert('請給 key 一個用途名稱'); return }
    setCreating(true)
    try {
      const { data } = await serviceKeysAPI.create(name.trim(), role)
      setCreated(data)
      setName(''); setRole('admin')
      await load()
    } catch (err) {
      alert('建立失敗：' + (err?.response?.data?.detail || err.message))
    } finally {
      setCreating(false)
    }
  }

  const revoke = async (k) => {
    if (!confirm(`撤銷「${k.name}」？此 key 將立即失效，使用該 key 的 Extension / scripts 會收到 401。`)) return
    try {
      await serviceKeysAPI.revoke(k.id)
      await load()
    } catch (err) {
      alert('撤銷失敗：' + (err?.response?.data?.detail || err.message))
    }
  }

  return (
    <div className="space-y-6">
      <div className="card">
        <h2 className="text-lg font-semibold text-slate-100 mb-1">什麼是 Service API Keys？</h2>
        <p className="text-sm text-slate-400 mb-3">
          給非瀏覽器 client（Chrome Extension、本機 hourly script、CI 等）用的長效認證 key。
          每把 key 可獨立撤銷，外洩時只動該 client，不影響其他人。
          建立後 key 完整內容**只在當下顯示一次**，務必立即複製存好。
        </p>

        <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            className="input"
            placeholder="用途名稱（例如：Chrome Extension）"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="admin">admin（可寫報告 / 一般操作）</option>
            <option value="regular">regular（只能讀 + 一般寫入）</option>
          </select>
          <button type="submit" disabled={creating} className="btn-primary">
            {creating ? '建立中…' : '建立新 Key'}
          </button>
        </form>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-100 mb-3">現有 Keys（{keys.length}）</h2>
        {loading ? (
          <p className="text-slate-400 text-sm">載入中…</p>
        ) : keys.length === 0 ? (
          <p className="text-slate-500 text-sm">尚無 service key</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-400 text-left">
                <tr className="border-b border-slate-700">
                  <th className="py-2 pr-3">名稱</th>
                  <th className="py-2 pr-3">前綴</th>
                  <th className="py-2 pr-3">角色</th>
                  <th className="py-2 pr-3">建立</th>
                  <th className="py-2 pr-3">最後使用</th>
                  <th className="py-2 pr-3">狀態</th>
                  <th className="py-2 pr-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {keys.map(k => (
                  <tr key={k.id} className={`border-b border-slate-800 ${k.is_revoked ? 'opacity-50' : ''}`}>
                    <td className="py-2 pr-3 text-slate-200">{k.name}</td>
                    <td className="py-2 pr-3 font-mono text-xs text-slate-400">{k.key_prefix}…</td>
                    <td className="py-2 pr-3 text-slate-300">{k.role}</td>
                    <td className="py-2 pr-3 text-slate-400 text-xs">
                      {k.created_at ? new Date(k.created_at).toLocaleDateString('zh-TW') : '—'}
                    </td>
                    <td className="py-2 pr-3 text-slate-400 text-xs">
                      {k.last_used_at ? new Date(k.last_used_at).toLocaleString('zh-TW') : '從未'}
                    </td>
                    <td className="py-2 pr-3">
                      {k.is_revoked
                        ? <span className="text-xs text-red-400">已撤銷</span>
                        : <span className="text-xs text-emerald-400">啟用中</span>}
                    </td>
                    <td className="py-2 pr-3">
                      {!k.is_revoked && (
                        <button onClick={() => revoke(k)} className="text-xs text-red-400 hover:text-red-300">撤銷</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {created && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-[min(92vw,560px)] rounded-lg border border-amber-700 bg-slate-900 p-5">
            <h3 className="text-amber-200 font-semibold mb-2">⚠️ 此 key 只顯示一次，請立即複製</h3>
            <p className="text-sm text-slate-300 mb-3">
              名稱：<span className="text-slate-100">{created.name}</span>　角色：<span className="text-slate-100">{created.role}</span>
            </p>
            <div className="rounded bg-slate-800 px-3 py-3 font-mono text-amber-300 select-all break-all text-sm">
              {created.full_key}
            </div>
            <p className="text-xs text-slate-500 mt-3">
              請貼到 Extension options 的「VM API Token」欄位，或本機 scripts/.env.local 的 API_TOKEN。
              關閉此視窗後將無法再取得完整內容。
            </p>
            <div className="text-right mt-4 space-x-2">
              <button
                onClick={() => navigator.clipboard?.writeText(created.full_key)}
                className="btn-secondary"
              >
                複製
              </button>
              <button onClick={() => setCreated(null)} className="btn-primary">我已記下，關閉</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
