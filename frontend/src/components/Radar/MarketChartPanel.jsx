import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { radarAPI } from '../../services/api'

// 類別色（深色介面用的五階，已用 dataviz validator 對 #1e293b 表面驗過：
// 明度帶 / 彩度下限 / 色盲可辨識度 / 一般視覺可辨識度 / 對比度 全數通過）。
// 固定順序、永不循環；色票綁在「指標」上而不是它在清單裡的名次，
// 移除其中一條線時其餘線不會換色。
const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181']
const MAX_SERIES = SERIES_COLORS.length

const PERIODS = [
  { v: '5d', label: '5天' },
  { v: '1mo', label: '1個月' },
  { v: '3mo', label: '3個月' },
  { v: '6mo', label: '6個月' },
  { v: '1y', label: '1年' },
  { v: '2y', label: '2年' },
]

const CAT_LABELS = {
  bond: '債市', currency: '匯市', equity: '股市',
  commodity: '原物料', crypto: '加密貨幣', volatility: '波動率',
}

function fmtValue(v, unit) {
  if (v === null || v === undefined) return '—'
  return unit === 'percent' ? `${v.toFixed(3)}%` : v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

// recharts 的 dataKey 是字串時會被當成巢狀路徑（lodash get），代碼裡的「.」
// 會被拆開——`DX-Y.NYB` 會去找 row['DX-Y']['NYB'] 而取不到值，圖就是空的。
// 因此列資料一律改用安全鍵 s0/s1/…，顯示時再映射回指標代碼。
const safeKey = (index) => `s${index}`

/** 把多條序列依時間合併成 recharts 需要的列陣列。
 *  indexed=true 時各序列除以自己的起始值 ×100，讓不同量級能放在同一個軸上比較。 */
function mergeSeries(series, indexed, hourly, keyBySymbol) {
  const rows = new Map()
  for (const s of series) {
    const k = keyBySymbol[s.symbol]
    if (!k) continue
    const pts = (s.points || []).filter(p => p.close !== null && p.close !== undefined)
    const base = indexed ? pts.find(p => p.close)?.close : null
    for (const p of pts) {
      const key = hourly ? p.time : p.time.slice(0, 10)
      if (!rows.has(key)) rows.set(key, { time: key })
      const val = indexed && base ? (p.close / base) * 100 : p.close
      rows.get(key)[k] = Number(val.toFixed(4))
    }
  }
  return [...rows.values()].sort((a, b) => a.time.localeCompare(b.time))
}

function ChartTooltip({ active, payload, label, metaBySymbol, symbolByKey, indexed }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-dark-800 border border-dark-600 rounded-lg px-3 py-2 shadow-xl">
      <div className="text-xs text-dark-400 mb-1">{label}</div>
      {payload.map(p => {
        const meta = metaBySymbol[symbolByKey[p.dataKey]]
        return (
          <div key={p.dataKey} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.color }} />
            <span className="text-dark-300">{meta?.name || symbolByKey[p.dataKey] || p.dataKey}</span>
            <span className="ml-auto tabular-nums text-gray-200">
              {indexed ? p.value?.toFixed(1) : fmtValue(p.value, meta?.unit)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function MarketChartPanel({ primarySymbol, allItems, onClose }) {
  const [compare, setCompare] = useState([])       // 額外比較的指標代碼
  const [slots, setSlots] = useState({})           // symbol -> 色票編號（移除其他線時不換色）
  const [period, setPeriod] = useState('3mo')
  const [series, setSeries] = useState([])
  const [loading, setLoading] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const pickerRef = useRef(null)

  const itemBySymbol = useMemo(
    () => Object.fromEntries(allItems.map(i => [i.symbol, i])), [allItems]
  )
  const symbols = useMemo(
    () => [primarySymbol, ...compare].filter(Boolean), [primarySymbol, compare]
  )

  // 主指標換了就重置比較清單與色票（避免沿用上一組的配色）
  useEffect(() => {
    setCompare([])
    setSlots({ [primarySymbol]: 0 })
  }, [primarySymbol])

  useEffect(() => {
    if (!pickerOpen) return
    const onDoc = (e) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) setPickerOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [pickerOpen])

  // 官方來源（日本 MOF / ECB / BoE）只有日資料，混到 5 天 / 1 小時的圖會是空的
  const allYahoo = symbols.every(s => (itemBySymbol[s]?.provider || 'yahoo') === 'yahoo')
  const hourly = period === '5d' && allYahoo
  const interval = hourly ? '1h' : '1d'

  const load = useCallback(async () => {
    if (symbols.length === 0) return
    setLoading(true)
    try {
      const { data } = await radarAPI.getMarketHistoryMulti(symbols, period, interval)
      setSeries(data.series || [])
    } catch {
      setSeries([])
    }
    setLoading(false)
  }, [symbols.join(','), period, interval])   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load() }, [load])

  const metaBySymbol = useMemo(() => {
    const out = {}
    for (const s of series) out[s.symbol] = s
    return out
  }, [series])

  // 單位不同（例：殖利率 % 對匯率數值）不能共用一個刻度，也不可以開雙軸——
  // 兩個 y 軸的對齊方式是任意的，會憑空造出不存在的相關性。改成指數化到共同基準。
  const units = new Set(series.map(s => s.unit || 'price'))
  const indexed = units.size > 1

  const { keyBySymbol, symbolByKey } = useMemo(() => {
    const k = {}, r = {}
    symbols.forEach((sym, i) => { k[sym] = safeKey(i); r[safeKey(i)] = sym })
    return { keyBySymbol: k, symbolByKey: r }
  }, [symbols])

  const rows = useMemo(
    () => mergeSeries(series, indexed, hourly, keyBySymbol),
    [series, indexed, hourly, keyBySymbol]
  )

  const addCompare = (sym) => {
    if (compare.includes(sym) || sym === primarySymbol) return
    if (symbols.length >= MAX_SERIES) return
    const used = new Set(Object.values(slots))
    let free = 0
    while (used.has(free)) free += 1
    setSlots(prev => ({ ...prev, [sym]: free }))
    setCompare(prev => [...prev, sym])
  }

  const removeCompare = (sym) => {
    setCompare(prev => prev.filter(s => s !== sym))
    setSlots(prev => {
      const next = { ...prev }
      delete next[sym]           // 釋放色票，其餘指標的色票不動
      return next
    })
  }

  const primary = itemBySymbol[primarySymbol]
  const colorOf = (sym) => SERIES_COLORS[(slots[sym] ?? 0) % SERIES_COLORS.length]

  const grouped = useMemo(() => {
    const g = {}
    for (const it of allItems) {
      if (it.symbol === primarySymbol) continue
      ;(g[it.category || 'equity'] ||= []).push(it)
    }
    return g
  }, [allItems, primarySymbol])

  return (
    <section className="card">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="font-semibold">
          {primary?.name || primarySymbol}
          {symbols.length > 1 && <span className="text-dark-400 font-normal"> 等 {symbols.length} 項比較</span>}
          <span className="text-dark-400 font-normal"> 走勢圖</span>
        </h3>

        <div className="flex items-center gap-1.5">
          {/* 日期範圍 */}
          <div className="flex items-center gap-0.5 mr-1">
            {PERIODS.map(p => {
              const disabled = p.v === '5d' && !allYahoo
              return (
                <button
                  key={p.v}
                  onClick={() => !disabled && setPeriod(p.v)}
                  disabled={disabled}
                  title={disabled ? '所選指標含官方來源日資料，不支援 5 天檢視' : ''}
                  className={`text-xs px-2 py-1 rounded transition-colors ${
                    period === p.v
                      ? 'bg-primary-600/30 text-primary-400'
                      : disabled
                        ? 'text-dark-700 cursor-not-allowed'
                        : 'text-dark-400 hover:text-gray-200 hover:bg-dark-700'
                  }`}
                >
                  {p.label}
                </button>
              )
            })}
          </div>

          {/* 加入比較 */}
          <div className="relative" ref={pickerRef}>
            <button
              onClick={() => setPickerOpen(o => !o)}
              disabled={symbols.length >= MAX_SERIES}
              title={symbols.length >= MAX_SERIES ? `最多同時比較 ${MAX_SERIES} 項` : '加入其他指標比較'}
              className="text-xs px-2 py-1 rounded border border-dark-600 text-dark-300 hover:text-primary-400 hover:border-primary-500/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              + 比較
            </button>
            {pickerOpen && (
              <div className="absolute right-0 top-full mt-1 z-50 w-56 max-h-72 overflow-y-auto bg-dark-800 border border-dark-600 rounded-lg shadow-xl p-2">
                {Object.entries(grouped).map(([cat, items]) => (
                  <div key={cat} className="mb-2 last:mb-0">
                    <div className="text-[10px] text-dark-500 px-1 mb-1">{CAT_LABELS[cat] || cat}</div>
                    {items.map(it => (
                      <button
                        key={it.symbol}
                        onClick={() => { addCompare(it.symbol); setPickerOpen(false) }}
                        disabled={compare.includes(it.symbol)}
                        className="w-full text-left text-xs px-2 py-1 rounded text-dark-300 hover:bg-dark-700 hover:text-gray-100 disabled:opacity-40 disabled:cursor-not-allowed truncate"
                      >
                        {it.name}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 資料來源 */}
          {primary?.source_url ? (
            <a
              href={primary.source_url}
              target="_blank"
              rel="noopener noreferrer"
              title={`資料來源：${primary.source_name || '來源'}`}
              className="p-1 rounded text-dark-400 hover:text-primary-400 hover:bg-dark-700 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
            </a>
          ) : primary?.source_name ? (
            <span className="text-[10px] text-dark-500 px-1" title="此指標由系統計算">
              {primary.source_name}
            </span>
          ) : null}

          <button onClick={onClose} className="p-1 rounded text-dark-400 hover:text-white hover:bg-dark-700 transition-colors" title="關閉">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      {/* 圖例（兩條以上一定顯示，讓身分不是只靠顏色傳達）*/}
      {symbols.length > 1 && (
        <div className="flex flex-wrap items-center gap-3 mb-2">
          {symbols.map(sym => {
            const meta = metaBySymbol[sym] || itemBySymbol[sym] || {}
            return (
              <span key={sym} className="flex items-center gap-1.5 text-xs text-dark-300">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: colorOf(sym) }} />
                {meta.name || sym}
                {sym !== primarySymbol && (
                  <button
                    onClick={() => removeCompare(sym)}
                    className="text-dark-600 hover:text-red-400 leading-none ml-0.5"
                    title="移除此指標"
                  >×</button>
                )}
              </span>
            )
          })}
        </div>
      )}

      {indexed && (
        <p className="text-[11px] text-dark-500 mb-2">
          所選指標單位不同（殖利率與價格無法共用同一刻度），已<span className="text-dark-300">指數化為起點 = 100</span> 比較相對走勢。
        </p>
      )}

      {loading && rows.length === 0 ? (
        <div className="h-[250px] flex items-center justify-center">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-500" />
        </div>
      ) : rows.length === 0 ? (
        <div className="h-[250px] flex items-center justify-center text-sm text-dark-500">此區間無資料</div>
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#334155" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 11, fill: '#64748b' }}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
              interval="preserveStartEnd"
              minTickGap={40}
              tickFormatter={(t) => (hourly ? t.slice(5, 16).replace('T', ' ') : t.slice(5))}
            />
            <YAxis
              domain={['auto', 'auto']}
              tick={{ fontSize: 11, fill: '#64748b' }}
              tickLine={false}
              axisLine={false}
              width={52}
              tickFormatter={(v) => (indexed ? v.toFixed(0) : v.toFixed(2))}
            />
            <Tooltip
              content={<ChartTooltip metaBySymbol={metaBySymbol} symbolByKey={symbolByKey} indexed={indexed} />}
              cursor={{ stroke: '#475569', strokeWidth: 1 }}
            />
            {symbols.map(sym => (
              <Line
                key={sym}
                type="monotone"
                dataKey={keyBySymbol[sym]}
                stroke={colorOf(sym)}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}
