import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { searchAPI } from '../services/api'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [context, setContext] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [hoursBack, setHoursBack] = useState(24)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [result, setResult] = useState(null)
  const [aiResult, setAiResult] = useState(null)
  const [error, setError] = useState(null)
  const [searchHistory, setSearchHistory] = useState([])

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)
    setAiResult(null)

    try {
      const { data } = await searchAPI.searchTopic({
        query: query.trim(),
        context: context.trim(),
        hours_back: hoursBack,
        include_ai_analysis: false,
      })
      setResult(data)
      setSearchHistory(prev => [
        { query: query.trim(), time: new Date().toLocaleTimeString('zh-TW') },
        ...prev.slice(0, 9),
      ])
    } catch (err) {
      setError(err.response?.data?.detail || '搜尋失敗，請稍後再試')
    }
    setLoading(false)
  }

  const handleAiAnalyze = async () => {
    if (!result) return
    setAnalyzing(true)
    try {
      const { data } = await searchAPI.analyzeTopic({
        query: result.query,
        context: context.trim(),
        articles: result.news_articles || [],
        exposure_summary: result.exposure_summary || '',
      })
      setAiResult(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'AI 分析失敗')
    }
    setAnalyzing(false)
  }

  const quickSearches = [
    '聯準會利率決議',
    '台股加權指數',
    '美國CPI通膨',
    '日本央行政策',
    '中國經濟數據',
    '原油價格走勢',
  ]

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Search Form */}
      <div className="card">
        <form onSubmit={handleSearch}>
          <div className="flex gap-3">
            <div className="relative flex-1">
              <svg className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-dark-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="輸入搜尋主題，例如：日本央行升息影響..."
                className="input pl-12 text-lg"
              />
            </div>
            <button type="submit" disabled={loading || !query.trim()} className="btn-primary px-8">
              {loading ? (
                <div className="flex items-center gap-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                  搜尋中
                </div>
              ) : '搜尋'}
            </button>
          </div>

          {/* Advanced Options */}
          <div className="mt-3">
            <button type="button" onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-sm text-dark-400 hover:text-primary-400 flex items-center gap-1">
              <svg className={`w-4 h-4 transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
              進階選項
            </button>
            {showAdvanced && (
              <div className="mt-3 grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-dark-400 mb-1">背景脈絡（選填）</label>
                  <textarea
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                    placeholder="提供額外脈絡，例如：我持有日圓空頭部位..."
                    className="input h-20 resize-none"
                  />
                </div>
                <div>
                  <label className="block text-sm text-dark-400 mb-1">搜尋時間範圍</label>
                  <select value={hoursBack} onChange={(e) => setHoursBack(Number(e.target.value))} className="input">
                    <option value={6}>近 6 小時</option>
                    <option value={12}>近 12 小時</option>
                    <option value={24}>近 24 小時</option>
                    <option value={48}>近 48 小時</option>
                    <option value={72}>近 3 天</option>
                    <option value={168}>近 7 天</option>
                  </select>
                </div>
              </div>
            )}
          </div>
        </form>

        {/* Quick Searches */}
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-dark-700">
          <span className="text-xs text-dark-500 py-1">快速搜尋：</span>
          {quickSearches.map(q => (
            <button key={q} onClick={() => { setQuery(q) }}
              className="text-xs px-3 py-1 rounded-full bg-dark-700 text-dark-300 hover:bg-primary-600/20 hover:text-primary-400 transition-colors">
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="card border-red-500/30 bg-red-500/5">
          <p className="text-red-400">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="card text-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500 mx-auto mb-4" />
          <p className="text-dark-300">正在搜尋多個來源...</p>
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="space-y-4">
          {/* News Articles */}
          {result.news_articles && result.news_articles.length > 0 && (
            <div className="card">
              <h4 className="font-semibold mb-3">
                相關新聞
                <span className="text-sm text-dark-400 font-normal ml-2">({result.news_articles.length} 篇)</span>
              </h4>
              <div className="space-y-3">
                {result.news_articles.map((article, i) => (
                  <div key={i} className="p-3 rounded-lg bg-dark-900 hover:bg-dark-800/50 transition-colors">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1">
                        <a href={article.source_url} target="_blank" rel="noopener noreferrer"
                          className="font-medium text-gray-200 hover:text-primary-400 transition-colors">
                          {article.title}
                        </a>
                        <p className="text-xs text-dark-400 mt-1">{article.source}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {article.published_at && (
                          <span className="text-xs text-dark-500 whitespace-nowrap">
                            {new Date(article.published_at).toLocaleDateString('zh-TW')}
                          </span>
                        )}
                        {article.source_url && (
                          <a href={article.source_url} target="_blank" rel="noopener noreferrer"
                            className="text-dark-400 hover:text-primary-400">
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                            </svg>
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Exposure Summary */}
          {result.matched_positions && result.matched_positions.length > 0 && (
            <div className="card border-yellow-500/20 bg-yellow-500/5">
              <h4 className="font-semibold text-yellow-400 mb-3 flex items-center gap-2">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
                </svg>
                可能影響的部位
              </h4>
              <div className="space-y-2">
                {result.matched_positions.map((pos, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-dark-800/50">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-sm text-primary-400">{pos.symbol}</span>
                      <span className="text-sm text-gray-300">{pos.name}</span>
                      {pos.category && (
                        <span className="text-xs px-2 py-0.5 rounded bg-dark-700 text-dark-300">{pos.category}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-sm text-dark-400">
                      {pos.quantity && <span>{pos.quantity}股</span>}
                      {pos.avg_cost && <span>均價{pos.avg_cost}</span>}
                      <span className="text-xs text-dark-500">
                        關聯：{pos.matched_keywords?.join(', ')}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI Analysis Button / Results - only show when there are articles */}
          {result.news_articles && result.news_articles.length > 0 && (aiResult ? (
            <div className="card border-primary-500/20">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 bg-primary-600/20 rounded-lg flex items-center justify-center">
                  <svg className="w-5 h-5 text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-bold text-primary-400">AI 深度分析</h3>
                  <p className="text-xs text-dark-400">
                    搜尋主題：{result.query} | {new Date(result.timestamp).toLocaleString('zh-TW')}
                  </p>
                </div>
              </div>
              <div className="markdown-content">
                <ReactMarkdown>{aiResult.ai_analysis}</ReactMarkdown>
              </div>

              {/* AI Sources */}
              {aiResult.ai_sources && aiResult.ai_sources.length > 0 && (
                <div className="mt-4 pt-4 border-t border-dark-700">
                  <h5 className="text-sm font-semibold text-dark-300 mb-2">AI 參考來源</h5>
                  <div className="space-y-1">
                    {aiResult.ai_sources.map((src, i) => (
                      <a key={i} href={src.url} target="_blank" rel="noopener noreferrer"
                        className="block text-xs text-primary-400 hover:underline truncate">
                        {src.title || src.url}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="card text-center py-6">
              <button
                onClick={handleAiAnalyze}
                disabled={analyzing}
                className="btn-primary px-8 py-3 text-base flex items-center gap-2 mx-auto"
              >
                {analyzing ? (
                  <>
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white" />
                    AI 分析中...（約 10-30 秒）
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                    </svg>
                    AI 深度分析
                  </>
                )}
              </button>
              <p className="text-xs text-dark-500 mt-2">包含事件影響評估、部位暴險分析、後續發展預測</p>
            </div>
          ))}

          {/* No results */}
          {result.news_articles && result.news_articles.length === 0 && (
            <div className="card text-center py-8 text-dark-400">
              <p>未找到相關新聞，請嘗試其他關鍵字</p>
            </div>
          )}
        </div>
      )}

      {/* Search History */}
      {searchHistory.length > 0 && !loading && !result && (
        <div className="card">
          <h4 className="font-semibold mb-3 text-dark-300">搜尋紀錄</h4>
          <div className="space-y-1">
            {searchHistory.map((item, i) => (
              <button key={i} onClick={() => setQuery(item.query)}
                className="flex items-center justify-between w-full p-2 rounded hover:bg-dark-800 text-sm text-dark-300 transition-colors">
                <span>{item.query}</span>
                <span className="text-xs text-dark-500">{item.time}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
