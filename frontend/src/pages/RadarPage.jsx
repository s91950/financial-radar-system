import { useCallback, useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import { radarAPI, resolveUrl, copyToClipboard, hasRole } from '../services/api'

export default function RadarPage({ wsSubscribe }) {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState(null)
  const isAdmin = hasRole('admin')

  // Filter & sort state
  const [filterSeverity, setFilterSeverity] = useState('all')
  const [filterUnread, setFilterUnread] = useState(false)
  const [filterSaved, setFilterSaved] = useState(false)
  const [sortOrder, setSortOrder] = useState('desc')
  const [filterKeyword, setFilterKeyword] = useState('')
  // Source URL selection (global across all alerts)
  const [selectedSourceUrls, setSelectedSourceUrls] = useState(new Set())

  const loadAlerts = useCallback(async () => {
    try {
      const params = { hours_back: 24 }
      if (filterUnread) params.unread_only = true
      const { data } = await radarAPI.getAlerts(params)
      setAlerts(data)
    } catch (err) {
      console.error('Failed to load alerts:', err)
    }
    setLoading(false)
  }, [filterUnread])

  useEffect(() => {
    loadAlerts()
    const interval = setInterval(loadAlerts, 30000)
    return () => clearInterval(interval)
  }, [loadAlerts])

  useEffect(() => {
    if (!wsSubscribe) return
    const unsub = wsSubscribe('radar_alert', () => { loadAlerts() })
    const unsub2 = wsSubscribe('market_alert', () => { loadAlerts() })
    return () => { unsub(); unsub2() }
  }, [wsSubscribe, loadAlerts])

  const parseSourceUrl = (rawUrl) => {
    if (!rawUrl) return { severity: null, url: '', raw: '' }
    const match = rawUrl.match(/^\{(critical|high|medium|low)\}(.*)/)
    if (match) {
      return { severity: match[1], url: match[2].trim(), raw: rawUrl }
    }
    return { severity: null, url: rawUrl, raw: rawUrl }
  }

  const extractMatchedKw = (kw) => {
    if (!kw) return null
    // 新格式（後端已萃取）：不含布林語法，按分隔符切分取前 4 個 term
    const isRawTopic = kw.includes(' OR ') || kw.startsWith('(') || kw.includes('"')
    if (!isRawTopic) {
      const parts = kw.split(/\s*[\/、,，;；]\s*/).map(s => s.trim()).filter(Boolean)
      const picked = [...new Set(parts)].slice(0, 4)
      const joined = picked.join(' / ')
      return joined.length <= 40 ? joined : joined.slice(0, 38) + '…'
    }
    // 舊格式（原始 topic 字串）：萃取前 4 個詞顯示
    const quoted = [...kw.matchAll(/"([^"]+)"/g)].map(m => m[1])
    const bare = kw.replace(/"[^"]*"/g, '').split(/[\s()]+/)
      .filter(t => t && !['OR', 'AND', 'NOT'].includes(t) && t.length > 1)
    const terms = [...new Set([...quoted, ...bare])]
    return terms.slice(0, 4).join(' / ') || null
  }

  const splitArticleLines = (content) => {
    if (!content) return []
    return content.split('\n').map(s => s.trim()).filter(Boolean).map(line => {
      const sevMatch = line.match(/^\{(critical|high|medium|low)\}(.*)/)
      const cleanLine = sevMatch ? sevMatch[2].trim() : line
      const kwMatch = cleanLine.match(/\(關鍵字：(.+?)\)$/)
      const displayLine = kwMatch ? cleanLine.slice(0, cleanLine.lastIndexOf(' (關鍵字：')) : cleanLine
      const rawKw = kwMatch?.[1] || null
      return {
        raw: line,
        severity: sevMatch ? sevMatch[1] : null,
        displayLine,
        kw: extractMatchedKw(rawKw),
      }
    })
  }

  // 卡片內新聞固定「風險優先」排序：critical > high > medium > low > 無等級
  // 傳入的物件需已帶原始 num（顯示編號維持原序，只重排顯示順序，URL 對應隨物件一起走不會錯位）
  const SEVERITY_RANK = { critical: 3, high: 2, medium: 1, low: 0 }
  const orderByMode = (items) =>
    [...items].sort(
      (a, b) => (SEVERITY_RANK[b.severity] ?? -1) - (SEVERITY_RANK[a.severity] ?? -1)
    )

  // Client-side filter & sort
  let displayAlerts = alerts
  if (filterSaved) {
    displayAlerts = displayAlerts.filter(a => a.is_saved)
  }
  if (filterKeyword) {
    const kw = filterKeyword.toLowerCase()
    displayAlerts = displayAlerts.filter(a =>
      a.title?.toLowerCase().includes(kw) || a.content?.toLowerCase().includes(kw)
    )
  }
  // Severity filter: keep alert only if it has at least one matching article line
  if (filterSeverity !== 'all') {
    displayAlerts = displayAlerts.filter(a => {
      if (a.type !== 'news') return a.severity === filterSeverity
      const lines = splitArticleLines(a.content)
      return lines.some(l => l.severity === filterSeverity)
    })
  }
  if (sortOrder === 'asc') {
    displayAlerts = [...displayAlerts].sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
  }

  const handleManualScan = async () => {
    setScanning(true)
    setScanResult(null)
    try {
      const beforeCount = alerts.length
      await radarAPI.triggerScan()
      let elapsed = 0
      const poll = setInterval(async () => {
        elapsed += 3
        try {
          const params = { hours_back: 24 }
          if (filterUnread) params.unread_only = true
          const { data } = await radarAPI.getAlerts(params)
          if (data.length > beforeCount) {
            const diff = data.length - beforeCount
            setAlerts(data)
            setScanResult(`發現 ${diff} 則新信號`)
            clearInterval(poll)
            setScanning(false)
            setTimeout(() => setScanResult(null), 4000)
            return
          }
        } catch (_) {}
        if (elapsed >= 30) {
          await loadAlerts()
          setScanResult('掃描完成，無新信號')
          clearInterval(poll)
          setScanning(false)
          setTimeout(() => setScanResult(null), 4000)
        }
      }, 3000)
    } catch (err) {
      console.error('Scan failed:', err)
      setScanResult('掃描失敗，請重試')
      setScanning(false)
      setTimeout(() => setScanResult(null), 3000)
    }
  }

  const handleMarkRead = async (alert) => {
    if (!isAdmin) return  // 訪客/regular 不能改已讀狀態，靜默跳過避免 401
    try {
      await radarAPI.markRead(alert.id)
      setAlerts(prev => prev.map(a => a.id === alert.id ? { ...a, is_read: true } : a))
    } catch (err) {
      console.error(err)
    }
  }

  const handleToggleSave = async (e, alertId) => {
    e?.stopPropagation()
    try {
      const { data } = await radarAPI.toggleSaveAlert(alertId)
      setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, is_saved: data.is_saved } : a))
    } catch (err) {
      console.error('Failed to toggle save:', err)
    }
  }

  const handleDeleteAlert = async (e, alertId) => {
    e.stopPropagation()
    try {
      await radarAPI.deleteAlert(alertId)
      setAlerts(prev => prev.filter(a => a.id !== alertId))
    } catch (err) {
      console.error('Failed to delete alert:', err)
    }
  }

  const handleSelectAllFilteredUrls = () => {
    const next = new Set()
    displayAlerts.forEach(a => {
      if (a.source_urls) {
        a.source_urls.forEach(rawU => {
          const parsed = parseSourceUrl(rawU)
          if (filterSeverity === 'all' || parsed.severity === filterSeverity) {
            next.add(rawU)
          }
        })
      } else if (a.source_url) {
        next.add(a.source_url)
      }
    })
    setSelectedSourceUrls(next)
  }

  const handleCopySelectedUrls = async (e) => {
    e && e.stopPropagation()
    const toastId = toast.loading('解析連結中...')
    const resolved = await Promise.all([...selectedSourceUrls].map(u => resolveUrl(parseSourceUrl(u).url)))
    const text = resolved.join('\n')
    await copyToClipboard(text)
    toast.dismiss(toastId)
    toast.success(`已複製 ${selectedSourceUrls.size} 個連結`)
  }

  const handleMarkAllRead = async () => {
    try {
      await radarAPI.markAllRead()
      setAlerts(prev => prev.map(a => ({ ...a, is_read: true })))
    } catch (err) {
      console.error(err)
    }
  }

  const handleDeleteRead = async () => {
    const readAlerts = alerts.filter(a => a.is_read)
    if (!readAlerts.length) return
    if (!confirm(`確定刪除 ${readAlerts.length} 則已讀信號？`)) return
    try {
      await Promise.all(readAlerts.map(a => radarAPI.deleteAlert(a.id)))
      setAlerts(prev => prev.filter(a => !a.is_read))
    } catch (err) {
      console.error(err)
    }
  }

  const SEVERITY_LABELS = { critical: '緊急', high: '高', medium: '中', low: '低' }

  const severityBadge = (severity) => {
    const cls = {
      critical: 'badge-critical',
      high: 'badge-high',
      medium: 'badge-medium',
      low: 'badge-low',
    }
    return <span className={cls[severity] || 'badge'}>{SEVERITY_LABELS[severity] || severity}</span>
  }

  const lineSeverityBadge = (severity) => {
    const styles = {
      critical: 'bg-red-500/20 text-red-400 border-red-500/30',
      high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
      medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      low: 'bg-green-500/20 text-green-400 border-green-500/30',
    }
    return (
      <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium whitespace-nowrap ${styles[severity] || ''}`}>
        {SEVERITY_LABELS[severity] || severity}
      </span>
    )
  }

  const severityPills = [
    { v: 'all', label: '全部', color: '' },
    { v: 'critical', label: '緊急', color: 'text-red-400' },
    { v: 'high', label: '高', color: 'text-orange-400' },
    { v: 'medium', label: '中', color: 'text-yellow-400' },
    { v: 'low', label: '低', color: 'text-green-400' },
  ]

  const hasActiveFilter = filterSeverity !== 'all' || filterUnread || filterKeyword

  return (
    <div className="space-y-6">
      {/* Alerts Feed */}
      <section>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
          <h3 className="text-lg font-semibold">信號動態</h3>
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            <span className="text-sm text-dark-400">
              {hasActiveFilter
                ? <>{displayAlerts.length} <span className="text-dark-600">/ {alerts.length} 則</span></>
                : <>{alerts.length} 則信號</>
              }
            </span>
            {scanResult && (
              <span className={`text-xs px-2 py-1 rounded-full ${
                scanResult.startsWith('發現') ? 'bg-green-500/20 text-green-400' :
                scanResult.startsWith('掃描失敗') ? 'bg-red-500/20 text-red-400' :
                'bg-dark-700 text-dark-400'
              }`}>{scanResult}</span>
            )}
            {isAdmin && (
              <button
                onClick={handleManualScan}
                disabled={scanning}
                className="btn-primary text-sm flex items-center gap-1.5"
              >
                {scanning ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    掃描中...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M9.348 14.651a3.75 3.75 0 010-5.303m5.304 0a3.75 3.75 0 010 5.303m-7.425 2.122a6.75 6.75 0 010-9.546m9.546 0a6.75 6.75 0 010 9.546" />
                    </svg>
                    立即掃描
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex flex-wrap items-center gap-2 mb-4 p-3 bg-dark-900/50 rounded-xl border border-dark-700 overflow-hidden">
          {/* Severity pills */}
          {severityPills.map(({ v, label, color }) => (
            <button key={v}
              onClick={() => setFilterSeverity(v)}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                filterSeverity === v
                  ? 'bg-primary-600/30 text-primary-400 border-primary-500/40'
                  : `bg-dark-800 ${color || 'text-dark-300'} border-dark-600 hover:border-dark-500`
              }`}>{label}</button>
          ))}

          <div className="w-px h-4 bg-dark-700 mx-1 hidden sm:block" />

          {/* 僅未讀 */}
          <button onClick={() => setFilterUnread(v => !v)}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              filterUnread
                ? 'bg-primary-600/20 text-primary-400 border-primary-500/40'
                : 'bg-dark-800 text-dark-400 border-dark-600 hover:border-dark-500'
            }`}>僅未讀</button>

          {/* 僅收藏（只有 admin 能切換收藏狀態，所以訪客也沒必要看這個篩選） */}
          {isAdmin && (
            <button onClick={() => setFilterSaved(v => !v)}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors flex items-center gap-1 ${
                filterSaved
                  ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/40'
                  : 'bg-dark-800 text-dark-400 border-dark-600 hover:border-dark-500'
              }`}>
              <svg className="w-3 h-3" fill={filterSaved ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
              </svg>
              收藏
            </button>
          )}

          {/* Sort */}
          <button onClick={() => setSortOrder(v => v === 'desc' ? 'asc' : 'desc')}
            className="text-xs px-2.5 py-1 rounded-full border bg-dark-800 text-dark-400 border-dark-600 hover:border-dark-500 transition-colors">
            {sortOrder === 'desc' ? '↓ 最新' : '↑ 最舊'}
          </button>

          {/* Keyword search */}
          <input type="text" value={filterKeyword} onChange={(e) => setFilterKeyword(e.target.value)}
            placeholder="關鍵字篩選..."
            className="text-xs px-3 py-1.5 rounded-lg bg-dark-800 border border-dark-600 text-gray-300 placeholder-dark-500 w-full sm:w-36 focus:outline-none focus:border-primary-500/50" />

          {/* Select all filtered URLs */}
          {hasActiveFilter && displayAlerts.length > 0 && (
            <button
              onClick={handleSelectAllFilteredUrls}
              className="text-xs px-2.5 py-1 rounded-full border bg-dark-800 text-dark-400 border-dark-600 hover:text-primary-400 hover:border-primary-500/40 transition-colors"
            >全選連結</button>
          )}

          {/* Copy + Save selected URLs */}
          {selectedSourceUrls.size > 0 && (
            <>
              <button
                onClick={(e) => handleCopySelectedUrls(e)}
                className="text-xs px-3 py-1 rounded-full border bg-primary-600/20 text-primary-400 border-primary-500/30 hover:bg-primary-600/30 transition-colors flex items-center gap-1.5"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                複製 {selectedSourceUrls.size} 個連結
              </button>
              {isAdmin && (
                <button
                  onClick={async (e) => {
                    e.stopPropagation()
                    // Bookmark all alerts that have at least one selected URL
                    const toSave = alerts.filter(a =>
                      (a.source_urls || []).some(u => selectedSourceUrls.has(u)) && !a.is_saved
                    )
                    await Promise.all(toSave.map(a => handleToggleSave(e, a.id)))
                    if (toSave.length) toast.success(`已收藏 ${toSave.length} 則新聞`)
                    else toast('已全部收藏過了')
                  }}
                  className="text-xs px-2.5 py-1 rounded-full border bg-yellow-500/10 text-yellow-400 border-yellow-500/30 hover:bg-yellow-500/20 transition-colors flex items-center gap-1"
                  title="收藏含選取連結的新聞"
                >
                  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
                  </svg>
                  收藏
                </button>
              )}
              <button
                onClick={() => setSelectedSourceUrls(new Set())}
                className="text-xs px-2 py-1 rounded-full border bg-dark-800 text-dark-500 border-dark-600 hover:text-red-400 transition-colors"
              >✕</button>
            </>
          )}

          {isAdmin && (
            <>
              <div className="w-px h-4 bg-dark-700 mx-1" />

              {/* 全部已讀 */}
              <button onClick={handleMarkAllRead}
                className="text-xs px-2.5 py-1 rounded-full border bg-dark-800 text-dark-400 border-dark-600 hover:text-primary-400 hover:border-primary-500/40 transition-colors">
                全部已讀
              </button>

              {/* 刪除已讀 */}
              <button onClick={handleDeleteRead}
                className="text-xs px-2.5 py-1 rounded-full border bg-dark-800 text-dark-400 border-dark-600 hover:text-red-400 hover:border-red-500/40 transition-colors">
                刪除已讀
              </button>
            </>
          )}
        </div>

        <div className="space-y-3">
          {loading ? (
            Array(3).fill(0).map((_, i) => (
              <div key={i} className="card animate-pulse">
                <div className="h-5 bg-dark-700 rounded w-3/4 mb-2" />
                <div className="h-4 bg-dark-700 rounded w-full mb-1" />
                <div className="h-4 bg-dark-700 rounded w-2/3" />
              </div>
            ))
          ) : displayAlerts.length === 0 ? (
            <div className="card text-center py-12 text-dark-400">
              <svg className="w-16 h-16 mx-auto mb-4 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9.348 14.651a3.75 3.75 0 010-5.303m5.304 0a3.75 3.75 0 010 5.303m-7.425 2.122a6.75 6.75 0 010-9.546m9.546 0a6.75 6.75 0 010 9.546" />
              </svg>
              {hasActiveFilter
                ? <p>沒有符合篩選條件的信號</p>
                : <><p>雷達正在掃描中，尚無信號...</p><p className="text-sm mt-1">系統每 5 分鐘自動檢測一次</p></>
              }
            </div>
          ) : (
            displayAlerts.map(alert => {
              const rawLines = splitArticleLines(alert.content)
              // 標題點擊直達新聞：content 行與 source_urls 同源同序（後端以風險序寫入），
              // 數量一致時逐行配對 URL；不一致（少數舊告警有缺 URL 的文章）該行退回純文字。
              // URL 綁在行物件上一起參與風險排序，不會錯位。
              const parsedUrls = (alert.source_urls || []).map(parseSourceUrl)
              const articleLines = rawLines.length === parsedUrls.length
                ? rawLines.map((l, i) => ({ ...l, url: parsedUrls[i].url }))
                : rawLines
              return (
                <div
                  key={alert.id}
                  className={`card-hover ${!alert.is_read ? 'border-l-4' : ''} ${
                    alert.severity === 'critical' ? 'border-l-red-500' :
                    alert.severity === 'high' ? 'border-l-orange-500' :
                    alert.severity === 'medium' ? 'border-l-yellow-500' : 'border-l-green-500'
                  }`}
                >
                  {/* 手機版：日期+刪除獨立一行，標題全寬 */}
                  <div className="flex items-center justify-between gap-2 mb-1 sm:hidden">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-dark-400 uppercase">{alert.type}</span>
                      {alert.type !== 'news' && severityBadge(alert.severity)}
                      {!alert.is_read && <span className="w-2 h-2 rounded-full bg-primary-500" />}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-dark-500 whitespace-nowrap">
                        {alert.created_at && new Date(alert.created_at).toLocaleString('zh-TW', {
                          month: 'numeric', day: 'numeric',
                          hour: '2-digit', minute: '2-digit'
                        })}
                      </span>
                      {isAdmin && (
                        <button
                          onClick={(e) => handleDeleteAlert(e, alert.id)}
                          className="text-dark-500 hover:text-red-400 transition-colors p-1"
                          title="刪除"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>

                  {/* 桌面版：原始橫排佈局（標題+文章列表在 flex-1 內，日期在右） */}
                  <div className="hidden sm:flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs text-dark-400 uppercase">{alert.type}</span>
                        {alert.type !== 'news' && severityBadge(alert.severity)}
                        {!alert.is_read && <span className="w-2 h-2 rounded-full bg-primary-500" />}
                      </div>
                      {/* 卡片不顯示大標題（新聞行本身就是內容）；非新聞類或無行可顯示時仍用告警標題 */}
                      {(alert.type !== 'news' || articleLines.length === 0) && (
                        <h4 className="font-medium text-gray-200 line-clamp-2">{alert.title}</h4>
                      )}
                      {articleLines.length > 0 && (
                        <div className="space-y-0.5">
                          {(() => {
                            // 先按風險排序，再編號（風險最高 = 1）；一律全部顯示
                            const orderedLines = orderByMode(articleLines).map((l, idx) => ({ ...l, num: idx + 1 }))
                            const visibleLines = filterSeverity !== 'all'
                              ? orderedLines.filter(l => l.severity === filterSeverity)
                              : orderedLines
                            const showLines = visibleLines
                            let kwCount = 0
                            return (
                              <>
                                {showLines.map((line, i) => {
                                  const hasKw = !!line.kw
                                  if (hasKw) kwCount++
                                  return (
                                    <p key={i} className="text-sm text-dark-400 flex items-start gap-1.5">
                                      {line.severity && lineSeverityBadge(line.severity)}
                                      <span className="shrink-0 text-xs text-dark-500 font-mono">{line.num})</span>
                                      {line.url ? (
                                        <a href={line.url} target="_blank" rel="noopener noreferrer"
                                          onClick={() => { if (!alert.is_read) handleMarkRead(alert) }}
                                          title={line.url}
                                          className="min-w-0 flex-1 line-clamp-2 text-gray-300 hover:text-primary-400 hover:underline">
                                          {line.displayLine}
                                        </a>
                                      ) : (
                                        <span className="min-w-0 flex-1 line-clamp-2">{line.displayLine}</span>
                                      )}
                                      {hasKw && kwCount <= 4 && (
                                        <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-primary-600/15 text-primary-400 border border-primary-500/20 whitespace-nowrap cursor-default">
                                          {line.kw}
                                        </span>
                                      )}
                                    </p>
                                  )
                                })}
                              </>
                            )
                          })()}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs text-dark-500 whitespace-nowrap">
                        {alert.created_at && new Date(alert.created_at).toLocaleString('zh-TW', {
                          month: 'numeric', day: 'numeric',
                          hour: '2-digit', minute: '2-digit'
                        })}
                      </span>
                      {isAdmin && (
                        <button
                          onClick={(e) => handleDeleteAlert(e, alert.id)}
                          className="text-dark-500 hover:text-red-400 transition-colors p-1"
                          title="刪除"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>

                  {/* 手機版：文章列表全寬（不顯示大標題） */}
                  <div className="min-w-0 sm:hidden">
                    {(alert.type !== 'news' || articleLines.length === 0) && (
                      <h4 className="font-medium text-gray-200 line-clamp-2">{alert.title}</h4>
                    )}
                    {articleLines.length > 0 && (
                      <div className="space-y-0.5">
                        {(() => {
                          // 先按風險排序，再編號（風險最高 = 1）；一律全部顯示
                          const orderedLines = orderByMode(articleLines).map((l, idx) => ({ ...l, num: idx + 1 }))
                          const visibleLines = filterSeverity !== 'all'
                            ? orderedLines.filter(l => l.severity === filterSeverity)
                            : orderedLines
                          const showLines = visibleLines
                          return (
                            <>
                              {showLines.map((line, i) => (
                                <p key={i} className="text-sm text-dark-400 flex items-start gap-1.5">
                                  {line.severity && lineSeverityBadge(line.severity)}
                                  <span className="shrink-0 text-xs text-dark-500 font-mono">{line.num})</span>
                                  {line.url ? (
                                    <a href={line.url} target="_blank" rel="noopener noreferrer"
                                      onClick={() => { if (!alert.is_read) handleMarkRead(alert) }}
                                      className="min-w-0 flex-1 line-clamp-2 text-gray-300 active:text-primary-400">
                                      {line.displayLine}
                                    </a>
                                  ) : (
                                    <span className="min-w-0 flex-1 line-clamp-2">{line.displayLine}</span>
                                  )}
                                </p>
                              ))}
                            </>
                          )
                        })()}
                      </div>
                    )}
                  </div>

                </div>
              )
            })
          )}
        </div>
      </section>
    </div>
  )
}
