import { useState } from 'react'
import { authAPI, setJwt, setCurrentUser } from '../services/api'

export default function LoginPage({ onLoggedIn, onContinueAsGuest }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e?.preventDefault?.()
    if (!username.trim() || !password) return
    setLoading(true)
    setError('')
    try {
      const { data } = await authAPI.login(username.trim(), password)
      setJwt(data.access_token)
      setCurrentUser(data.user)
      if (data.user?.must_change_password) {
        // 強制改密碼放到登入後 UI 處理（這裡先讓他進去）
      }
      onLoggedIn?.(data.user)
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || '登入失敗'
      setError(typeof msg === 'string' ? msg : '登入失敗')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-2xl">
        <h1 className="text-xl font-semibold text-slate-100 mb-1">金融即時偵測系統</h1>
        <p className="text-sm text-slate-400 mb-5">請輸入帳號密碼登入</p>

        <label className="block text-xs font-medium text-slate-300 mb-1">帳號</label>
        <input
          autoFocus
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          className="mb-3 w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
        />

        <label className="block text-xs font-medium text-slate-300 mb-1">密碼</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          className="mb-4 w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
        />

        {error && (
          <div className="mb-3 rounded bg-red-900/40 border border-red-700 px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !username.trim() || !password}
          className="w-full rounded bg-indigo-600 py-2 text-sm font-medium text-white disabled:opacity-50 hover:bg-indigo-500"
        >
          {loading ? '登入中…' : '登入'}
        </button>

        {onContinueAsGuest && (
          <button
            type="button"
            onClick={onContinueAsGuest}
            className="mt-3 w-full rounded border border-slate-700 bg-slate-800 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
          >
            以訪客進入（唯讀）
          </button>
        )}

        <p className="mt-3 text-xs text-slate-500 text-center">
          訪客可瀏覽雷達警報、市場儀表板、分析結果（唯讀）
        </p>
      </form>
    </div>
  )
}
