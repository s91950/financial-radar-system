import { useCallback, useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import { newsAPI } from '../services/api'

const SENTIMENT_COLORS = {
  positive: { bg: 'bg-green-500', text: 'text-green-400', label: '正面' },
  neutral: { bg: 'bg-yellow-500', text: 'text-yellow-400', label: '中性' },
  negative: { bg: 'bg-red-500', text: 'text-red-400', label: '偏負' },
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
    search: '',
  })
  const [searchInput, setSearchInput] = useState('')
  const [customQuery, setCustomQuery] = useState('')
  const [page, setPage] = useState(0)
  const pageSize = 20

  // Preview state
  const [preview, setPreview] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [saving, setSaving] = useState(false)

  // Sentiment state
  const [sentiment, setSentiment] = useState(null)

  const loadArticles = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await newsAPI.getArticles({
        limit: pageSize,
        offset: page * pageSize,
        ...filters,
      })
      setArticles(data.articles)
      setTotal(data.total)
    } catch (err) {
      console.error('Failed to load articles:', err)
    }
    setLoading(false)
  }, [page, filters])

  const loadSentiment = useCallback(async () => {
    try {
      const { data } = await newsAPI.getSentiment()
      setSentiment(data)
    } catch (err) {
      console.error('Failed to load sentiment:', err)
    }
  }, [])

  useEffect(() => {
    loadArticles()
    loadSentiment()
  }, [loadArticles, loadSentiment])

  const handleManualFetch = async (query = null) => {
    setFetchLoading(true)
    setPreview(null)
    try {
      const { data } = await newsAPI.manualFetch({
        query: query || null,
        hours_back: 24,
      })
      // Show preview instead of auto-saving
      setPreview(data.preview || [])
      // Pre-select all new articles
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

  const handleCustomSearch = (e) => {
    e.preventDefault()
    if (customQuery.trim()) {
      handleManualFetch(customQuery.trim())
      setCustomQuery('')
    }
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
    preview.forEach((a, i) => {
      if (!a.already_in_db) allNew.add(i)
    })
    setSelectedIds(allNew)
  }

  const handleDeselectAll = () => {
    setSelectedIds(new Set())
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
      loadSentiment()
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

  const newCount = preview ? preview.filter((_, i) => selectedIds.has(i)).length : 0

  return (
    <div className="space-y-6">
      {/* Sentiment Dashboard */}
      {sentiment && sentiment.categories && sentiment.categories.length > 0 && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold flex items-center gap-2">
              <svg className="w-5 h-5 text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
              </svg>
              今日市場熱度
              <span className="text-xs text-dark-400 font-normal">{sentiment.date} ({sentiment.total_articles} 則)</span>
            </h3>
            <button onClick={loadSentiment} className="text-xs text-dark-400 hover:text-primary-400">
              重新整理
            </button>
          </div>
          <div className="space-y-3">
            {sentiment.categories.map((cat) => {
              const colors = SENTIMENT_COLORS[cat.sentiment_label] || SENTIMENT_COLORS.neutral
              return (
                <div key={cat.category} className="flex items-center gap-3">
                  <span className="text-sm w-16 text-dark-300">{cat.label}</span>
                  <div className="flex-1 h-5 bg-dark-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${colors.bg} rounded-full transition-all duration-500`}
                      style={{ width: `${Math.max(cat.heat, 3)}%` }}
                    />
                  </div>
                  <span className="text-xs w-8 text-right text-dark-400">{cat.heat}</span>
                  <span className={`text-xs w-10 text-center ${colors.text}`}>{colors.label}</span>
                  <span className="text-xs text-dark-500 w-12 text-right">({cat.article_count}則)</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Preview Panel (shown after fetch) */}
      {preview && (
        <div className="card border-primary-500/20">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">
              搜尋結果預覽
              <span className="text-sm text-dark-400 font-normal ml-2">({preview.length} 則)</span>
            </h3>
            <div className="flex items-center gap-2">
              <button onClick={handleSelectAll} className="text-xs text-primary-400 hover:underline">全選</button>
              <button onClick={handleDeselectAll} className="text-xs text-dark-400 hover:underline">取消全選</button>
            </div>
          </div>
          <div className="space-y-1 max-h-80 overflow-y-auto">
            {preview.map((article, idx) => (
              <label
                key={idx}
                className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors ${
                  article.already_in_db
                    ? 'opacity-50'
                    : selectedIds.has(idx)
                    ? 'bg-primary-600/10'
                    : 'hover:bg-dark-800'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedIds.has(idx)}
                  disabled={article.already_in_db}
                  onChange={() => handleTogglePreviewItem(idx)}
                  className="rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500"
                />
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
            ))}
          </div>
          <div className="flex items-center justify-end gap-3 mt-4 pt-4 border-t border-dark-700">
            <button onClick={() => { setPreview(null); setSelectedIds(new Set()) }}
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
        <button
          onClick={() => handleManualFetch()}
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
          抓取新聞 (24hr)
        </button>

        <form onSubmit={handleCustomSearch} className="flex gap-2">
          <input
            type="text"
            value={customQuery}
            onChange={(e) => setCustomQuery(e.target.value)}
            placeholder="自訂搜尋主題..."
            className="input w-56"
          />
          <button type="submit" disabled={fetchLoading || !customQuery.trim()} className="btn-secondary">
            搜尋抓取
          </button>
        </form>

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

        <span className="text-sm text-dark-400">{total} 篇文章</span>
      </div>

      {/* Filter / Search */}
      <div className="flex gap-3">
        <form onSubmit={handleSearch} className="flex gap-2 flex-1">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜尋資料庫中的文章..."
            className="input"
          />
          <button type="submit" className="btn-secondary">篩選</button>
          {filters.search && (
            <button type="button" onClick={() => { setSearchInput(''); setFilters(prev => ({ ...prev, search: '' })); }}
              className="btn-secondary text-red-400">清除</button>
          )}
        </form>
      </div>

      {/* Articles List */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* List */}
        <div className={`space-y-2 ${selectedArticle ? 'lg:col-span-1' : 'lg:col-span-3'}`}>
          {loading ? (
            Array(5).fill(0).map((_, i) => (
              <div key={i} className="card animate-pulse">
                <div className="h-5 bg-dark-700 rounded w-3/4 mb-2" />
                <div className="h-4 bg-dark-700 rounded w-full" />
              </div>
            ))
          ) : articles.length === 0 ? (
            <div className="card text-center py-12 text-dark-400">
              <p>沒有找到文章</p>
              <p className="text-sm mt-1">試試點擊「抓取新聞」來收集新聞</p>
            </div>
          ) : (
            articles.map(article => (
              <div
                key={article.id}
                onClick={() => setSelectedArticle(article)}
                className={`card-hover cursor-pointer ${
                  selectedArticle?.id === article.id ? 'border-primary-500/50 bg-primary-500/5' : ''
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {article.is_saved && (
                        <svg className="w-4 h-4 text-yellow-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
                        </svg>
                      )}
                      <span className="text-xs text-dark-500">{article.source}</span>
                      {article.category && (
                        <span className="badge bg-dark-700 text-dark-300">{article.category}</span>
                      )}
                    </div>
                    <h4 className="font-medium text-sm text-gray-200 line-clamp-2">{article.title}</h4>
                    {article.tags && article.tags.length > 0 && (
                      <div className="flex gap-1 mt-1.5">
                        {article.tags.map(tag => (
                          <span key={tag} className="text-xs px-1.5 py-0.5 rounded bg-primary-600/10 text-primary-400">
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <span className="text-xs text-dark-500 whitespace-nowrap">
                    {article.published_at && new Date(article.published_at).toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })}
                  </span>
                </div>
              </div>
            ))
          )}

          {/* Pagination */}
          {total > pageSize && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                className="btn-secondary text-sm">上一頁</button>
              <span className="text-sm text-dark-400">
                第 {page + 1} / {Math.ceil(total / pageSize)} 頁
              </span>
              <button onClick={() => setPage(p => p + 1)}
                disabled={(page + 1) * pageSize >= total}
                className="btn-secondary text-sm">下一頁</button>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        {selectedArticle && (
          <div className="lg:col-span-2 card sticky top-24 max-h-[calc(100vh-8rem)] overflow-y-auto">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h3 className="text-lg font-bold text-gray-100">{selectedArticle.title}</h3>
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
            <div className="flex gap-2 mb-4 pb-4 border-b border-dark-700">
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
                <a href={selectedArticle.source_url} target="_blank" rel="noopener noreferrer"
                  className="btn-secondary text-sm flex items-center gap-1.5">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                  原始來源
                </a>
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
