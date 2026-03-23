import { useCallback, useEffect, useState } from 'react'
import { settingsAPI } from '../services/api'
import { toast } from 'react-hot-toast'

export default function SettingsPage() {
  const [sources, setSources] = useState([])
  const [notifications, setNotifications] = useState([])
  const [sheetsStatus, setSheetsStatus] = useState(null)
  const [sheetsTestResult, setSheetsTestResult] = useState(null)
  const [sheetsTesting, setSheetsTesting] = useState(false)
  const [loading, setLoading] = useState(true)
  const [newSource, setNewSource] = useState({ name: '', type: 'rss', url: '', keywords: '' })
  const [showAddSource, setShowAddSource] = useState(false)

  const loadSettings = useCallback(async () => {
    try {
      const [srcRes, notifRes, sheetsRes] = await Promise.all([
        settingsAPI.getSources(),
        settingsAPI.getNotificationSettings(),
        settingsAPI.getGoogleSheetsStatus(),
      ])
      setSources(srcRes.data)
      setNotifications(notifRes.data)
      setSheetsStatus(sheetsRes.data)
    } catch (err) {
      console.error('Failed to load settings:', err)
    }
    setLoading(false)
  }, [])

  useEffect(() => { loadSettings() }, [loadSettings])

  const handleAddSource = async (e) => {
    e.preventDefault()
    try {
      const keywords = newSource.keywords.split(',').map(k => k.trim()).filter(Boolean)
      await settingsAPI.createSource({ ...newSource, keywords })
      setNewSource({ name: '', type: 'rss', url: '', keywords: '' })
      setShowAddSource(false)
      loadSettings()
      toast.success('來源新增成功')
    } catch (err) {
      toast.error('新增失敗')
    }
  }

  const handleToggleSource = async (source) => {
    try {
      await settingsAPI.updateSource(source.id, { is_active: !source.is_active })
      setSources(prev => prev.map(s => s.id === source.id ? { ...s, is_active: !s.is_active } : s))
    } catch (err) {
      toast.error('更新失敗')
    }
  }

  const handleDeleteSource = async (id) => {
    if (!confirm('確定刪除此來源？')) return
    try {
      await settingsAPI.deleteSource(id)
      setSources(prev => prev.filter(s => s.id !== id))
      toast.success('已刪除')
    } catch (err) {
      toast.error('刪除失敗')
    }
  }

  const handleToggleNotification = async (channel) => {
    const current = notifications.find(n => n.channel === channel)
    if (!current) return
    try {
      await settingsAPI.updateNotification(channel, { is_enabled: !current.is_enabled })
      setNotifications(prev => prev.map(n =>
        n.channel === channel ? { ...n, is_enabled: !n.is_enabled } : n
      ))
    } catch (err) {
      toast.error('更新失敗')
    }
  }

  const handleTestNotification = async (channel) => {
    try {
      const { data } = await settingsAPI.testNotification(channel)
      if (data.success) {
        toast.success(`${channel} 測試通知已發送`)
      } else {
        toast.error(`${channel} 測試失敗`)
      }
    } catch (err) {
      toast.error('測試失敗')
    }
  }

  const typeLabels = { rss: 'RSS', website: '網頁', social: '社群', newsapi: 'NewsAPI' }
  const channelLabels = { web: '網頁通知', line: 'LINE Notify', email: 'Email' }
  const channelIcons = {
    web: '🌐',
    line: '💬',
    email: '📧',
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500" />
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Monitor Sources */}
      <section className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold">監控來源</h3>
            <p className="text-sm text-dark-400">管理雷達掃描的資料來源</p>
          </div>
          <button onClick={() => setShowAddSource(!showAddSource)} className="btn-primary text-sm">
            + 新增來源
          </button>
        </div>

        {/* Add Source Form */}
        {showAddSource && (
          <form onSubmit={handleAddSource} className="mb-4 p-4 bg-dark-900 rounded-lg space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm text-dark-400 mb-1">名稱</label>
                <input
                  value={newSource.name}
                  onChange={(e) => setNewSource(prev => ({ ...prev, name: e.target.value }))}
                  className="input"
                  placeholder="例：金管會公告"
                  required
                />
              </div>
              <div>
                <label className="block text-sm text-dark-400 mb-1">類型</label>
                <select
                  value={newSource.type}
                  onChange={(e) => setNewSource(prev => ({ ...prev, type: e.target.value }))}
                  className="input"
                >
                  <option value="rss">RSS Feed</option>
                  <option value="website">網頁爬蟲</option>
                  <option value="social">社群媒體</option>
                  <option value="newsapi">NewsAPI</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm text-dark-400 mb-1">URL</label>
              <input
                value={newSource.url}
                onChange={(e) => setNewSource(prev => ({ ...prev, url: e.target.value }))}
                className="input"
                placeholder="https://..."
                required
              />
            </div>
            <div>
              <label className="block text-sm text-dark-400 mb-1">關鍵字（逗號分隔）</label>
              <input
                value={newSource.keywords}
                onChange={(e) => setNewSource(prev => ({ ...prev, keywords: e.target.value }))}
                className="input"
                placeholder="例：利率, 升息, 降息"
              />
            </div>
            <div className="flex gap-2">
              <button type="submit" className="btn-primary text-sm">新增</button>
              <button type="button" onClick={() => setShowAddSource(false)} className="btn-secondary text-sm">取消</button>
            </div>
          </form>
        )}

        {/* Sources List */}
        <div className="space-y-2">
          {sources.map(source => (
            <div key={source.id} className="flex items-center justify-between p-3 rounded-lg bg-dark-900 hover:bg-dark-800/50">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => handleToggleSource(source)}
                  className={`w-10 h-6 rounded-full transition-colors relative ${
                    source.is_active ? 'bg-primary-600' : 'bg-dark-600'
                  }`}
                >
                  <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${
                    source.is_active ? 'translate-x-5' : 'translate-x-1'
                  }`} />
                </button>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{source.name}</span>
                    <span className="badge bg-dark-700 text-dark-300">{typeLabels[source.type]}</span>
                  </div>
                  <p className="text-xs text-dark-500 truncate max-w-md">{source.url}</p>
                  {source.keywords && source.keywords.length > 0 && (
                    <div className="flex gap-1 mt-1">
                      {source.keywords.map(kw => (
                        <span key={kw} className="text-xs px-1.5 py-0.5 rounded bg-dark-700 text-dark-300">{kw}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <button onClick={() => handleDeleteSource(source.id)}
                className="p-1.5 hover:bg-red-500/10 rounded text-dark-500 hover:text-red-400">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Notification Settings */}
      <section className="card">
        <div className="mb-4">
          <h3 className="text-lg font-bold">通知設定</h3>
          <p className="text-sm text-dark-400">設定即時警報的通知管道</p>
        </div>

        <div className="space-y-3">
          {notifications.map(notif => (
            <div key={notif.channel} className="flex items-center justify-between p-4 rounded-lg bg-dark-900">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{channelIcons[notif.channel]}</span>
                <div>
                  <span className="font-medium">{channelLabels[notif.channel]}</span>
                  <p className="text-xs text-dark-500">
                    {notif.channel === 'web' && '瀏覽器內 Toast 通知'}
                    {notif.channel === 'line' && 'LINE Notify 推送'}
                    {notif.channel === 'email' && 'SMTP 郵件通知'}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <button onClick={() => handleTestNotification(notif.channel)}
                  className="btn-secondary text-xs">
                  測試
                </button>
                <button
                  onClick={() => handleToggleNotification(notif.channel)}
                  className={`w-10 h-6 rounded-full transition-colors relative ${
                    notif.is_enabled ? 'bg-primary-600' : 'bg-dark-600'
                  }`}
                >
                  <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${
                    notif.is_enabled ? 'translate-x-5' : 'translate-x-1'
                  }`} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Google Sheets */}
      <section className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold">Google Sheets 連結</h3>
            <p className="text-sm text-dark-400">部位資料讀取 & 新聞留存</p>
          </div>
          <button
            onClick={async () => {
              setSheetsTesting(true)
              setSheetsTestResult(null)
              try {
                const { data } = await settingsAPI.testGoogleSheets()
                setSheetsTestResult(data)
              } catch (err) {
                setSheetsTestResult({ success: false, message: '連線失敗' })
              }
              setSheetsTesting(false)
            }}
            disabled={sheetsTesting}
            className="btn-secondary text-sm flex items-center gap-1.5"
          >
            {sheetsTesting && <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-current" />}
            測試連線
          </button>
        </div>

        {sheetsStatus && (
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">金鑰檔案</span>
              <p className="text-sm mt-1 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${sheetsStatus.credentials_exists ? 'bg-green-500' : 'bg-red-500'}`} />
                {sheetsStatus.credentials_file}
              </p>
            </div>
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">試算表 ID</span>
              <p className="text-sm mt-1 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${sheetsStatus.configured ? 'bg-green-500' : 'bg-yellow-500'}`} />
                {sheetsStatus.spreadsheet_id || '未設定'}
              </p>
            </div>
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">部位資料 Tab</span>
              <p className="text-sm mt-1">{sheetsStatus.position_sheet}</p>
            </div>
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">新聞留存 Tab</span>
              <p className="text-sm mt-1">{sheetsStatus.news_sheet}</p>
            </div>
          </div>
        )}

        {sheetsTestResult && (
          <div className={`p-3 rounded-lg ${sheetsTestResult.success ? 'bg-green-500/10 border border-green-500/20' : 'bg-red-500/10 border border-red-500/20'}`}>
            <p className={`text-sm ${sheetsTestResult.success ? 'text-green-400' : 'text-red-400'}`}>
              {sheetsTestResult.message}
            </p>
            {sheetsTestResult.position_count !== undefined && (
              <p className="text-xs text-dark-400 mt-1">部位數量：{sheetsTestResult.position_count}</p>
            )}
            {sheetsTestResult.tabs && (
              <p className="text-xs text-dark-400 mt-1">分頁：{sheetsTestResult.tabs.join(', ')}</p>
            )}
          </div>
        )}
      </section>

      {/* System Info */}
      <section className="card">
        <h3 className="text-lg font-bold mb-4">系統資訊</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">雷達掃描間隔</span>
            <p className="font-medium mt-1">每 5 分鐘</p>
          </div>
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">每日新聞蒐集</span>
            <p className="font-medium mt-1">每日 08:00</p>
          </div>
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">資料來源數量</span>
            <p className="font-medium mt-1">{sources.filter(s => s.is_active).length} / {sources.length} 啟用</p>
          </div>
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">AI 分析引擎</span>
            <p className="font-medium mt-1">Claude Sonnet 4</p>
          </div>
        </div>
      </section>
    </div>
  )
}
