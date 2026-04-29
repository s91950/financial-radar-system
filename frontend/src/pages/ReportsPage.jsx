import { useCallback, useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import { reportsAPI, resolveUrl, copyToClipboard } from '../services/api'

const INSTITUTION_COLORS = {
  'IMF Working Papers': 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  'BIS Working Papers': 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  'Fed Working Papers (FEDS)': 'bg-green-500/15 text-green-400 border-green-500/25',
  'Fed IFDP Papers': 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  'ECB Working Papers': 'bg-yellow-500/15 text-yellow-400 border-yellow-500/25',
  'BOJ Research & Publications': 'bg-red-500/15 text-red-400 border-red-500/25',
  'BOE Publications': 'bg-orange-500/15 text-orange-400 border-orange-500/25',
  'NBER Working Papers': 'bg-teal-500/15 text-teal-400 border-teal-500/25',
}

function InstitutionBadge({ name }) {
  const cls = INSTITUTION_COLORS[name] || 'bg-dark-700 text-dark-300 border-dark-600'
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium whitespace-nowrap ${cls}`}>
      {name}
    </span>
  )
}

export default function ReportsPage() {
  const [reports, setReports] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [fetchLoading, setFetchLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [institutions, setInstitutions] = useState([])
  const [selectedReport, setSelectedReport] = useState(null)

  // Filters
  const [searchInput, setSearchInput] = useState('')
  const [filters, setFilters] = useState({ search: '', institution: '', date_from: '', date_to: '', saved_only: false })
  const [showDateFilter, setShowDateFilter] = useState(false)
  const [page, setPage] = useState(0)
  const pageSize = 30

  // Fetch / preview
  const [preview, setPreview] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())

  // Manual fetch options
  const [fetchHours, setFetchHours] = useState(72)
  const [fetchDateFrom, setFetchDateFrom] = useState('')
  const [fetchDateTo, setFetchDateTo] = useState('')
  const [fetchInstitutions, setFetchInstitutions] = useState(new Set()) // empty = all

  const loadInstitutions = useCallback(async () => {
    try {
      const { data } = await reportsAPI.getInstitutions()
      setInstitutions(data)
    } catch { /* silent */ }
  }, [])

  const loadReports = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await reportsAPI.getReports({
        limit: pageSize,
        offset: page * pageSize,
        ...filters,
      })
      setReports(data.reports)
      setTotal(data.total)
    } catch (err) {
      console.error(err)
    }
    setLoading(false)
  }, [page, filters])

  useEffect(() => { loadInstitutions() }, [loadInstitutions])
  useEffect(() => { loadReports() }, [loadReports])

  const handleFetch = async () => {
    setFetchLoading(true)
    setPreview(null)
    try {
      const payload = {
        hours_back: fetchHours === 'custom' ? 8760 : fetchHours,
        institutions: fetchInstitutions.size > 0 ? [...fetchInstitutions] : null,
        ...(fetchHours === 'custom' && fetchDateFrom ? { date_from: fetchDateFrom } : {}),
        ...(fetchHours === 'custom' && fetchDateTo ? { date_to: fetchDateTo } : {}),
      }
      const { data } = await reportsAPI.manualFetch(payload)
      setPreview(data.preview || [])
      // Auto-select items not already in db
      const newIds = new Set()
      ;(data.preview || []).forEach((r, i) => { if (!r.already_in_db) newIds.add(i) })
      setSelectedIds(newIds)
      toast.success(`取得 ${data.fetched} 篇報告，請選擇要儲存的`)
    } catch (err) {
      toast.error('抓取失敗：' + (err.response?.data?.detail || err.message))
    }
    setFetchLoading(false)
  }

  const handleSelectAll = () => {
    if (!preview) return
    setSelectedIds(new Set(preview.map((_, i) => i).filter(i => !preview[i].already_in_db)))
  }
  const handleDeselectAll = () => setSelectedIds(new Set())

  const handleTogglePreview = (idx) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const handleCopySelected = async () => {
    if (!preview || selectedIds.size === 0) return
    const urls = preview.filter((r, i) => selectedIds.has(i) && r.pdf_url).map(r => r.pdf_url)
    if (!urls.length) return
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
      const { data } = await reportsAPI.saveSelected({ reports: toSave })
      toast.success(`已儲存 ${data.saved} 篇研究報告`)
      setPreview(null)
      setSelectedIds(new Set())
      loadReports()
    } catch (err) {
      toast.error('儲存失敗')
    }
    setSaving(false)
  }

  const handleToggleSave = async (report) => {
    try {
      const { data } = await reportsAPI.updateReport(report.id, { is_saved: !report.is_saved })
      setReports(prev => prev.map(r => r.id === report.id ? { ...r, is_saved: data.is_saved } : r))
      if (selectedReport?.id === report.id) setSelectedReport({ ...selectedReport, is_saved: data.is_saved })
    } catch { /* silent */ }
  }

  const handleDelete = async (id) => {
    if (!confirm('確定刪除此報告？')) return
    try {
      await reportsAPI.deleteReport(id)
      setReports(prev => prev.filter(r => r.id !== id))
      if (selectedReport?.id === id) setSelectedReport(null)
    } catch { /* silent */ }
  }

  const handleCopyUrl = async (url) => {
    const final = await resolveUrl(url)
    copyToClipboard(final)
    toast.success('已複製連結')
  }

  const handleSearch = (e) => {
    e.preventDefault()
    setFilters(prev => ({ ...prev, search: searchInput }))
    setPage(0)
  }

  const toggleFetchInstitution = (name) => {
    setFetchInstitutions(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const newCount = preview ? preview.filter((_, i) => selectedIds.has(i)).length : 0

  return (
    <div className="space-y-5">
      {/* Preview Panel */}
      {preview && (
        <div className="card border-primary-500/20">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">
              搜尋結果預覽
              <span className="text-sm text-dark-400 font-normal ml-2">({preview.length} 篇)</span>
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

          <div className="space-y-1 max-h-80 overflow-y-auto">
            {preview.map((report, idx) => (
              <label key={idx} className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors ${
                report.already_in_db ? 'opacity-50' : selectedIds.has(idx) ? 'bg-primary-600/10' : 'hover:bg-dark-800'
              }`}>
                <input type="checkbox"
                  checked={selectedIds.has(idx)}
                  disabled={report.already_in_db}
                  onChange={() => handleTogglePreview(idx)}
                  className="rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500"
                />
                <div className="flex-1 min-w-0">
                  <span className="text-sm text-gray-200 line-clamp-1">{report.title}</span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <InstitutionBadge name={report.source} />
                    {report.publication_date && (
                      <span className="text-xs text-dark-500">
                        {new Date(report.publication_date).toLocaleDateString('zh-TW')}
                      </span>
                    )}
                  </div>
                </div>
                {report.already_in_db && <span className="text-xs text-dark-500 shrink-0">已存在</span>}
                {report.pdf_url && (
                  <a href={report.pdf_url} target="_blank" rel="noopener noreferrer"
                    className="text-dark-400 hover:text-primary-400 shrink-0"
                    onClick={(e) => e.stopPropagation()}>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                  </a>
                )}
              </label>
            ))}
          </div>

          <div className="flex items-center justify-end gap-3 mt-4 pt-4 border-t border-dark-700">
            <button onClick={() => { setPreview(null); setSelectedIds(new Set()) }} className="btn-secondary text-sm">
              取消
            </button>
            <button onClick={handleSaveSelected} disabled={saving || newCount === 0} className="btn-primary text-sm flex items-center gap-2">
              {saving && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />}
              儲存選取 ({newCount})
            </button>
          </div>
        </div>
      )}

      {/* Action Bar */}
      <div className="card space-y-3">
        {/* Top row: fetch button + hours */}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleFetch}
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
            {fetchLoading ? '搜尋中...' : '搜尋報告'}
          </button>

          <select value={fetchHours} onChange={(e) => setFetchHours(e.target.value === 'custom' ? 'custom' : Number(e.target.value))} className="input text-sm w-28">
            <option value={24}>近 24 小時</option>
            <option value={48}>近 48 小時</option>
            <option value={72}>近 3 天</option>
            <option value={168}>近 7 天</option>
            <option value={720}>近 30 天</option>
            <option value="custom">自選範圍</option>
          </select>

          {fetchHours === 'custom' && (
            <div className="flex items-center gap-2">
              <input type="date" value={fetchDateFrom} onChange={(e) => setFetchDateFrom(e.target.value)}
                className="input text-sm py-1.5 w-36" placeholder="開始日期" />
              <span className="text-xs text-dark-500">至</span>
              <input type="date" value={fetchDateTo} onChange={(e) => setFetchDateTo(e.target.value)}
                className="input text-sm py-1.5 w-36" placeholder="結束日期" />
            </div>
          )}

          <div className="flex-1" />

          <button
            onClick={() => setFilters(prev => ({ ...prev, saved_only: !prev.saved_only }))}
            className={`btn-secondary flex items-center gap-1.5 ${filters.saved_only ? 'bg-primary-600/20 text-primary-400 border-primary-500/30' : ''}`}
          >
            <svg className="w-4 h-4" fill={filters.saved_only ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
            </svg>
            已收藏
          </button>
          <span className="text-sm text-dark-400">{total} 篇報告</span>
        </div>

        {/* Institution chips */}
        {institutions.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-dark-500 shrink-0">機構：</span>
            {institutions.map(inst => (
              <button
                key={inst.name}
                onClick={() => toggleFetchInstitution(inst.name)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  fetchInstitutions.has(inst.name)
                    ? 'bg-primary-600/20 text-primary-400 border-primary-500/30'
                    : 'bg-dark-800 text-dark-400 border-dark-600 hover:text-gray-300'
                }`}
              >
                {inst.name}
              </button>
            ))}
            {fetchInstitutions.size > 0 && (
              <button onClick={() => setFetchInstitutions(new Set())}
                className="text-xs text-dark-500 hover:text-red-400">
                × 全部
              </button>
            )}
            <span className="text-xs text-dark-600 ml-1">
              {fetchInstitutions.size === 0 ? '（全部機構）' : `（已選 ${fetchInstitutions.size} 個）`}
            </span>
          </div>
        )}
      </div>

      {/* Filter bar */}
      <div className="space-y-2">
        <div className="flex flex-wrap gap-3">
          <form onSubmit={handleSearch} className="flex gap-2 flex-1">
            <input type="text" value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
              placeholder="搜尋報告標題或摘要..."
              className="input" />
            <button type="button"
              onClick={() => setShowDateFilter(v => !v)}
              className={`btn-secondary flex items-center gap-1.5 shrink-0 ${
                showDateFilter || filters.date_from || filters.date_to
                  ? 'bg-primary-600/20 text-primary-400 border-primary-500/30' : ''
              }`}>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
              日期
              {(filters.date_from || filters.date_to) && <span className="w-1.5 h-1.5 rounded-full bg-primary-400" />}
            </button>
            <button type="submit" className="btn-secondary">篩選</button>
            {(filters.search || filters.date_from || filters.date_to) && (
              <button type="button" onClick={() => {
                setSearchInput('')
                setFilters(prev => ({ ...prev, search: '', date_from: '', date_to: '' }))
                setPage(0)
              }} className="btn-secondary text-red-400">清除</button>
            )}
          </form>

          {/* Institution filter (saved reports list) */}
          <select
            value={filters.institution}
            onChange={(e) => { setFilters(prev => ({ ...prev, institution: e.target.value })); setPage(0) }}
            className="input text-sm w-40"
          >
            <option value="">全部機構</option>
            {institutions.map(inst => <option key={inst.name} value={inst.name}>{inst.name}</option>)}
          </select>
        </div>

        {showDateFilter && (
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-dark-800/60 border border-dark-700">
            <span className="text-xs text-dark-400 shrink-0">發布日期</span>
            <input type="date" value={filters.date_from}
              onChange={(e) => { setFilters(prev => ({ ...prev, date_from: e.target.value })); setPage(0) }}
              className="input text-sm py-1.5 w-36" />
            <span className="text-xs text-dark-500">至</span>
            <input type="date" value={filters.date_to}
              onChange={(e) => { setFilters(prev => ({ ...prev, date_to: e.target.value })); setPage(0) }}
              className="input text-sm py-1.5 w-36" />
            {(filters.date_from || filters.date_to) && (
              <button onClick={() => { setFilters(prev => ({ ...prev, date_from: '', date_to: '' })); setPage(0) }}
                className="text-xs text-dark-500 hover:text-red-400 transition-colors">
                × 清除日期
              </button>
            )}
          </div>
        )}
      </div>

      {/* Reports list + detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-6">
        <div className={`space-y-2 ${selectedReport ? 'hidden lg:block lg:col-span-1' : 'lg:col-span-3'}`}>
          {loading ? (
            Array(5).fill(0).map((_, i) => (
              <div key={i} className="card animate-pulse">
                <div className="h-4 bg-dark-700 rounded w-3/4 mb-2" />
                <div className="h-3 bg-dark-700 rounded w-full" />
              </div>
            ))
          ) : reports.length === 0 ? (
            <div className="card text-center py-12 text-dark-400">
              <svg className="w-12 h-12 mx-auto mb-3 text-dark-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              <p>尚無報告</p>
              <p className="text-sm mt-1">點擊「搜尋報告」抓取最新研究報告</p>
            </div>
          ) : (
            reports.map(report => (
              <div key={report.id} onClick={() => setSelectedReport(report)}
                className={`card-hover cursor-pointer ${selectedReport?.id === report.id ? 'border-primary-500/50 bg-primary-500/5' : ''}`}>
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      {report.is_saved && (
                        <svg className="w-3.5 h-3.5 text-yellow-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
                        </svg>
                      )}
                      <InstitutionBadge name={report.source} />
                      {report.authors?.length > 0 && (
                        <span className="text-xs text-dark-500 truncate max-w-32">
                          {report.authors.slice(0, 2).join(', ')}{report.authors.length > 2 ? '...' : ''}
                        </span>
                      )}
                    </div>
                    <h4 className="font-medium text-sm text-gray-200 line-clamp-2">{report.title}</h4>
                    {report.abstract && (
                      <p className="text-xs text-dark-500 mt-1 line-clamp-2">{report.abstract}</p>
                    )}
                  </div>
                  <span className="text-xs text-dark-500 whitespace-nowrap shrink-0">
                    {report.publication_date
                      ? new Date(report.publication_date).toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })
                      : new Date(report.fetched_at).toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })
                    }
                  </span>
                </div>
              </div>
            ))
          )}

          {total > pageSize && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="btn-secondary text-sm">上一頁</button>
              <span className="text-sm text-dark-400">第 {page + 1} / {Math.ceil(total / pageSize)} 頁</span>
              <button onClick={() => setPage(p => p + 1)} disabled={(page + 1) * pageSize >= total} className="btn-secondary text-sm">下一頁</button>
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selectedReport && (
          <div className="lg:col-span-2 card lg:sticky lg:top-24 max-h-[calc(100vh-8rem)] overflow-y-auto">
            {/* Mobile back button */}
            <button onClick={() => setSelectedReport(null)}
              className="lg:hidden flex items-center gap-1 text-sm text-primary-400 mb-3">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              返回列表
            </button>
            <div className="flex items-start justify-between gap-3 mb-4">
              <div className="flex-1 min-w-0">
                <InstitutionBadge name={selectedReport.source} />
                <h3 className="text-base md:text-lg font-bold text-gray-100 mt-2">{selectedReport.title}</h3>
                <div className="flex items-center gap-3 mt-1 flex-wrap">
                  {selectedReport.authors?.length > 0 && (
                    <span className="text-sm text-dark-400">{selectedReport.authors.join(', ')}</span>
                  )}
                  {selectedReport.publication_date && (
                    <span className="text-sm text-dark-500">
                      {new Date(selectedReport.publication_date).toLocaleDateString('zh-TW', { year: 'numeric', month: 'long', day: 'numeric' })}
                    </span>
                  )}
                </div>
              </div>
              <button onClick={() => setSelectedReport(null)} className="p-1 hover:bg-dark-700 rounded shrink-0">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap gap-2 mb-4 pb-4 border-b border-dark-700">
              <button onClick={() => handleToggleSave(selectedReport)}
                className={`btn-secondary text-sm flex items-center gap-1.5 ${selectedReport.is_saved ? 'text-yellow-500' : ''}`}>
                <svg className="w-4 h-4" fill={selectedReport.is_saved ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
                </svg>
                {selectedReport.is_saved ? '已收藏' : '收藏'}
              </button>

              {selectedReport.pdf_url && (
                <div className="flex items-center gap-1">
                  <a href={selectedReport.pdf_url} target="_blank" rel="noopener noreferrer"
                    className="btn-secondary text-sm flex items-center gap-1.5">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                    開啟報告
                  </a>
                  <button onClick={() => handleCopyUrl(selectedReport.pdf_url)}
                    className="btn-secondary text-sm p-2" title="複製連結">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </button>
                </div>
              )}

              {selectedReport.source_url && selectedReport.source_url !== selectedReport.pdf_url && (
                <a href={selectedReport.source_url} target="_blank" rel="noopener noreferrer"
                  className="btn-secondary text-sm flex items-center gap-1.5 text-dark-400">
                  報告頁面
                </a>
              )}

              <button onClick={() => handleDelete(selectedReport.id)} className="btn-danger text-sm ml-auto">刪除</button>
            </div>

            {/* Abstract */}
            {selectedReport.abstract ? (
              <div>
                <h4 className="text-sm font-semibold text-dark-300 mb-2">摘要</h4>
                <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{selectedReport.abstract}</p>
              </div>
            ) : (
              <p className="text-sm text-dark-500">（無摘要）</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
