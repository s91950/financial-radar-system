import { useCallback, useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import { newsAPI, settingsAPI, resolveUrl, copyToClipboard } from '../services/api'

// Severity assessment — mirrors backend _assess_severity_single logic
const CRITICAL_KWS = ['崩盤', '暴跌', '危機', 'crash', 'crisis', 'emergency',
  '戰爭', '制裁', '違約', '破產', '倒閉', '破產保護', '債務違約',
  '勒索軟體', '網路攻擊', '資料外洩']
const HIGH_KWS = ['升息', '降息', '衰退', 'recession', 'inflation', '通膨',
  '獨家', '重訊', '重大訊息', '盈餘警告', '虧損擴大', '淨損',
  '信用評等', '調降', '縮編', '重組', '裁員', '出口禁令']

function assessSeverity(title = '', content = '') {
  const text = (title + ' ' + content).toLowerCase()
  if (CRITICAL_KWS.some(kw => text.includes(kw))) return 'critical'
  if (HIGH_KWS.some(kw => text.includes(kw))) return 'high'
  return 'low'
}

const SEVERITY_CFG = {
  critical: { label: '緊急', pill: 'bg-red-500/20 text-red-400 border-red-500/30' },
  high:     { label: '高',   pill: 'bg-orange-500/20 text-orange-400 border-orange-500/30' },
  medium:   { label: '中',   pill: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' },
  low:      { label: '低',   pill: 'bg-green-500/20 text-green-400 border-green-500/30' },
}

function SeverityBadge({ severity }) {
  const cfg = SEVERITY_CFG[severity] || SEVERITY_CFG.low
  return (
    <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium whitespace-nowrap ${cfg.pill}`}>
      {cfg.label}
    </span>
  )
}

export default function NewsDBPage() {
  const [articles, setArticles] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [fetchLoading, setFetchLoading] = useState(false)
  const [selectedArticle, setSelectedArticle] = useState(null)
  const [filters, setFilters] = useState({
    saved_only: false,
    category: '',
    source: '',
    keyword: '',
    search: '',
    date_from: '',
    date_to: '',
  })
  const [showDateFilter, setShowDateFilter] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [customQuery, setCustomQuery] = useState('')
  const [fetchHoursBack, setFetchHoursBack] = useState(24)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)

  // Sort & filter state
  const [sortOrder, setSortOrder] = useState('newest')  // 'newest'|'oldest'|'source'
  const [categories, setCategories] = useState([])
  const [sourceList, setSourceList] = useState([])
  const [keywordList, setKeywordList] = useState([])

  // Preview state
  const [preview, setPreview] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [saving, setSaving] = useState(false)
  const [previewSeverityFilter, setPreviewSeverityFilter] = useState('all')

  // DB article multi-select + severity filter state
  const [selectedDbIds, setSelectedDbIds] = useState(new Set())
  const [dbSeverityFilter, setDbSeverityFilter] = useState('all')

  // Reset to page 0 when pageSize or severity filter changes
  const handlePageSizeChange = (newSize) => { setPageSize(newSize); setPage(0) }
  const handleSeverityFilter = (v) => { setDbSeverityFilter(v); setPage(0); setSelectedDbIds(new Set()) }

  useEffect(() => {
    newsAPI.getCategories().then(({ data }) => setCategories(data)).catch(() => {})
    newsAPI.getSources().then(({ data }) => setSourceList(data)).catch(() => {})
    newsAPI.getKeywords().then(({ data }) => setKeywordList(data)).catch(() => {})
  }, [])

  const loadArticles = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await newsAPI.getArticles({
        limit: pageSize,
        offset: page * pageSize,
        severity: dbSeverityFilter !== 'all' ? dbSeverityFilter : undefined,
        ...filters,
      })
      setArticles(data.articles)
      setTotal(data.total)
      setSelectedDbIds(new Set())
    } catch (err) {
      console.error('Failed to load articles:', err)
    }
    setLoading(false)
  }, [page, pageSize, dbSeverityFilter, filters])

  useEffect(() => {
    loadArticles()
  }, [loadArticles])

  // Client-side sort only (severity filter is server-side)
  let sortedArticles = [...articles]
  if (sortOrder === 'oldest') {
    sortedArticles.sort((a, b) => new Date(a.published_at) - new Date(b.published_at))
  } else if (sortOrder === 'source') {
    sortedArticles.sort((a, b) => (a.source || '').localeCompare(b.source || ''))
  } else {
    sortedArticles.sort((a, b) => new Date(b.published_at) - new Date(a.published_at))
  }

  const handleManualFetch = async (query = null, sourceType = 'sources_only') => {
    setFetchLoading(true)
    setPreview(null)
    setPreviewSeverityFilter('all')
    try {
      const { data } = await newsAPI.manualFetch({
        query: query || null,
        hours_back: fetchHoursBack,
        source_type: sourceType,
      })
      setPreview(data.preview || [])
      const newIds = new Set()
      ;(data.preview || []).forEach((a, i) => {
        if (!a.already_in_db) newIds.add(i)
      })
      setSelectedIds(newIds)
      toast.success(`取得 ${data.fetched} 則新聞，請選擇要儲存的`)
    } catch (err) {
      console.error('Fetch failed:', err)
      toast.error('抓取失敗')
    }
    setFetchLoading(false)
  }

  const handleSourceSearch = (e) => {
    e.preventDefault()
    handleManualFetch(customQuery.trim() || null, 'sources_only')
    setCustomQuery('')
  }

  const handleGnSearch = (e) => {
    e.preventDefault()
    handleManualFetch(customQuery.trim() || null, 'gn_only')
    setCustomQuery('')
  }

  const handleTogglePreviewItem = (idx) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const handleSelectAll = () => {
    if (!preview) return
    const allNew = new Set()
    filteredPreview.forEach((_, i) => {
      const origIdx = filteredPreviewIndices[i]
      if (!preview[origIdx].already_in_db) allNew.add(origIdx)
    })
    setSelectedIds(allNew)
  }

  const handleDeselectAll = () => {
    setSelectedIds(new Set())
  }

  const handleCopySelected = async () => {
    if (!preview || selectedIds.size === 0) return
    const urls = preview
      .filter((a, i) => selectedIds.has(i) && a.source_url)
      .map(a => a.source_url)
    if (urls.length === 0) return
    const toastId = toast.loading(`解析 ${urls.length} 個連結...`)
    const resolved = await Promise.all(urls.map(u => resolveUrl(u)))
    copyToClipboard(resolved.join('\n'))
    toast.dismiss(toastId)
    toast.success(`已複製 ${resolved.length} 個連結`)
  }

  const handleSaveSelected = async () => {
    if (!preview || selectedIds.size === 0) return
    setSaving(true)
    const toSave = preview.filter((_, i) => selectedIds.has(i))
    try {
      const { data } = await newsAPI.saveSelected({ articles: toSave })
      toast.success(`已儲存 ${data.saved} 則到資料庫${data.sheets_saved ? `，${data.sheets_saved} 則到 Google Sheets` : ''}`)
      setPreview(null)
      setSelectedIds(new Set())
      loadArticles()
    } catch (err) {
      console.error('Save failed:', err)
      toast.error('儲存失敗')
    }
    setSaving(false)
  }

  const handleToggleSave = async (article) => {
    try {
      const { data } = await newsAPI.updateArticle(article.id, {
        is_saved: !article.is_saved,
      })
      setArticles(prev => prev.map(a => a.id === article.id ? { ...a, is_saved: data.is_saved } : a))
      if (selectedArticle?.id === article.id) {
        setSelectedArticle({ ...selectedArticle, is_saved: data.is_saved })
      }
    } catch (err) {
      console.error(err)
    }
  }

  const handleAddTag = async (article, tag) => {
    const currentTags = article.tags || []
    if (currentTags.includes(tag)) return
    try {
      const newTags = [...currentTags, tag]
      await newsAPI.updateArticle(article.id, { tags: newTags })
      setArticles(prev => prev.map(a => a.id === article.id ? { ...a, tags: newTags } : a))
    } catch (err) {
      console.error(err)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('確定刪除此文章？')) return
    try {
      await newsAPI.deleteArticle(id)
      setArticles(prev => prev.filter(a => a.id !== id))
      if (selectedArticle?.id === id) setSelectedArticle(null)
    } catch (err) {
      console.error(err)
    }
  }

  const handleSearch = (e) => {
    e.preventDefault()
    setFilters(prev => ({ ...prev, search: searchInput }))
    setPage(0)
  }

  const handleExport = () => {
    const params = new URLSearchParams({ format: 'csv', saved_only: String(filters.saved_only) })
    window.open(`/api/news/export?${params.toString()}`, '_blank')
  }

  const handleCopyUrl = async (url) => {
    const finalUrl = await resolveUrl(url)
    copyToClipboard(finalUrl)
    toast.success('已複製連結')
  }

  // DB article multi-select handlers
  const handleToggleDbSelect = (e, id) => {
    e.stopPropagation()
    setSelectedDbIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSelectAllDb = () => {
    // Select all articles currently visible (after severity filter)
    setSelectedDbIds(new Set(sortedArticles.map(a => a.id)))
  }

  const handleDeselectAllDb = () => {
    setSelectedDbIds(new Set())
  }

  const handleCopySelectedDb = async () => {
    if (!selectedDbIds.size) return
    const urls = sortedArticles
      .filter(a => selectedDbIds.has(a.id) && a.source_url)
      .map(a => a.source_url)
    if (!urls.length) { toast.error('選取的文章無來源連結'); return }
    const toastId = toast.loading(`解析 ${urls.length} 個連結...`)
    const resolved = await Promise.all(urls.map(u => resolveUrl(u)))
    await copyToClipboard(resolved.filter(Boolean).join('\n'))
    toast.dismiss(toastId)
    toast.success(`已複製 ${resolved.length} 個連結`)
  }

  // Preview filtered by severity
  const filteredPreviewIndices = preview
    ? preview
        .map((a, i) => i)
        .filter(i => previewSeverityFilter === 'all' || assessSeverity(preview[i].title, preview[i].content) === previewSeverityFilter)
    : []
  const filteredPreview = filteredPreviewIndices.map(i => preview[i])

  const newCount = preview ? preview.filter((_, i) => selectedIds.has(i)).length : 0

  const PREVIEW_SEVERITY_PILLS = [
    { v: 'all', label: '全部' },
    { v: 'critical', label: '緊急' },
    { v: 'high', label: '高風險' },
    { v: 'low', label: '低風險' },
  ]

  return (
    <div className="space-y-6">
      {/* Preview Panel */}
      {preview && (
        <div className="card border-primary-500/20">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold">
              搜尋結果預覽
              <span className="text-sm text-dark-400 font-normal ml-2">({preview.length} 則)</span>
            </h3>
            <div className="flex items-center gap-2">
              {selectedIds.size > 0 && (
                <button
                  onClick={handleCopySelected}
                  className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border bg-primary-600/20 text-primary-400 border-primary-500/30 hover:bg-primary-600/30 transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  複製 {selectedIds.size} 個連結
                </button>
              )}
              <button onClick={handleSelectAll} className="text-xs text-primary-400 hover:underline">全選</button>
              <button onClick={handleDeselectAll} className="text-xs text-dark-400 hover:underline">取消全選</button>
            </div>
          </div>

          {/* Severity filter pills for preview */}
          <div className="flex items-center gap-1.5 mb-3 flex-wrap">
            {PREVIEW_SEVERITY_PILLS.map(({ v, label }) => {
              const cfg = SEVERITY_CFG[v]
              return (
                <button
                  key={v}
                  onClick={() => setPreviewSeverityFilter(v)}
                  className={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
                    previewSeverityFilter === v
                      ? (cfg ? cfg.pill + ' font-medium' : 'bg-primary-600/30 text-primary-400 border-primary-500/40')
                      : 'bg-dark-800 text-dark-400 border-dark-600 hover:border-dark-500'
                  }`}
                >
                  {label}
                </button>
              )
            })}
          </div>

          <div className="space-y-1 max-h-80 overflow-y-auto">
            {filteredPreview.length === 0 ? (
              <p className="text-sm text-dark-500 text-center py-4">此風險等級無符合項目</p>
            ) : (
              filteredPreview.map((article, _i) => {
                const origIdx = filteredPreviewIndices[_i]
                const sev = assessSeverity(article.title, article.content)
                return (
                  <label
                    key={origIdx}
                    className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors ${
                      article.already_in_db
                        ? 'opacity-50'
                        : selectedIds.has(origIdx)
                        ? 'bg-primary-600/10'
                        : 'hover:bg-dark-800'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(origIdx)}
                      disabled={article.already_in_db}
                      onChange={() => handleTogglePreviewItem(origIdx)}
                      className="rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500"
                    />
                    <SeverityBadge severity={sev} />
                    {article.matched_keyword && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-primary-600/20 text-primary-400 whitespace-nowrap shrink-0">
                        {article.matched_keyword}
                      </span>
                    )}
                    <div className="flex-1 min-w-0">
                      <span className="text-sm text-gray-200 line-clamp-1">{article.title}</span>
                      <span className="text-xs text-dark-500 ml-2">[{article.source}]</span>
                    </div>
                    {article.already_in_db && (
                      <span className="text-xs text-dark-500 whitespace-nowrap">已存在</span>
                    )}
                    {article.source_url && (
                      <a
                        href={article.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-dark-400 hover:text-primary-400"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                        </svg>
                      </a>
                    )}
                  </label>
                )
              })
            )}
          </div>
          <div className="flex items-center justify-end gap-3 mt-4 pt-4 border-t border-dark-700">
            <button onClick={() => { setPreview(null); setSelectedIds(new Set()); setPreviewSeverityFilter('all') }}
              className="btn-secondary text-sm">取消</button>
            <button
              onClick={handleSaveSelected}
              disabled={saving || newCount === 0}
              className="btn-primary text-sm flex items-center gap-2"
            >
              {saving && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />}
              儲存選取 ({newCount})
            </button>
          </div>
        </div>
      )}

      {/* Action Bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* 時間範圍 */}
        <select
          value={fetchHoursBack}
          onChange={(e) => setFetchHoursBack(Number(e.target.value))}
          className="input w-28 text-sm"
          disabled={fetchLoading}
        >
          <option value={6}>6 小時</option>
          <option value={12}>12 小時</option>
          <option value={24}>24 小時</option>
          <option value={48}>48 小時</option>
          <option value={72}>72 小時</option>
        </select>

        {/* 搜尋輸入 */}
        <input
          type="text"
          value={customQuery}
          onChange={(e) => setCustomQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSourceSearch(e) }}
          placeholder="關鍵字（空白=雷達主題）"
          className="input w-48"
        />

        {/* 抓取來源新聞（預設）*/}
        <button
          onClick={(e) => handleSourceSearch(e)}
          disabled={fetchLoading}
          className="btn-primary flex items-center gap-2"
        >
          {fetchLoading ? (
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
          ) : (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
          )}
          抓取來源新聞
        </button>

        {/* Google News 搜尋 */}
        <button
          onClick={(e) => handleGnSearch(e)}
          disabled={fetchLoading}
          className="btn-secondary flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          Google News
        </button>

        <div className="flex-1" />

        <button
          onClick={() => setFilters(prev => ({ ...prev, saved_only: !prev.saved_only }))}
          className={`btn-secondary flex items-center gap-1.5 ${
            filters.saved_only ? 'bg-primary-600/20 text-primary-400 border-primary-500/30' : ''
          }`}
        >
          <svg className="w-4 h-4" fill={filters.saved_only ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
          </svg>
          已收藏
        </button>

        {/* Export CSV */}
        <button onClick={handleExport} className="btn-secondary flex items-center gap-1.5">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          匯出 CSV
        </button>

        <span className="text-sm text-dark-400">{total} 篇文章</span>
      </div>

      {/* Filter / Search */}
      <div className="space-y-2">
        {/* Severity filter pills for DB list */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {[
            { v: 'all', label: '全部' },
            { v: 'critical', label: '緊急' },
            { v: 'high', label: '高' },
            { v: 'low', label: '低' },
          ].map(({ v, label }) => {
            const cfg = SEVERITY_CFG[v]
            return (
              <button
                key={v}
                onClick={() => handleSeverityFilter(v)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  dbSeverityFilter === v
                    ? (cfg ? cfg.pill + ' font-medium' : 'bg-primary-600/30 text-primary-400 border-primary-500/40')
                    : 'bg-dark-800 text-dark-400 border-dark-600 hover:border-dark-500'
                }`}
              >
                {label}
              </button>
            )
          })}
          <span className="text-xs text-dark-500">
            顯示 {total} 篇
          </span>
        </div>

        <div className="flex flex-wrap gap-2 md:gap-3 items-center">
          <form onSubmit={handleSearch} className="flex flex-wrap gap-2 items-center w-full sm:w-auto">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="搜尋資料庫中的文章..."
              className="input w-full sm:w-44"
            />
            {/* 全選 / 取消全選 */}
            {selectedDbIds.size > 0 ? (
              <button
                type="button"
                onClick={handleDeselectAllDb}
                className="btn-secondary text-sm text-primary-400"
              >
                取消全選 ({selectedDbIds.size})
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSelectAllDb}
                className="btn-secondary text-sm"
                title="全選目前頁面文章"
              >
                全選
              </button>
            )}
            {/* 複製選取連結 */}
            <button
              type="button"
              onClick={handleCopySelectedDb}
              disabled={!selectedDbIds.size}
              className={`flex items-center gap-1 text-sm px-3 py-1.5 rounded-lg border transition-colors ${
                selectedDbIds.size
                  ? 'bg-primary-600/20 text-primary-400 border-primary-500/30 hover:bg-primary-600/30'
                  : 'btn-secondary opacity-40 cursor-not-allowed'
              }`}
              title={selectedDbIds.size ? `複製 ${selectedDbIds.size} 篇文章連結` : '尚未選取'}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              複製{selectedDbIds.size > 0 ? ` (${selectedDbIds.size})` : ''}
            </button>
            <button
              type="button"
              onClick={() => setShowDateFilter(v => !v)}
              className={`btn-secondary flex items-center gap-1.5 shrink-0 ${
                showDateFilter || filters.date_from || filters.date_to
                  ? 'bg-primary-600/20 text-primary-400 border-primary-500/30'
                  : ''
              }`}
              title="日期範圍篩選"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
              日期
              {(filters.date_from || filters.date_to) && (
                <span className="w-1.5 h-1.5 rounded-full bg-primary-400" />
              )}
            </button>
            <button type="submit" className="btn-secondary">篩選</button>
            {(filters.search || filters.date_from || filters.date_to || filters.source || filters.keyword) && (
              <button type="button" onClick={() => {
                setSearchInput('')
                setFilters(prev => ({ ...prev, search: '', date_from: '', date_to: '', source: '', keyword: '' }))
                setPage(0)
              }} className="btn-secondary text-red-400">清除</button>
            )}
          </form>

          {/* Sort */}
          <select value={sortOrder} onChange={(e) => setSortOrder(e.target.value)} className="input text-sm w-32">
            <option value="newest">最新優先</option>
            <option value="oldest">最舊優先</option>
            <option value="source">來源 A-Z</option>
          </select>

          {/* Source filter */}
          <select
            value={filters.source}
            onChange={(e) => { setFilters(prev => ({ ...prev, source: e.target.value })); setPage(0) }}
            className="input text-sm w-44"
          >
            <option value="">全部來源</option>
            {sourceList.map(s => (
              <option key={s.name} value={s.name}>
                {s.name === '__other__' ? `其他來源 (${s.count})` : `${s.name} (${s.count})`}
              </option>
            ))}
          </select>

          {/* Keyword filter */}
          <select
            value={filters.keyword}
            onChange={(e) => { setFilters(prev => ({ ...prev, keyword: e.target.value })); setPage(0) }}
            className="input text-sm w-40"
          >
            <option value="">全部關鍵字</option>
            {keywordList.map(k => <option key={k.keyword} value={k.keyword}>{k.keyword} ({k.count})</option>)}
          </select>
        </div>

        {/* Date range panel */}
        {showDateFilter && (
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-dark-800/60 border border-dark-700">
            <span className="text-xs text-dark-400 shrink-0">發布日期</span>
            <input
              type="date"
              value={filters.date_from}
              onChange={(e) => { setFilters(prev => ({ ...prev, date_from: e.target.value })); setPage(0) }}
              className="input text-sm py-1.5 w-36"
            />
            <span className="text-xs text-dark-500">至</span>
            <input
              type="date"
              value={filters.date_to}
              onChange={(e) => { setFilters(prev => ({ ...prev, date_to: e.target.value })); setPage(0) }}
              className="input text-sm py-1.5 w-36"
            />
            {(filters.date_from || filters.date_to) && (
              <button
                onClick={() => { setFilters(prev => ({ ...prev, date_from: '', date_to: '' })); setPage(0) }}
                className="text-xs text-dark-500 hover:text-red-400 transition-colors"
              >
                × 清除日期
              </button>
            )}
          </div>
        )}
      </div>

      {/* Articles List */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-6">
        {/* List */}
        <div className={`space-y-2 ${selectedArticle ? 'hidden lg:block lg:col-span-1' : 'lg:col-span-3'}`}>
          {loading ? (
            Array(5).fill(0).map((_, i) => (
              <div key={i} className="card animate-pulse">
                <div className="h-5 bg-dark-700 rounded w-3/4 mb-2" />
                <div className="h-4 bg-dark-700 rounded w-full" />
              </div>
            ))
          ) : sortedArticles.length === 0 ? (
            <div className="card text-center py-12 text-dark-400">
              <p>沒有找到文章</p>
              <p className="text-sm mt-1">試試點擊「抓取新聞」來收集新聞</p>
            </div>
          ) : (
            sortedArticles.map(article => {
              const sev = article.severity || assessSeverity(article.title, article.content)
              const isSelected = selectedDbIds.has(article.id)
              return (
                <div
                  key={article.id}
                  onClick={() => setSelectedArticle(article)}
                  className={`card-hover cursor-pointer ${
                    selectedArticle?.id === article.id ? 'border-primary-500/50 bg-primary-500/5' : ''
                  } ${isSelected ? 'ring-1 ring-primary-500/30' : ''}`}
                >
                  <div className="flex items-start gap-3">
                    {/* Checkbox for multi-select */}
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => handleToggleDbSelect(e, article.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="mt-1 rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500 shrink-0"
                    />
                    <SeverityBadge severity={sev} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                        {article.is_saved && (
                          <svg className="w-4 h-4 text-yellow-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
                          </svg>
                        )}
                        <span className="text-xs text-dark-500">{article.source}</span>
                        {article.matched_keyword && article.matched_keyword.split(/[,、]/).map(kw => kw.trim()).filter(Boolean).map(kw => (
                          <span key={kw} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-600/15 text-blue-400 border border-blue-500/20 whitespace-nowrap">
                            {kw}
                          </span>
                        ))}
                      </div>
                      <h4 className="font-medium text-sm text-gray-200 line-clamp-2">{article.title}</h4>
                    </div>
                    <span className="text-xs text-dark-500 whitespace-nowrap">
                      {article.published_at && new Date(article.published_at).toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })}
                    </span>
                  </div>
                </div>
              )
            })
          )}

          {/* Pagination */}
          {total > 0 && (
            <div className="flex items-center justify-center gap-3 pt-4 flex-wrap">
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                className="btn-secondary text-sm">上一頁</button>
              <span className="text-sm text-dark-400">
                第 {page + 1} / {Math.ceil(total / pageSize)} 頁
              </span>
              <button onClick={() => setPage(p => p + 1)}
                disabled={(page + 1) * pageSize >= total}
                className="btn-secondary text-sm">下一頁</button>
              <select
                value={pageSize}
                onChange={(e) => handlePageSizeChange(Number(e.target.value))}
                className="input text-xs py-1 w-28"
              >
                {[10, 20, 50, 100, 200].map(n => (
                  <option key={n} value={n}>每頁 {n} 篇</option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        {selectedArticle && (
          <div className="lg:col-span-2 card lg:sticky lg:top-24 max-h-[calc(100vh-8rem)] overflow-y-auto">
            {/* Mobile back button */}
            <button onClick={() => setSelectedArticle(null)}
              className="lg:hidden flex items-center gap-1 text-sm text-primary-400 mb-3">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              返回列表
            </button>
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h3 className="text-base md:text-lg font-bold text-gray-100">{selectedArticle.title}</h3>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-sm text-dark-400">{selectedArticle.source}</span>
                  {selectedArticle.published_at && (
                    <span className="text-sm text-dark-500">
                      {new Date(selectedArticle.published_at).toLocaleString('zh-TW')}
                    </span>
                  )}
                </div>
              </div>
              <button onClick={() => setSelectedArticle(null)}
                className="p-1 hover:bg-dark-700 rounded shrink-0">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap gap-2 mb-4 pb-4 border-b border-dark-700">
              <button onClick={() => handleToggleSave(selectedArticle)}
                className={`btn-secondary text-sm flex items-center gap-1.5 ${
                  selectedArticle.is_saved ? 'text-yellow-500' : ''
                }`}>
                <svg className="w-4 h-4" fill={selectedArticle.is_saved ? 'currentColor' : 'none'}
                  viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
                </svg>
                {selectedArticle.is_saved ? '已收藏' : '收藏'}
              </button>

              {selectedArticle.source_url && (
                <div className="flex items-center gap-1">
                  <a href={selectedArticle.source_url} target="_blank" rel="noopener noreferrer"
                    className="btn-secondary text-sm flex items-center gap-1.5">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                    原始來源
                  </a>
                  <button
                    onClick={() => handleCopyUrl(selectedArticle.source_url)}
                    className="btn-secondary text-sm p-2"
                    title="複製連結"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </button>
                </div>
              )}

              <button onClick={() => handleDelete(selectedArticle.id)}
                className="btn-danger text-sm ml-auto">
                刪除
              </button>
            </div>

            {/* Tags */}
            <div className="mb-4">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-dark-400">標籤：</span>
                {(selectedArticle.tags || []).map(tag => (
                  <span key={tag} className="badge bg-primary-600/10 text-primary-400 border border-primary-500/20">
                    {tag}
                  </span>
                ))}
                <TagInput onAdd={(tag) => handleAddTag(selectedArticle, tag)} />
              </div>
            </div>

            {/* Content */}
            {selectedArticle.summary && (
              <div className="mb-4 p-3 bg-primary-600/5 border border-primary-500/20 rounded-lg">
                <h4 className="text-sm font-semibold text-primary-400 mb-1">AI 摘要</h4>
                <p className="text-sm text-gray-300">{selectedArticle.summary}</p>
              </div>
            )}
            <div className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
              {selectedArticle.content || '（無內容）'}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function TagInput({ onAdd }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    if (value.trim()) {
      onAdd(value.trim())
      setValue('')
      setEditing(false)
    }
  }

  if (!editing) {
    return (
      <button onClick={() => setEditing(true)}
        className="text-xs text-dark-400 hover:text-primary-400 border border-dashed border-dark-600 rounded px-2 py-0.5">
        + 新增標籤
      </button>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="inline-flex">
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => { if (!value) setEditing(false) }}
        className="text-xs px-2 py-0.5 bg-dark-900 border border-dark-600 rounded w-20 text-gray-200"
        placeholder="標籤名稱"
      />
    </form>
  )
}
