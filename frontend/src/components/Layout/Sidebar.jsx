import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { getCurrentUser, clearAuth } from '../../services/api'

// 與 backend/auth.py ROLE_ORDER 同步：guest=0（只能存取雷達/新聞/分析/YT 唯讀）
const ROLE_ORDER = { guest: 0, regular: 1, admin: 2, owner: 3 }
const hasRole = (current, min) => (ROLE_ORDER[current] ?? 0) >= (ROLE_ORDER[min] ?? 0)

const navItems = [
  {
    path: '/',
    label: '即時雷達',
    shortLabel: '雷達',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9.348 14.651a3.75 3.75 0 010-5.303m5.304 0a3.75 3.75 0 010 5.303m-7.425 2.122a6.75 6.75 0 010-9.546m9.546 0a6.75 6.75 0 010 9.546M5.106 18.894c-3.808-3.808-3.808-9.98 0-13.789m13.788 0c3.808 3.808 3.808 9.981 0 13.79M12 12h.008v.007H12V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
      </svg>
    ),
  },
  {
    path: '/search',
    label: '主題追蹤',
    shortLabel: '追蹤',
    requiresRole: 'regular',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
    ),
  },
  {
    path: '/news',
    label: '新聞資料庫',
    shortLabel: '新聞',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 01-2.25 2.25M16.5 7.5V18a2.25 2.25 0 002.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 002.25 2.25h13.5" />
      </svg>
    ),
  },
  {
    path: '/youtube',
    label: 'YouTube 監控',
    shortLabel: 'YT',
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
      </svg>
    ),
  },
  {
    path: '/analysis',
    label: '分析結果',
    shortLabel: '分析',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    path: '/reports',
    label: '研究報告',
    shortLabel: '報告',
    requiresRole: 'regular',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
    ),
  },
  {
    path: '/dashboard',
    label: '市場儀表板',
    shortLabel: '儀表',
    requiresRole: 'regular',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
  },
  {
    path: '/feedback',
    label: '意見回饋',
    shortLabel: '回饋',
    requiresRole: 'regular',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
      </svg>
    ),
  },
  {
    path: '/raw-articles',
    label: '篩選前資料',
    shortLabel: '原始',
    requiresRole: 'regular',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.5v5m4-5v5M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
      </svg>
    ),
  },
  {
    path: '/settings',
    label: '系統設定',
    shortLabel: '設定',
    requiresRole: 'admin',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
  {
    path: '/users',
    label: '使用者管理',
    shortLabel: '使用者',
    requiresRole: 'owner',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
    ),
  },
  {
    path: '/service-keys',
    label: 'Service Keys',
    shortLabel: 'Keys',
    requiresRole: 'owner',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
      </svg>
    ),
  },
]

// Bottom tab bar: indices into navItems
const primaryTabIndices = [0, 2, 4, 3] // 雷達, 新聞, 分析, YT
const secondaryIndices = [1, 5, 6, 7, 8, 9, 10, 11] // 追蹤, 報告, 儀表, 回饋, 篩選前資料, 設定, 使用者, Keys

