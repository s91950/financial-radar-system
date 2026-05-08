import { useEffect, useState } from 'react'
import { getApiToken, setApiToken } from '../../services/api'

/**
 * TokenGate：只在後端要求 API token 時介入。
 *
 * 流程：
 *  1. 子元件正常渲染（沒 token 也照常 mount）
 *  2. 第一個 API call 若回 401 → axios interceptor 觸發 'api-token-required' 事件
 *  3. 本元件捕捉事件 → 顯示輸入框
 *  4. 使用者貼入 token → 存 localStorage → reload 頁面（讓所有 API call 重發）
 *
 * 後端沒啟用 API_TOKEN 時，永遠不會收到 401，這個 modal 不會跳出，UX 完全等同舊版。
 */
export default function TokenGate({ children }) {
  const [need, setNeed] = useState(false)
  const [input, setInput] = useState('')

  useEffect(() => {
    const handler = () => setNeed(true)
    window.addEventListener('api-token-required', handler)
    return () => window.removeEventListener('api-token-required', handler)
  }, [])

  const submit = (e) => {
    e?.preventDefault?.()
    const v = input.trim()
    if (!v) return
    setApiToken(v)
    // reload 讓所有 axios call 重新跑（簡單可靠）
    window.location.reload()
  }

  return (
    <>
      {children}
      {need && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <form onSubmit={submit} className="w-[min(92vw,440px)] rounded-lg border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <h2 className="text-lg font-semibold text-slate-100 mb-1">需要 API Token</h2>
            <p className="text-sm text-slate-400 mb-4">
              此系統已啟用 API token 驗證。請貼入管理員提供的 token 以繼續使用。
            </p>
            <input
              autoFocus
              type="password"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="貼上 API Token"
              className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => { setApiToken(''); setNeed(false) }}
                className="rounded px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={!input.trim()}
                className="rounded bg-indigo-600 px-3 py-1.5 text-sm text-white disabled:opacity-50 hover:bg-indigo-500"
              >
                儲存並重新載入
              </button>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              Token 儲存在瀏覽器 localStorage（不會送到第三方）。可在瀏覽器 DevTools 清除。
            </p>
          </form>
        </div>
      )}
    </>
  )
}
