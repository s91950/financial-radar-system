import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { useCallback, useEffect, useState } from 'react'
import { Toaster, toast } from 'react-hot-toast'
import Sidebar from './components/Layout/Sidebar'
import Header from './components/Layout/Header'
import NotificationCenter from './components/Layout/NotificationCenter'
import RadarPage from './pages/RadarPage'
import SearchPage from './pages/SearchPage'
import NewsDBPage from './pages/NewsDBPage'
import SettingsPage from './pages/SettingsPage'
import useWebSocket from './hooks/useWebSocket'
import { radarAPI } from './services/api'

const pageConfig = {
  '/': { title: '即時偵測雷達', subtitle: '每5分鐘自動掃描多來源資訊' },
  '/search': { title: '主題搜尋', subtitle: '搜尋特定主題並取得 AI 分析報告' },
  '/news': { title: '新聞資料庫', subtitle: '自動蒐集與管理新聞、報告與聲明' },
  '/settings': { title: '系統設定', subtitle: '管理資料來源、通知與偏好設定' },
}

export default function App() {
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [alertStats, setAlertStats] = useState({ total: 0, unread: 0, critical: 0 })
  const { isConnected, subscribe } = useWebSocket()

  // Load alert stats
  const loadAlertStats = useCallback(async () => {
    try {
      const { data } = await radarAPI.getAlertStats()
      setAlertStats(data)
    } catch (err) {
      // Silently fail on stats load
    }
  }, [])

  useEffect(() => {
    loadAlertStats()
    const interval = setInterval(loadAlertStats, 30000)
    return () => clearInterval(interval)
  }, [loadAlertStats])

  // Handle WebSocket notifications
  useEffect(() => {
    const unsubRadar = subscribe('radar_alert', (msg) => {
      const { data } = msg
      toast(data.title, {
        icon: data.severity === 'critical' ? '🔴' : data.severity === 'high' ? '🟠' : '🟡',
        duration: 6000,
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
      loadAlertStats()
    })

    const unsubMarket = subscribe('market_alert', (msg) => {
      const { data } = msg
      toast(data.title, {
        icon: '📊',
        duration: 6000,
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
      loadAlertStats()
    })

    const unsubDaily = subscribe('daily_summary', (msg) => {
      toast(msg.data.message, {
        icon: '📰',
        duration: 5000,
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
    })

    return () => {
      unsubRadar()
      unsubMarket()
      unsubDaily()
    }
  }, [subscribe, loadAlertStats])

  return (
    <BrowserRouter>
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex-1 ml-64">
          <Routes>
            <Route path="/" element={
              <PageWrapper path="/" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <RadarPage wsSubscribe={subscribe} />
              </PageWrapper>
            } />
            <Route path="/search" element={
              <PageWrapper path="/search" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <SearchPage />
              </PageWrapper>
            } />
            <Route path="/news" element={
              <PageWrapper path="/news" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <NewsDBPage />
              </PageWrapper>
            } />
            <Route path="/settings" element={
              <PageWrapper path="/settings" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <SettingsPage />
              </PageWrapper>
            } />
          </Routes>
        </main>

        <NotificationCenter
          isOpen={notificationsOpen}
          onClose={() => setNotificationsOpen(false)}
        />

        <Toaster position="top-right" />
      </div>
    </BrowserRouter>
  )
}

function PageWrapper({ path, children, wsConnected, alertStats, onToggleNotifications }) {
  const config = pageConfig[path] || {}
  return (
    <>
      <Header
        title={config.title}
        subtitle={config.subtitle}
        wsConnected={wsConnected}
        alertStats={alertStats}
        onToggleNotifications={onToggleNotifications}
      />
      <div className="p-6">
        {children}
      </div>
    </>
  )
}
