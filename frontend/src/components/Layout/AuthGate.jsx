import { useEffect, useState } from 'react'
import { authAPI, getJwt, getCurrentUser, setCurrentUser, clearAuth } from '../../services/api'
import LoginPage from '../../pages/LoginPage'

/**
 * AuthGate：所有路由的最外層守門。
 *
 * 三種狀態：
 *   - 未登入訪客：可看雷達相關 GET，但訪問 /settings、/users、/service-keys 等寫入頁會收到 401，AuthGate 跳登入
 *   - 已登入：JWT 存 localStorage，axios 自動帶 Authorization header
 *   - JWT 過期 / 被撤銷：API 回 401 → axios interceptor 觸發 'auth-required' → 顯示登入畫面
 *
 * 使用者點 sidebar 上的「登入」按鈕也會觸發。
 */
export default function AuthGate({ children }) {
  const [user, setUser] = useState(getCurrentUser())
  const [showLogin, setShowLogin] = useState(false)
  const [bootChecked, setBootChecked] = useState(false)

  // 開頁時若 localStorage 有 jwt 就 verify 一下（過期 / 被撤銷時清掉）
  useEffect(() => {
    let cancelled = false
    const run = async () => {
      if (!getJwt()) {
        setBootChecked(true)
        return
      }
      try {
        const { data } = await authAPI.me()
        if (cancelled) return
        if (data?.authenticated) {
          setCurrentUser({
            id: data.id,
            username: data.username,
            role: data.role,
            must_change_password: data.must_change_password,
          })
          setUser(getCurrentUser())
        } else {
          clearAuth()
          setUser(null)
        }
      } catch {
        // 401 等已被 interceptor 清掉
      }
      if (!cancelled) setBootChecked(true)
    }
    run()
    return () => { cancelled = true }
  }, [])

  // 接收 axios 的 401 / 403 廣播
  useEffect(() => {
    const handler = () => {
      setUser(null)
      setShowLogin(true)
    }
    const loginHandler = () => setShowLogin(true)
    window.addEventListener('auth-required', handler)
    window.addEventListener('show-login', loginHandler)
    return () => {
      window.removeEventListener('auth-required', handler)
      window.removeEventListener('show-login', loginHandler)
    }
  }, [])

  if (!bootChecked) {
    return <div className="min-h-screen bg-slate-950" />
  }

  if (showLogin) {
    return (
      <LoginPage
        onLoggedIn={(u) => {
          setUser(u)
          setShowLogin(false)
          // reload 以重發那些被 401 擋住的 API call
          window.location.reload()
        }}
      />
    )
  }

  return children
}
