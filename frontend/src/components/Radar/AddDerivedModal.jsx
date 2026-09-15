import { useEffect, useMemo, useState } from 'react'
import { toast } from 'react-hot-toast'
import { radarAPI } from '../../services/api'

const CAT_LABELS = {
  bond: '債市', currency: '匯市', equity: '股市',
  commodity: '原物料', crypto: '加密貨幣', volatility: '波動率',
}

// 代碼只留英數與底線：使用者選的指標代碼含 ^ = - . 等字元，直接串起來當代碼
// 不好讀也容易跟既有代碼混淆。
function makeSymbol(a, b) {
  const clean = (s) => (s || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase().slice(0, 10)
  return `SPR_${clean(a)}_${clean(b)}` || 'SPR_NEW'
}

export default function AddDerivedModal({ allItems, onClose, onCreated }) {
  // 只有非衍生指標能當成分（不支援衍生引用衍生，避免相依環）
  const baseItems = useMemo(
    () => allItems.filter(i => (i.provider || 'yahoo') !== 'derived'),
    [allItems]
  )
  const grouped = useMemo(() => {
    const g = {}
    for (const it of baseItems) (g[it.category || 'equity'] ||= []).push(it)
    return g
  }, [baseItems])

  const [legA, setLegA] = useState('')
  const [legB, setLegB] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [formula, setFormula] = useState('')
  const [name, setName] = useState('')
  const [symbol, setSymbol] = useState('')
  const [category, setCategory] = useState('bond')
  const [nameTouched, setNameTouched] = useState(false)
  const [symbolTouched, setSymbolTouched] = useState(false)
  const [preview, setPreview] = useState(null)
  const [checking, setChecking] = useState(false)
  const [saving, setSaving] = useState(false)

  const effectiveFormula = advanced
    ? formula
    : (legA && legB ? `{${legA}} - {${legB}}` : '')

  const itemBySymbol = useMemo(
    () => Object.fromEntries(allItems.map(i => [i.symbol, i])), [allItems]
  )

  // 簡易模式下，名稱／代碼／類別跟著選擇自動帶入，除非使用者自己改過
  useEffect(() => {
    if (advanced || !legA || !legB) return
    const a = itemBySymbol[legA], b = itemBySymbol[legB]
    if (!nameTouched) setName(`${a?.name || legA}-${b?.name || legB} 利差`)
    if (!symbolTouched) setSymbol(makeSymbol(legA, legB))
    setCategory(a?.category || 'bond')
  }, [legA, legB, advanced])   // eslint-disable-line react-hooks/exhaustive-deps

  // 試算（debounce，避免每次按鍵都打後端）
  useEffect(() => {
    if (!effectiveFormula) { setPreview(null); return }
    let cancelled = false
    setChecking(true)
    const t = setTimeout(async () => {
      try {
        const { data } = await radarAPI.previewDerived(effectiveFormula)
        if (!cancelled) setPreview(data)
      } catch {
        if (!cancelled) setPreview({ ok: false, error: '試算失敗，請稍後再試' })
      }
      if (!cancelled) setChecking(false)
    }, 500)
    return () => { cancelled = true; clearTimeout(t) }
  }, [effectiveFormula])

  const canSave = preview?.ok && name.trim() && symbol.trim() && !saving

  const handleSave = async () => {
    if (!canSave) return
    setSaving(true)
    try {
      const { data } = await radarAPI.addWatchlistItem({
        symbol: symbol.trim(),
        name: name.trim(),
        category,
        description: `自訂衍生指標：${effectiveFormula}`,
        provider: 'derived',
        formula: effectiveFormula,
        unit: preview?.unit || undefined,
        sort_order: 900,
      })
      if (data?.error) {
        toast.error(data.error)
      } else {
        toast.success(`已新增「${name.trim()}」`)
        onCreated?.()
        onClose()
      }
    } catch {
      toast.error('新增失敗')
    }
    setSaving(false)
  }

  const renderOptions = () => Object.entries(grouped).map(([cat, items]) => (
    <optgroup key={cat} label={CAT_LABELS[cat] || cat}>
      {items.map(i => <option key={i.symbol} value={i.symbol}>{i.name}</option>)}
    </optgroup>
  ))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-dark-800 rounded-xl border border-dark-600 w-full max-w-lg max-h-[88vh] overflow-y-auto shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-dark-700">
          <div>
            <h3 className="font-semibold text-lg">新增利差指標</h3>
            <p className="text-sm text-dark-400">由既有指標相減算出，會像一般指標一樣有走勢圖與警示條件</p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-dark-700 text-dark-400 hover:text-white">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {!advanced ? (
            <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
              <div>
                <label className="block text-xs text-dark-400 mb-1">指標 A</label>
                <select value={legA} onChange={e => setLegA(e.target.value)}
                  className="w-full bg-dark-700 border border-dark-600 rounded-lg px-2 py-2 text-sm focus:border-primary-500 focus:outline-none">
                  <option value="">請選擇…</option>
                  {renderOptions()}
                </select>
              </div>
              <div className="pb-2 text-lg text-dark-400 font-bold">−</div>
              <div>
                <label className="block text-xs text-dark-400 mb-1">指標 B</label>
                <select value={legB} onChange={e => setLegB(e.target.value)}
                  className="w-full bg-dark-700 border border-dark-600 rounded-lg px-2 py-2 text-sm focus:border-primary-500 focus:outline-none">
                  <option value="">請選擇…</option>
                  {renderOptions()}
                </select>
              </div>
            </div>
          ) : (
            <div>
              <label className="block text-xs text-dark-400 mb-1">自訂算式</label>
              <input
                type="text"
                value={formula}
                onChange={e => setFormula(e.target.value)}
                placeholder="{^TNX} - {DE10Y}"
                className="w-full bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm font-mono focus:border-primary-500 focus:outline-none"
              />
              <p className="text-[11px] text-dark-500 mt-1">
                指標代碼要用大括號包住（代碼本身含 <code className="text-dark-400">^ = - .</code> 這些運算子字元）。
                可用 <code className="text-dark-400">+ - * /</code> 與括號，例如
                <code className="text-dark-400"> {'{^TNX} - ({JP10Y} + {DE10Y}) / 2'}</code>。
              </p>
            </div>
          )}

          <button
            onClick={() => setAdvanced(a => !a)}
            className="text-xs text-dark-400 hover:text-primary-400 transition-colors"
          >
            {advanced ? '← 回到簡易模式（A − B）' : '進階：自訂算式 →'}
          </button>

          {/* 試算結果 */}
          <div className="rounded-lg border border-dark-600 bg-dark-900/60 px-3 py-2.5 min-h-[58px]">
            {checking ? (
              <div className="flex items-center gap-2 text-xs text-dark-400">
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-primary-500" />
                試算中…
              </div>
            ) : !effectiveFormula ? (
              <p className="text-xs text-dark-500">選好兩個指標後會即時試算目前的值</p>
            ) : preview?.ok ? (
              <div>
                <div className="flex items-baseline gap-2">
                  <span className="text-xs text-dark-400">目前值</span>
                  <span className="text-lg font-bold tabular-nums text-green-400">{preview.value}</span>
                  {preview.unit === 'percent' && <span className="text-xs text-dark-500">（＝ {(preview.value * 100).toFixed(1)}bp）</span>}
                </div>
                <div className="text-[11px] text-dark-500 mt-1">
                  {preview.legs?.map(l => `${l.name} ${l.price}`).join('  −  ')}
                </div>
              </div>
            ) : (
              <p className="text-xs text-red-400">{preview?.error || '算式無效'}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-dark-400 mb-1">顯示名稱</label>
              <input type="text" value={name}
                onChange={e => { setName(e.target.value); setNameTouched(true) }}
                placeholder="例：美德10Y利差"
                className="w-full bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm focus:border-primary-500 focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs text-dark-400 mb-1">指標代碼（唯一）</label>
              <input type="text" value={symbol}
                onChange={e => { setSymbol(e.target.value); setSymbolTouched(true) }}
                placeholder="SPR_TNX_DE10Y"
                className="w-full bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm font-mono focus:border-primary-500 focus:outline-none" />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-dark-400 mb-1">歸到哪個分類</label>
              <select value={category} onChange={e => setCategory(e.target.value)}
                className="w-full bg-dark-700 border border-dark-600 rounded-lg px-2 py-2 text-sm focus:border-primary-500 focus:outline-none">
                {Object.entries(CAT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
          </div>
        </div>

        <div className="flex gap-2 justify-end px-5 py-4 border-t border-dark-700">
          <button onClick={onClose} className="btn-secondary text-sm px-4 py-1.5">取消</button>
          <button onClick={handleSave} disabled={!canSave}
            className="btn-primary text-sm px-4 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed">
            {saving ? '新增中…' : '新增指標'}
          </button>
        </div>
      </div>
    </div>
  )
}
