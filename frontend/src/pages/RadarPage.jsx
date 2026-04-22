import { useCallback, useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import { radarAPI, resolveUrl, settingsAPI, copyToClipboard } from '../services/api'

export default function RadarPage({ wsSubscribe }) {
  const [alerts, setAlerts] = useState([])
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [analyzingId, setAnalyzingId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState(null)
  const [aiLabel, setAiLabel] = useState('Gemini')

  // Filter & sort state
  const [filterSeverity, setFilterSeverity] = useState('all')
  const [filterUnread, setFilterUnread] = useState(false)
  const [filterSaved, setFilterSaved] = useState(false)
  const [sortOrder, setSortOrder] = useState('desc')
  const [filterKeyword, setFilterKeyword] = useState('')
  const [copiedUrl, setCopiedUrl] = useState(null)
  // Source URL selection (global across all alerts)
  const [selectedSourceUrls, setSelectedSourceUrls] = useState(new Set())

  useEffect(() => {
    settingsAPI.getAIModel().then(({ data }) => {
      setAiLabel(data.model === 'gemini' ? 'Gemini' : 'Claude')
    }).catch(() => {})
  }, [])

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
    // 新格式（後端已萃取）：不含布林語法，直接顯示
    const isRawTopic = kw.includes(' OR ') || kw.startsWith('(') || kw.includes('"')
    if (!isRawTopic) return kw.length <= 40 ? kw : kw.slice(0, 38) + '…'
    // 舊格式（原始 topic 字串）：萃取前 3 個詞顯示
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
      if (selectedAlert?.id === alertId) setSelectedAlert(prev => ({ ...prev, is_saved: data.is_saved }))
    } catch (err) {
      console.error('Failed to toggle save:', err)
    }
  }

  const handleDeleteAlert = async (e, alertId) => {
    e.stopPropagation()
    try {
      await radarAPI.deleteAlert(alertId)
      setAlerts(prev => prev.filter(a => a.id !== alertId))
      if (selectedAlert?.id === alertId) setSelectedAlert(null)
    } catch (err) {
      console.error('Failed to delete alert:', err)
    }
  }

  const handleAnalyze = async (e, alert) => {
    e.stopPropagation()
    setAnalyzingId(alert.id)
    try {
      const { data } = await radarAPI.analyzeAlert(alert.id)
      setAlerts(prev => prev.map(a => a.id === alert.id ? { ...a, analysis: data.analysis } : a))
      if (selectedAlert?.id === alert.id) {
        setSelectedAlert(prev => ({ ...prev, analysis: data.analysis }))
      }
    } catch (err) {
      console.error('Failed to analyze alert:', err)
    }
    setAnalyzingId(null)
  }

  const handleCopyUrl = async (e, url) => {
    e.stopPropagation()
    try {
      const finalUrl = await resolveUrl(url)
      await copyToClipboard(finalUrl)
      setCopiedUrl(url)
      toast.success('已複製連結')
      setTimeout(() => setCopiedUrl(null), 2000)
    } catch (err) {
      console.error('Copy failed:', err)
    }
  }

  const handleToggleSourceUrl = (e, url) => {
    e.stopPropagation()
    setSelectedSourceUrls(prev => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
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
      if (selectedAlert && readAlerts.find(a => a.id === selectedAlert.id)) setSelectedAlert(null)
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

  const parseAnalysisSections = (text) => {
    if (!text) return null
    const sections = []
    const regex = /【([^】]+)】\s*([\s\S]*?)(?=【|$)/g
    let match
    while ((match = regex.exec(text)) !== null) {
      const content = match[2].trim()
      if (content) sections.push({ title: match[1], content })
    }
    return sections.length ? sections : null
  }

  const sectionStyle = (title) => {
    if (title.includes('摘要') || title.includes('發生')) {
      return { box: 'bg-blue-500/10 border border-blue-500/20', heading: 'text-blue-400' }
    }
    if (title.includes('暴險') || title.includes('部位')) {
      return { box: 'bg-yellow-500/10 border border-yellow-500/20', heading: 'text-yellow-400' }
    }
    return { box: 'bg-purple-500/10 border border-purple-500/20', heading: 'text-purple-400' }
  }

  const renderFollowUp = (content) => {
    const parts = content.split(/\n|(?=樂觀情境[：:]|基本情境[：:]|悲觀情境[：:])/)
      .map(s => s.replace(/^[•\-\s]+/, '').trim())
      .filter(Boolean)
    if (parts.length < 2) {
      return <p className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">{content}</p>
    }
    return (
      <ul className="space-y-2">
        {parts.map((item, i) => (
          <li key={i} className="text-sm text-gray-300 flex gap-2 leading-relaxed">
            <span className="text-purple-400 shrink-0 mt-0.5">•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
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
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">信號動態</h3>
          <div className="flex items-center gap-3">
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
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex flex-wrap items-center gap-2 mb-4 p-3 bg-dark-900/50 rounded-xl border border-dark-700">
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

          <div className="w-px h-4 bg-dark-700 mx-1" />

          {/* 僅未讀 */}
          <button onClick={() => setFilterUnread(v => !v)}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              filterUnread
                ? 'bg-primary-600/20 text-primary-400 border-primary-500/40'
                : 'bg-dark-800 text-dark-400 border-dark-600 hover:border-dark-500'
            }`}>僅未讀</button>

          {/* 僅收藏 */}
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

          {/* Sort */}
          <button onClick={() => setSortOrder(v => v === 'desc' ? 'asc' : 'desc')}
            className="text-xs px-2.5 py-1 rounded-full border bg-dark-800 text-dark-400 border-dark-600 hover:border-dark-500 transition-colors">
            {sortOrder === 'desc' ? '↓ 最新' : '↑ 最舊'}
          </button>

          <div className="flex-1" />

          {/* Keyword search */}
          <input type="text" value={filterKeyword} onChange={(e) => setFilterKeyword(e.target.value)}
            placeholder="關鍵字篩選..."
            className="text-xs px-3 py-1.5 rounded-lg bg-dark-800 border border-dark-600 text-gray-300 placeholder-dark-500 w-36 focus:outline-none focus:border-primary-500/50" />

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
              <button
                onClick={() => setSelectedSourceUrls(new Set())}
                className="text-xs px-2 py-1 rounded-full border bg-dark-800 text-dark-500 border-dark-600 hover:text-red-400 transition-colors"
              >✕</button>
            </>
          )}

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
              const articleLines = splitArticleLines(alert.content)
              return (
                <div
                  key={alert.id}
                  className={`card-hover cursor-pointer ${!alert.is_read ? 'border-l-4' : ''} ${
                    alert.severity === 'critical' ? 'border-l-red-500' :
                    alert.severity === 'high' ? 'border-l-orange-500' :
                    alert.severity === 'medium' ? 'border-l-yellow-500' : 'border-l-green-500'
                  }`}
                  onClick={() => {
                    setSelectedAlert(selectedAlert?.id === alert.id ? null : alert)
                    if (!alert.is_read) handleMarkRead(alert)
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs text-dark-400 uppercase">{alert.type}</span>
                        {alert.type !== 'news' && severityBadge(alert.severity)}
                        {!alert.is_read && <span className="w-2 h-2 rounded-full bg-primary-500" />}
                      </div>
                      <h4 className="font-medium text-gray-200">{alert.title}</h4>

                      {articleLines.length > 0 && (
                        <div className="mt-1.5 space-y-0.5">
                          {(() => {
                            const numberedLines = articleLines.map((l, idx) => ({ ...l, num: idx + 1 }))
                            const visibleLines = filterSeverity !== 'all'
                              ? numberedLines.filter(l => l.severity === filterSeverity)
                              : numberedLines
                            const showLines = selectedAlert?.id === alert.id ? visibleLines : visibleLines.slice(0, 3)
                            return (
                              <>
                                {showLines.map((line, i) => (
                                  <p key={i} className="text-sm text-dark-400 flex items-center gap-1.5">
                                    {line.severity && lineSeverityBadge(line.severity)}
                                    <span className="shrink-0 text-xs text-dark-500 font-mono">{line.num})</span>
                                    <span className="min-w-0 flex-1 line-clamp-2">{line.displayLine}</span>
                                    {line.kw && (
                                      <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-primary-600/15 text-primary-400 border border-primary-500/20 whitespace-nowrap cursor-default">
                                        {line.kw}
                                      </span>
                                    )}
                                  </p>
                                ))}
                                {selectedAlert?.id !== alert.id && visibleLines.length > 3 && (
                                  <p className="text-xs text-dark-500">...共 {visibleLines.length} 則</p>
                                )}
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
                    </div>
                  </div>

                  {/* Expanded Detail */}
                  {selectedAlert?.id === alert.id && (
                    <div className="mt-4 pt-4 border-t border-dark-700 space-y-3">
                      {/* Exposure Summary */}
                      {alert.exposure_summary && (
                        <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3">
                          <h5 className="text-sm font-semibold text-yellow-400 mb-1">可能影響部位</h5>
                          <pre className="text-sm text-gray-300 whitespace-pre-wrap">{alert.exposure_summary}</pre>
                        </div>
                      )}

                      {/* Source URLs with checkboxes and copy buttons */}
                      {alert.source_urls && alert.source_urls.length > 0 && (() => {
                        const allUrls = alert.source_urls.map((u, idx) => ({ ...parseSourceUrl(u), num: idx + 1 }))
                        let displayUrls = allUrls
                        if (filterSeverity !== 'all') {
                          const filtered = allUrls.filter(u => u.severity === filterSeverity)
                          displayUrls = filtered.length > 0 ? filtered : allUrls
                        }
                        if (displayUrls.length === 0) return null;

                        return (
                          <div>
                            <div className="flex items-center gap-2 mb-1.5">
                              <h5 className="text-sm font-semibold text-dark-300">資料來源</h5>
                              {/* Per-alert select-all — inline with title */}
                              <label className="flex items-center gap-1 cursor-pointer select-none" onClick={(e) => e.stopPropagation()}>
                                <input
                                    type="checkbox"
                                    checked={displayUrls.every(u => selectedSourceUrls.has(u.raw))}
                                    onChange={(e) => {
                                      e.stopPropagation()
                                      if (e.target.checked) {
                                        setSelectedSourceUrls(prev => {
                                          const next = new Set(prev)
                                          displayUrls.forEach(u => next.add(u.raw))
                                          return next
                                        })
                                      } else {
                                        setSelectedSourceUrls(prev => {
                                          const next = new Set(prev)
                                          displayUrls.forEach(u => next.delete(u.raw))
                                          return next
                                        })
                                      }
                                    }}
                                    className="rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500 w-3.5 h-3.5 cursor-pointer"
                                  />
                                  <span className="text-xs text-dark-500">全選此則</span>
                              </label>
                            </div>
                            <div className="space-y-1.5">
                              {displayUrls.map((parsed, i) => (
                                <div key={i} className={`flex items-center gap-2 p-1 rounded transition-colors ${selectedSourceUrls.has(parsed.raw) ? 'bg-primary-600/10' : ''}`}>
                                  <input
                                    type="checkbox"
                                    checked={selectedSourceUrls.has(parsed.raw)}
                                    onChange={(e) => handleToggleSourceUrl(e, parsed.raw)}
                                    className="rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500 w-4 h-4 shrink-0 cursor-pointer"
                                  />
                                  {parsed.severity && lineSeverityBadge(parsed.severity)}
                                  <span className="shrink-0 text-xs text-dark-500 font-mono">{parsed.num})</span>
                                  <a href={parsed.url} target="_blank" rel="noopener noreferrer"
                                    onClick={(e) => e.stopPropagation()}
                                    title={parsed.url}
                                    className="text-xs text-primary-400 hover:underline break-all flex-1 line-clamp-1">
                                    {parsed.url}
                                  </a>
                                  <button
                                    onClick={(e) => handleCopyUrl(e, parsed.url)}
                                    className="shrink-0 p-1.5 rounded text-dark-500 hover:text-primary-400 hover:bg-dark-700 transition-colors"
                                    title="複製連結"
                                  >
                                    {copiedUrl === parsed.url ? (
                                      <svg className="w-4 h-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                                      </svg>
                                    ) : (
                                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                          d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                      </svg>
                                    )}
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        )
                      })()}

                      {/* AI Analysis */}
                      {alert.analysis ? (
                        <div>
                          <h5 className="text-sm font-semibold text-primary-400 mb-2">AI 分析</h5>
                          {(() => {
                            const sections = parseAnalysisSections(alert.analysis)
                            if (sections) {
                              return (
                                <div className="space-y-2">
                                  {sections.map(sec => {
                                    const style = sectionStyle(sec.title)
                                    return (
                                      <div key={sec.title} className={`rounded-lg p-3 ${style.box}`}>
                                        <h6 className={`text-xs font-bold mb-1.5 ${style.heading}`}>【{sec.title}】</h6>
                                        {sec.title.includes('後續') ? renderFollowUp(sec.content) : (
                                          <p className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">{sec.content}</p>
                                        )}
                                      </div>
                                    )
                                  })}
                                </div>
                              )
                            }
                            return <p className="text-sm text-gray-300 whitespace-pre-wrap">{alert.analysis}</p>
                          })()}
                        </div>
                      ) : (
                        <button
                          onClick={(e) => handleAnalyze(e, alert)}
                          disabled={analyzingId === alert.id}
                          className="btn-primary text-sm flex items-center gap-2"
                        >
                          {analyzingId === alert.id ? (
                            <>
                              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                              </svg>
                              AI 分析中...
                            </>
                          ) : (
                            <>
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                  d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                              </svg>
                              AI 深度分析
                              <span className="text-xs opacity-60 ml-1">[{aiLabel}]</span>
                            </>
                          )}
                        </button>
                      )}

                      {/* Legacy source_url fallback */}
                      {alert.source_url && !alert.source_urls?.length && (
                        <div className={`flex items-center gap-2 p-1 rounded transition-colors ${selectedSourceUrls.has(alert.source_url) ? 'bg-primary-600/10' : ''}`}>
                          <input
                            type="checkbox"
                            checked={selectedSourceUrls.has(alert.source_url)}
                            onChange={(e) => handleToggleSourceUrl(e, alert.source_url)}
                            className="rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500 w-4 h-4 shrink-0 cursor-pointer"
                          />
                          <a href={alert.source_url} target="_blank" rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-xs text-primary-400 hover:underline break-all flex-1">
                            查看原始來源
                          </a>
                          <button
                            onClick={(e) => handleCopyUrl(e, alert.source_url)}
                            className="shrink-0 p-1.5 rounded text-dark-500 hover:text-primary-400 hover:bg-dark-700 transition-colors"
                            title="複製連結"
                          >
                            {copiedUrl === alert.source_url ? (
                              <svg className="w-4 h-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                              </svg>
                            ) : (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                              </svg>
                            )}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </section>
    </div>
  )
}
