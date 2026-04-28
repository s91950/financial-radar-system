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
import DashboardPage from './pages/DashboardPage'
import ReportsPage from './pages/ReportsPage'
import YouTubePage from './pages/YouTubePage'
import AnalysisPage from './pages/AnalysisPage'
import FeedbackPage from './pages/FeedbackPage'
import useWebSocket from './hooks/useWebSocket'
import { radarAPI } from './services/api'

const pageConfig = {
  '/': { title: '即時偵測雷達', subtitle: '每5分鐘自動掃描多來源資訊' },
  '/dashboard': { title: '市場儀表板', subtitle: '指標總覽 · 市場熱度 · 情緒指標' },
  '/search': { title: '主題追蹤', subtitle: '建立主題關鍵字，雷達自動匯入相關資訊' },
  '/news': { title: '新聞資料庫', subtitle: '自動蒐集與管理新聞、報告與聲明' },
  '/reports': { title: '研究報告', subtitle: 'IMF · BIS · Fed · ECB · BOJ · BOE 研究報告蒐集' },
  '/youtube': { title: 'YouTube 頻道監控', subtitle: '定期偵測頻道新影片，即時通知' },
  '/analysis': { title: '分析結果', subtitle: 'NotebookLM AI 深度分析報告' },
  '/feedback': { title: '意見回饋', subtitle: '提交改善建議與問題回報' },
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
      <div className="min-h-screen">
        <Sidebar />
        <main className="ml-64">
          <Routes>
            <Route path="/" element={
              <PageWrapper path="/" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <RadarPage wsSubscribe={subscribe} />
              </PageWrapper>
            } />
            <Route path="/dashboard" element={
              <PageWrapper path="/dashboard" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <DashboardPage wsSubscribe={subscribe} />
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
            <Route path="/reports" element={
              <PageWrapper path="/reports" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <ReportsPage />
              </PageWrapper>
            } />
            <Route path="/youtube" element={
              <PageWrapper path="/youtube" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <YouTubePage wsSubscribe={subscribe} />
              </PageWrapper>
            } />
            <Route path="/analysis" element={
              <PageWrapper path="/analysis" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <AnalysisPage />
              </PageWrapper>
            } />
            <Route path="/feedback" element={
              <PageWrapper path="/feedback" wsConnected={isConnected} alertStats={alertStats}
                onToggleNotifications={() => setNotificationsOpen(true)}>
                <FeedbackPage />
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