export default function Sidebar() {
  const [moreOpen, setMoreOpen] = useState(false)
  const location = useLocation()
  const user = getCurrentUser()
  const role = user?.role || 'guest'

  const visible = (item) => !item.requiresRole || hasRole(role, item.requiresRole)

  const isSecondaryActive = secondaryIndices.some(i => {
    const item = navItems[i]
    if (!visible(item)) return false
    const p = item.path
    return p === '/' ? location.pathname === '/' : location.pathname.startsWith(p)
  })

  const handleLogout = () => {
    if (!confirm('確定登出？')) return
    clearAuth()
    window.location.reload()
  }
  const handleLogin = () => {
    window.dispatchEvent(new CustomEvent('show-login'))
  }

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:flex fixed left-0 top-0 h-screen w-64 bg-dark-900 border-r border-dark-700 flex-col z-40">
        {/* Logo */}
        <div className="p-5 border-b border-dark-700">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary-600 rounded-xl flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">金融偵測系統</h1>
              <p className="text-xs text-dark-400">Financial Radar</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {navItems.filter(visible).map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200 ${
                  isActive
                    ? 'bg-primary-600/20 text-primary-400 border border-primary-500/30'
                    : 'text-dark-300 hover:text-white hover:bg-dark-800'
                }`
              }
            >
              {item.icon}
              <span className="font-medium">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-dark-700 space-y-2">
          {user ? (
            <div className="flex items-center justify-between gap-2 text-xs">
              <div className="min-w-0">
                <div className="text-slate-200 truncate">{user.username}</div>
                <div className="text-slate-500">
                  {role === 'owner' ? '擁有者' : role === 'admin' ? '管理者' : '一般'}
                </div>
              </div>
              <button onClick={handleLogout} className="text-red-400 hover:text-red-300 px-2 py-1 rounded">
                登出
              </button>
            </div>
          ) : (
            <button
              onClick={handleLogin}
              className="w-full text-sm bg-indigo-600 hover:bg-indigo-500 text-white py-2 rounded"
            >
              登入
            </button>
          )}
          <div className="flex items-center gap-2 text-xs text-dark-500">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span>System Active</span>
          </div>
        </div>
      </aside>

      {/* Mobile bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 md:hidden bg-dark-900 border-t border-dark-700">
        <div className="flex justify-around items-center">
          {primaryTabIndices
            .map(idx => navItems[idx])
            .filter(visible)
            .map(item => {
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                className={({ isActive }) =>
                  `flex flex-col items-center justify-center min-h-[56px] flex-1 transition-colors ${
                    isActive ? 'text-primary-400' : 'text-dark-400'
                  }`
                }
              >
                {item.icon}
                <span className="text-[10px] mt-0.5">{item.shortLabel}</span>
              </NavLink>
            )
          })}
          {/* More button */}
          <button
            onClick={() => setMoreOpen(true)}
            className={`flex flex-col items-center justify-center min-h-[56px] flex-1 transition-colors ${
              isSecondaryActive ? 'text-primary-400' : 'text-dark-400'
            }`}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
            <span className="text-[10px] mt-0.5">更多</span>
          </button>
        </div>
      </nav>

      {/* Mobile "More" overlay */}
      {moreOpen && (
        <div className="fixed inset-0 z-50 md:hidden" onClick={() => setMoreOpen(false)}>
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/60" />
          {/* Bottom sheet */}
          <div
            className="absolute bottom-0 left-0 right-0 bg-dark-800 rounded-t-2xl border-t border-dark-700 animate-slide-up"
            onClick={e => e.stopPropagation()}
          >
            {/* Handle bar */}
            <div className="flex justify-center py-2">
              <div className="w-10 h-1 bg-dark-600 rounded-full" />
            </div>
            <nav className="px-4 pb-3 space-y-1">
              {secondaryIndices
                .map(idx => navItems[idx])
                .filter(visible)
                .map(item => {
                const isActive = item.path === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(item.path)
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    onClick={() => setMoreOpen(false)}
                    className={`flex items-center gap-3 px-4 py-3.5 rounded-lg transition-colors ${
                      isActive
                        ? 'bg-primary-600/20 text-primary-400'
                        : 'text-dark-300 active:bg-dark-700'
                    }`}
                  >
                    {item.icon}
                    <span className="font-medium">{item.label}</span>
                  </NavLink>
                )
              })}
            </nav>
            {/* Account row (login / logout) */}
            <div className="px-4 pb-6 pt-2 border-t border-dark-700">
              {user ? (
                <div className="flex items-center justify-between gap-3 pt-3">
                  <div className="min-w-0">
                    <div className="text-sm text-slate-200 truncate">{user.username}</div>
                    <div className="text-xs text-slate-500">
                      {role === 'owner' ? '擁有者' : role === 'admin' ? '管理者' : '一般'}
                    </div>
                  </div>
                  <button
                    onClick={() => { setMoreOpen(false); handleLogout(); }}
                    className="text-sm text-red-400 active:text-red-300 px-3 py-2 rounded border border-red-900/50"
                  >
                    登出
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => { setMoreOpen(false); handleLogin(); }}
                  className="mt-3 w-full text-sm bg-indigo-600 active:bg-indigo-500 text-white py-3 rounded"
                >
                  登入
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
