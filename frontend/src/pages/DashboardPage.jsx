import { useCallback, useEffect, useState } from 'react'
import { radarAPI, newsAPI, getCurrentUser, hasRole } from '../services/api'
import CategoryTabs from '../components/Radar/CategoryTabs'
import MarketIndicatorCard from '../components/Radar/MarketIndicatorCard'
import MarketChartPanel from '../components/Radar/MarketChartPanel'
import AddDerivedModal from '../components/Radar/AddDerivedModal'
import SignalConditionModal from '../components/Radar/SignalConditionModal'

const SENTIMENT_COLORS = {
  positive: { bg: 'bg-green-500', text: 'text-green-400', label: '正面' },
  neutral: { bg: 'bg-yellow-500', text: 'text-yellow-400', label: '中性' },
  negative: { bg: 'bg-red-500', text: 'text-red-400', label: '偏負' },
}

export default function DashboardPage({ wsSubscribe }) {
  // Market indicators state
  const [marketData, setMarketData] = useState({})
  const [categories, setCategories] = useState([])
  const [activeCategory, setActiveCategory] = useState('bond')
  const [sparklines, setSparklines] = useState({})
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [conditionItem, setConditionItem] = useState(null)
  const [showAddDerived, setShowAddDerived] = useState(false)
  const isAdmin = hasRole('admin')
  const [marketLoading, setMarketLoading] = useState(true)

  // Sentiment state
  const [sentiment, setSentiment] = useState(null)
  const [sentimentLoading, setSentimentLoading] = useState(false)

  const loadMarketData = useCallback(async () => {
    setMarketLoading(true)
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

  // 走勢縮圖一次要回全部指標：後端會批次抓（Yahoo 一次 yf.download、
  // 官方來源共用快取），比每檔各打一次快得多——指標擴充到 34 檔後差很多。
  const loadSparklines = useCallback(async (grouped) => {
    const items = Object.values(grouped).flat()
    if (items.length === 0) return
    try {
      const { data } = await radarAPI.getMarketHistoryMulti(
        items.map(i => i.symbol), '1mo', '1d'
      )
      const results = {}
      for (const s of data.series || []) {
        results[s.symbol] = (s.points || []).map(d => ({ close: d.close }))
      }
      setSparklines(results)
    } catch (err) {
      console.error('Failed to load sparklines:', err)
    }
  }, [])

  const loadSentiment = useCallback(async () => {
    // 訪客（未登入）跳過：/news/sentiment 是 regular+，會 401 觸發登入彈窗
    if (!getCurrentUser()) return
    setSentimentLoading(true)
    try {
      const { data } = await newsAPI.getSentiment()
      setSentiment(data)
    } catch (err) {
      console.error('Failed to load sentiment:', err)
    }
    setSentimentLoading(false)
  }, [])

  useEffect(() => {
    loadMarketData()
    loadSentiment()
    const interval = setInterval(() => { loadMarketData() }, 3600000)
    return () => clearInterval(interval)
  }, [loadMarketData, loadSentiment])

  useEffect(() => {
    if (Object.keys(marketData).length > 0) {
      loadSparklines(marketData)
    }
  }, [marketData, loadSparklines])

  useEffect(() => {
    if (!wsSubscribe) return
    const unsub = wsSubscribe('market_alert', () => { loadMarketData() })
    return () => unsub()
  }, [wsSubscribe, loadMarketData])

  const displayItems = activeCategory === 'all'
    ? Object.values(marketData).flat()
    : marketData[activeCategory] || []

  const allItems = Object.values(marketData).flat()

  return (
    <div className="space-y-6">
      {/* Market Indicators */}
      <section>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <h3 className="text-lg font-semibold">市場指標總覽</h3>
          <div className="flex items-center gap-2">
          {isAdmin && (
            <button
              onClick={() => setShowAddDerived(true)}
              className="btn-secondary text-sm flex items-center gap-1.5"
              title="由既有指標相減，自訂一個利差指標"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              新增利差
            </button>
          )}
          <button onClick={loadMarketData} className="btn-secondary text-sm flex items-center gap-1.5">
            <svg className={`w-4 h-4 ${marketLoading ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
            </svg>
            更新
          </button>
          </div>
        </div>

        {categories.length > 0 && (
          <div className="mb-4">
            <CategoryTabs
              categories={categories}
              activeCategory={activeCategory}
              onSelect={setActiveCategory}
            />
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 md:gap-4">
          {marketLoading && displayItems.length === 0 ? (
            Array(8).fill(0).map((_, i) => (
              <div key={i} className="card animate-pulse">
                <div className="h-4 bg-dark-700 rounded w-2/3 mb-2" />
                <div className="h-8 bg-dark-700 rounded w-1/2 mb-2" />
                <div className="h-10 bg-dark-700 rounded w-full" />
              </div>
            ))
          ) : displayItems.length === 0 ? (
            <div className="col-span-full text-center text-dark-400 py-8">此分類尚無指標</div>
          ) : (
            displayItems.map((item) => (
              <MarketIndicatorCard
                key={item.symbol}
                item={item}
                sparkData={sparklines[item.symbol]}
                isSelected={selectedSymbol === item.symbol}
                onClick={() => setSelectedSymbol(item.symbol)}
                onSettingsClick={(item) => setConditionItem(item)}
              />
            ))
          )}
        </div>
      </section>

      {/* Chart */}
      {selectedSymbol && (
        <MarketChartPanel
          primarySymbol={selectedSymbol}
          allItems={allItems}
          onClose={() => setSelectedSymbol(null)}
        />
      )}

      {/* News Sentiment & Heat */}
      <section className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold flex items-center gap-2">
            <svg className="w-5 h-5 text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
            </svg>
            今日市場熱度與情緒
            {sentiment && (
              <span className="text-xs text-dark-400 font-normal">
                {sentiment.date} · {sentiment.total_articles} 則新聞
              </span>
            )}
          </h3>
          <button
            onClick={loadSentiment}
            className="btn-secondary text-sm flex items-center gap-1.5"
          >
            <svg className={`w-4 h-4 ${sentimentLoading ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
            </svg>
            重新整理
          </button>
        </div>

        {!sentiment || !sentiment.categories || sentiment.categories.length === 0 ? (
          <div className="text-center text-dark-400 py-8">
            <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75z" />
            </svg>
            <p>尚無今日新聞資料</p>
            <p className="text-sm mt-1">先到新聞資料庫抓取新聞後再查看</p>
          </div>
        ) : (
          <div className="space-y-3">
            {sentiment.categories.map((cat) => {
              const colors = SENTIMENT_COLORS[cat.sentiment_label] || SENTIMENT_COLORS.neutral
              return (
                <div key={cat.category} className="flex items-center gap-3">
                  <span className="text-sm w-20 text-dark-300 shrink-0">{cat.label}</span>
                  <div className="flex-1 h-5 bg-dark-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${colors.bg} rounded-full transition-all duration-700`}
                      style={{ width: `${Math.max(cat.heat, 3)}%` }}
                    />
                  </div>
                  <span className="text-sm tabular-nums w-8 text-right text-dark-300 font-medium">{cat.heat}</span>
                  <span className={`text-xs w-10 text-center font-medium ${colors.text}`}>{colors.label}</span>
                  <span className="text-xs text-dark-500 w-14 text-right">({cat.article_count} 則)</span>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* 新增利差指標 */}
      {showAddDerived && (
        <AddDerivedModal
          allItems={allItems}
          onClose={() => setShowAddDerived(false)}
          onCreated={loadMarketData}
        />
      )}

      {/* Signal Condition Modal */}
      {conditionItem && (
        <SignalConditionModal
          item={conditionItem}
          onClose={() => setConditionItem(null)}
          onDeleted={() => { setSelectedSymbol(null); loadMarketData() }}
        />
      )}
    </div>
  )
}
