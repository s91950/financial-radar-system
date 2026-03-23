import { useCallback, useEffect, useState } from 'react'
import { radarAPI } from '../services/api'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import ReactMarkdown from 'react-markdown'
import CategoryTabs from '../components/Radar/CategoryTabs'
import MarketIndicatorCard from '../components/Radar/MarketIndicatorCard'
import SignalConditionModal from '../components/Radar/SignalConditionModal'

export default function RadarPage({ wsSubscribe }) {
  const [alerts, setAlerts] = useState([])
  const [marketData, setMarketData] = useState({})
  const [categories, setCategories] = useState([])
  const [activeCategory, setActiveCategory] = useState('bond')
  const [sparklines, setSparklines] = useState({})
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [chartData, setChartData] = useState([])
  const [conditionItem, setConditionItem] = useState(null)
  const [analyzingId, setAnalyzingId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [marketLoading, setMarketLoading] = useState(true)

  const loadAlerts = useCallback(async () => {
    try {
      const { data } = await radarAPI.getAlerts({ limit: 30 })
      setAlerts(data)
    } catch (err) {
      console.error('Failed to load alerts:', err)
    }
    setLoading(false)
  }, [])

  const loadMarketData = useCallback(async () => {
    try {
      const [mktRes, catRes] = await Promise.all([
        radarAPI.getMarketData(),
        radarAPI.getMarketCategories(),
      ])
      setMarketData(mktRes.data)
      setCategories(catRes.data)
    } catch (err) {
      console.error('Failed to load market data:', err)
    }
    setMarketLoading(false)
  }, [])

  // Load sparkline data for all symbols
  const loadSparklines = useCallback(async (grouped) => {
    const allItems = Object.values(grouped).flat()
    const results = {}
    // Load in batches of 5 to avoid hammering the API
    for (let i = 0; i < allItems.length; i += 5) {
      const batch = allItems.slice(i, i + 5)
      const promises = batch.map(async (item) => {
        try {
          const { data } = await radarAPI.getMarketHistory(item.symbol, '5d', '1d')
          results[item.symbol] = data.map(d => ({ close: d.close }))
        } catch {
          results[item.symbol] = []
        }
      })
      await Promise.all(promises)
    }
    setSparklines(results)
  }, [])

  const loadChart = useCallback(async (symbol) => {
    setSelectedSymbol(symbol)
    try {
      const { data } = await radarAPI.getMarketHistory(symbol, '5d', '1h')
      setChartData(data.map(d => ({
        time: new Date(d.time).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
        price: d.close,
      })))
    } catch (err) {
      console.error('Failed to load chart:', err)
    }
  }, [])

  useEffect(() => {
    loadAlerts()
    loadMarketData()
    const interval = setInterval(() => { loadMarketData() }, 3600000)
    return () => clearInterval(interval)
  }, [loadAlerts, loadMarketData])

  // Load sparklines once market data arrives
  useEffect(() => {
    if (Object.keys(marketData).length > 0) {
      loadSparklines(marketData)
    }
  }, [marketData, loadSparklines])

  // Subscribe to real-time alerts
  useEffect(() => {
    if (!wsSubscribe) return
    const unsub = wsSubscribe('radar_alert', () => { loadAlerts() })
    const unsub2 = wsSubscribe('market_alert', () => { loadAlerts(); loadMarketData() })
    return () => { unsub(); unsub2() }
  }, [wsSubscribe, loadAlerts, loadMarketData])

  const handleMarkRead = async (alert) => {
    try {
      await radarAPI.markRead(alert.id)
      setAlerts(prev => prev.map(a => a.id === alert.id ? { ...a, is_read: true } : a))
    } catch (err) {
      console.error(err)
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

  // Filter items by category
  const displayItems = activeCategory === 'all'
    ? Object.values(marketData).flat()
    : marketData[activeCategory] || []

  // Find item name for chart title
  const allItems = Object.values(marketData).flat()
  const chartItemName = allItems.find(m => m.symbol === selectedSymbol)?.name

  const severityBadge = (severity) => {
    const cls = {
      critical: 'badge-critical',
      high: 'badge-high',
      medium: 'badge-medium',
      low: 'badge-low',
    }
    return <span className={cls[severity] || 'badge'}>{severity}</span>
  }

  return (
    <div className="space-y-6">
      {/* Market Indicators */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">市場指標</h3>
          <button onClick={loadMarketData} className="btn-secondary text-sm flex items-center gap-1.5">
            <svg className={`w-4 h-4 ${marketLoading ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
            </svg>
            更新
          </button>
        </div>

        {/* Category Tabs */}
        {categories.length > 0 && (
          <div className="mb-4">
            <CategoryTabs
              categories={categories}
              activeCategory={activeCategory}
              onSelect={setActiveCategory}
            />
          </div>
        )}

        {/* Indicator Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {marketLoading && displayItems.length === 0 ? (
            Array(8).fill(0).map((_, i) => (
              <div key={i} className="card animate-pulse">
                <div className="h-4 bg-dark-700 rounded w-2/3 mb-2" />
                <div className="h-8 bg-dark-700 rounded w-1/2 mb-2" />
                <div className="h-10 bg-dark-700 rounded w-full" />
              </div>
            ))
          ) : displayItems.length === 0 ? (
            <div className="col-span-full text-center text-dark-400 py-8">
              此分類尚無指標
            </div>
          ) : (
            displayItems.map((item) => (
              <MarketIndicatorCard
                key={item.symbol}
                item={item}
                sparkData={sparklines[item.symbol]}
                isSelected={selectedSymbol === item.symbol}
                onClick={() => loadChart(item.symbol)}
                onSettingsClick={(item) => setConditionItem(item)}
              />
            ))
          )}
        </div>
      </section>

      {/* Chart */}
      {selectedSymbol && chartData.length > 0 && (
        <section className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">
              {chartItemName} 走勢圖
            </h3>
            <button onClick={() => { setSelectedSymbol(null); setChartData([]) }}
              className="text-dark-400 hover:text-white">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" tick={{ fontSize: 11, fill: '#64748b' }} interval="preserveStartEnd" />
              <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11, fill: '#64748b' }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#f1f5f9' }}
              />
              <Area type="monotone" dataKey="price" stroke="#3b82f6" fill="url(#colorPrice)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* Alerts Feed */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">信號動態</h3>
          <span className="text-sm text-dark-400">{alerts.length} 則信號</span>
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
          ) : alerts.length === 0 ? (
            <div className="card text-center py-12 text-dark-400">
              <svg className="w-16 h-16 mx-auto mb-4 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9.348 14.651a3.75 3.75 0 010-5.303m5.304 0a3.75 3.75 0 010 5.303m-7.425 2.122a6.75 6.75 0 010-9.546m9.546 0a6.75 6.75 0 010 9.546" />
              </svg>
              <p>雷達正在掃描中，尚無信號...</p>
              <p className="text-sm mt-1">系統每 5 分鐘自動檢測一次</p>
            </div>
          ) : (
            alerts.map(alert => (
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
                      {severityBadge(alert.severity)}
                      <span className="text-xs text-dark-400 uppercase">{alert.type}</span>
                      {!alert.is_read && <span className="w-2 h-2 rounded-full bg-primary-500" />}
                    </div>
                    <h4 className="font-medium text-gray-200">{alert.title}</h4>
                    <p className="text-sm text-dark-400 mt-1 line-clamp-2">{alert.content}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-dark-500 whitespace-nowrap">
                      {alert.created_at && new Date(alert.created_at).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}
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

                    {/* Source URLs */}
                    {alert.source_urls && alert.source_urls.length > 0 && (
                      <div>
                        <h5 className="text-sm font-semibold text-dark-300 mb-1">資料來源</h5>
                        <div className="space-y-1">
                          {alert.source_urls.map((url, i) => (
                            <a key={i} href={url} target="_blank" rel="noopener noreferrer"
                              className="block text-xs text-primary-400 hover:underline truncate">
                              {url}
                            </a>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* AI Analysis */}
                    {alert.analysis ? (
                      <div>
                        <h5 className="text-sm font-semibold text-primary-400 mb-2">AI 分析</h5>
                        <div className="markdown-content text-sm">
                          <ReactMarkdown>{alert.analysis}</ReactMarkdown>
                        </div>
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
                          </>
                        )}
                      </button>
                    )}

                    {/* Legacy source_url fallback */}
                    {alert.source_url && !alert.source_urls && (
                      <a href={alert.source_url} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-primary-400 hover:underline">
                        查看原始來源
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                        </svg>
                      </a>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </section>

      {/* Signal Condition Modal */}
      {conditionItem && (
        <SignalConditionModal
          item={conditionItem}
          onClose={() => setConditionItem(null)}
        />
      )}
    </div>
  )
}
