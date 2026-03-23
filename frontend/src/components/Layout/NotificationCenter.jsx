import { useEffect, useState } from 'react'
import { radarAPI } from '../../services/api'

export default function NotificationCenter({ isOpen, onClose, onAlertClick }) {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isOpen) {
      loadAlerts()
    }
  }, [isOpen])

  const loadAlerts = async () => {
    setLoading(true)
    try {
      const { data } = await radarAPI.getAlerts({ limit: 20, unread_only: true })
      setAlerts(data)
    } catch (err) {
      console.error('Failed to load alerts:', err)
    }
    setLoading(false)
  }

  const handleMarkAllRead = async () => {
    try {
      await radarAPI.markAllRead()
      setAlerts([])
    } catch (err) {
      console.error('Failed to mark all read:', err)
    }
  }

  if (!isOpen) return null

  const severityColors = {
    critical: 'border-l-red-500 bg-red-500/5',
    high: 'border-l-orange-500 bg-orange-500/5',
    medium: 'border-l-yellow-500 bg-yellow-500/5',
    low: 'border-l-green-500 bg-green-500/5',
  }

  return (
    <div className="fixed inset-0 z-50" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="absolute right-0 top-0 h-full w-96 bg-dark-900 border-l border-dark-700 shadow-2xl animate-slide-in"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-dark-700">
          <h3 className="text-lg font-bold">通知中心</h3>
          <div className="flex items-center gap-2">
            {alerts.length > 0 && (
              <button onClick={handleMarkAllRead} className="text-xs text-primary-400 hover:underline">
                全部已讀
              </button>
            )}
            <button onClick={onClose} className="p-1 hover:bg-dark-800 rounded">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="overflow-y-auto h-[calc(100%-60px)] p-3 space-y-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500" />
            </div>
          ) : alerts.length === 0 ? (
            <div className="text-center py-12 text-dark-400">
              <svg className="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9.143 17.082a24.248 24.248 0 005.714 0m-5.714 0a3 3 0 015.714 0m-5.714 0H3.82a1.5 1.5 0 01-1.342-2.174l1.17-2.341A4.5 4.5 0 004.5 10.5V9a7.5 7.5 0 1115 0v1.5c0 .82.224 1.623.648 2.317l1.17 2.341a1.5 1.5 0 01-1.342 2.174H15.857" />
              </svg>
              <p>目前沒有未讀通知</p>
            </div>
          ) : (
            alerts.map(alert => (
              <div
                key={alert.id}
                onClick={() => onAlertClick?.(alert)}
                className={`p-3 rounded-lg border-l-4 cursor-pointer hover:bg-dark-800/50 transition-colors ${
                  severityColors[alert.severity] || 'border-l-gray-500'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-medium text-sm text-gray-200 line-clamp-2">{alert.title}</h4>
                  <span className={`badge-${alert.severity} shrink-0`}>{alert.severity}</span>
                </div>
                <p className="text-xs text-dark-400 mt-1 line-clamp-2">{alert.content}</p>
                <p className="text-xs text-dark-500 mt-2">
                  {alert.created_at && new Date(alert.created_at).toLocaleString('zh-TW')}
                </p>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
