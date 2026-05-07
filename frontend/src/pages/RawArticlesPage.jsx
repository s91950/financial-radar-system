import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'react-hot-toast'
import { rawArticlesAPI } from '../services/api'

const TYPE_LABELS = {
  rss: 'RSS',
  social: 'Social',
  website: '網站爬蟲',
  mops: 'MOPS',
  gn: 'Google News',
}

const TYPE_COLORS = {
  rss: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  social: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  website: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  mops: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  gn: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
}

const PAGE_SIZE = 50

export default function RawArticlesPage() {
  const [stats, setStats] = useState(null)
  const [articles, setArticles] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(0)

  // Filters
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [sourceType, setSourceType] = useState('')
  const [source, setSource] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')   // all | passed | not_passed
  const [hoursBack, setHoursBack] = useState('')            // '' = 全部

  const loadStats = useCallback(async () => {
    try {
      const { data } = await rawArticlesAPI.stats()
      setStats(data)
    } catch { /* ignore */ }
  }, [])

  const loadArticles = useCallback(async () => {
    setLoading(true)
    try {
      const params = {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }
      if (search) params.search = search
      if (sourceType) params.source_type = sourceType
      if (source) params.source = source
      if (filterStatus !== 'all') params.filter_status = filterStatus
      if (hoursBack) params.hours_back = Number(hoursBack)
      const { data } = await rawArticlesAPI.list(params)
      setArticles(data.articles || [])
      setTotal(data.total || 0)
    } catch {
      toast.error('載入失敗')
    }
    setLoading(false)
  }, [page, search, sourceType, source, filterStatus, hoursBack])

  useEffect(() => { loadStats() }, [loadStats])
  useEffect(() => { loadArticles() }, [loadArticles])

  const handleSearch = (e) => {
    e?.preventDefault?.()
    setPage(0)
    setSearch(searchInput.trim())
  }

  const clearFilters = () => {
    setSearch(''); setSearchInput('')
    setSourceType(''); setSource('')
    setFilterStatus('all'); setHoursBack('')
    setPage(0)
  }

  const handleDelete = async (id) => {
    try {
      await rawArticlesAPI.delete(id)
      setArticles(prev => prev.filter(a => a.id !== id))
      setTotal(t => Math.max(0, t - 1))
      loadStats()
    } catch {
      toast.error('刪除失敗')
    }
  }

  const handleManualCleanup = async () => {
    if (!confirm('確定要刪除超過 7 天的篩選前資料嗎？')) return
    try {
      const { data } = await rawArticlesAPI.cleanup(7)
      toast.success(`已刪除 ${data.deleted} 筆`)
      loadStats()
      loadArticles()
    } catch {
      toast.error('清理失敗')
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const showingRange = useMemo(() => {
    if (total === 0) return '0'
    const from = page * PAGE_SIZE + 1
    const to = Math.min(total, (page + 1) * PAGE_SIZE)
    return `${from}-${to} / ${total}`
  }, [page, total])

  return (
    <div className="space-y-4">
      {/* 總覽卡 */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="總筆數" value={stats.total.toLocaleString()} hint="近 7 天滾動" />
          <StatCard label="進入雷達" value={stats.passed.toLocaleString()} hint={`${stats.total > 0 ? Math.round(stats.passed / stats.total * 100) : 0}%`} accent="text-emerald-400" />
          <StatCard label="被篩掉" value={stats.not_passed.toLocaleString()} hint={`${stats.total > 0 ? Math.round(stats.not_passed / stats.total * 100) : 0}%`} accent="text-amber-400" />
          <StatCard label="最新抓取" value={stats.newest_fetched_at ? new Date(stats.newest_fetched_at).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'} hint="UTC→本地" />
        </div>
      )}

      {/* 來源類型分布 */}
      {stats?.by_source_type && Object.keys(stats.by_source_type).length > 0 && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-200">來源類型分布</h3>
            <button onClick={handleManualCleanup} className="btn-secondary text-xs">
              手動清理（7 天前）
            </button>
          </div>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(stats.by_source_type).map(([type, count]) => (
              <div key={type || 'unknown'} className={`px-3 py-1.5 rounded-lg text-xs border ${TYPE_COLORS[type] || 'bg-dark-700 text-dark-300 border-dark-600'}`}>
                {TYPE_LABELS[type] || type || '未知'} <span className="ml-1 font-semibold">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 搜尋 + 篩選 */}
      <div className="card space-y-3">
        <form onSubmit={handleSearch} className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜尋標題或摘要（支援整段標題容錯比對）"
            className="input flex-1 min-w-[240px]"
          />
          <button type="submit" className="btn-primary text-sm">搜尋</button>
          {(search || sourceType || source || filterStatus !== 'all' || hoursBack) && (
            <button type="button" onClick={clearFilters} className="btn-secondary text-sm">清除篩選</button>
          )}
        </form>

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <select value={sourceType} onChange={(e) => { setSourceType(e.target.value); setPage(0) }} className="input w-32">
            <option value="">所有類型</option>
            <option value="rss">RSS</option>
            <option value="social">Social</option>
            <option value="website">網站爬蟲</option>
            <option value="mops">MOPS</option>
            <option value="gn">Google News</option>
          </select>

          <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(0) }} className="input w-36">
            <option value="all">全部</option>
            <option value="passed">已進雷達</option>
            <option value="not_passed">被篩掉</option>
          </select>

          <select value={hoursBack} onChange={(e) => { setHoursBack(e.target.value); setPage(0) }} className="input w-32">
            <option value="">全部 7 天</option>
            <option value="1">近 1 小時</option>
            <option value="6">近 6 小時</option>
            <option value="24">近 24 小時</option>
            <option value="72">近 3 天</option>
          </select>

          <input
            type="text"
            value={source}
            onChange={(e) => { setSource(e.target.value); setPage(0) }}
            placeholder="來源名稱（可選）"
            className="input w-40"
          />
        </div>
      </div>

      {/* 列表 */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-200">
            篩選前資料 <span className="text-dark-500 font-normal text-xs ml-2">{showingRange}</span>
          </h3>
          <div className="text-xs text-dark-500">
            滾動視窗 7 天 · 每天凌晨 04:15 自動清理
          </div>
        </div>

        {loading ? (
          <div className="text-center py-12 text-dark-500">載入中…</div>
        ) : articles.length === 0 ? (
          <div className="text-center py-12 text-dark-500">沒有符合條件的資料</div>
        ) : (
          <div className="space-y-2">
            {articles.map(a => (
              <div key={a.id} className="p-3 rounded-lg bg-dark-800/50 border border-dark-700 group hover:border-dark-600 transition-colors">
                <div className="flex flex-wrap items-center gap-2 mb-1.5">
                  {a.source_type && (
                    <span className={`px-2 py-0.5 rounded text-[10px] border ${TYPE_COLORS[a.source_type] || 'bg-dark-700 text-dark-300 border-dark-600'}`}>
                      {TYPE_LABELS[a.source_type] || a.source_type}
                    </span>
                  )}
                  {a.filter_status === 'passed' ? (
                    <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                      ✓ 已進雷達
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-[10px] bg-dark-700 text-dark-400 border border-dark-600">
                      被篩掉
                    </span>
                  )}
                  {a.source && <span className="text-xs text-dark-400">[{a.source}]</span>}
                  {a.matched_keyword && (
                    <span className="text-[10px] px-2 py-0.5 rounded bg-primary-600/15 text-primary-300 border border-primary-500/20">
                      {a.matched_keyword}
                    </span>
                  )}
                  <span className="text-xs text-dark-500 ml-auto">
                    {a.fetched_at && new Date(a.fetched_at).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </span>
                  <button
                    onClick={() => handleDelete(a.id)}
                    className="text-dark-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                    title="刪除"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <a
                  href={a.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-sm text-gray-200 hover:text-primary-400 transition-colors leading-snug"
                >
                  {a.title}
                </a>
                {a.summary && (
                  <p className="text-xs text-dark-400 mt-1 line-clamp-2 leading-relaxed">{a.summary}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 分頁 */}
        {!loading && total > PAGE_SIZE && !search && (
          <div className="flex items-center justify-center gap-3 mt-4 text-sm">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="btn-secondary text-xs disabled:opacity-40"
            >
              上一頁
            </button>
            <span className="text-dark-400">{page + 1} / {totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="btn-secondary text-xs disabled:opacity-40"
            >
              下一頁
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value, hint, accent = 'text-gray-100' }) {
  return (
    <div className="card !p-3">
      <div className="text-xs text-dark-500 mb-1">{label}</div>
      <div className={`text-xl font-semibold ${accent}`}>{value}</div>
      {hint && <div className="text-[10px] text-dark-500 mt-0.5">{hint}</div>}
    </div>
  )
}
