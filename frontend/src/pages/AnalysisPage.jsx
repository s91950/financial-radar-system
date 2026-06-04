import { useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import { radarAPI, hasRole } from '../services/api'

// 將文字片段中的 URL 轉成可點擊的 <a> 連結
function linkify(text, keyPrefix) {
  const URL_RE = /https?:\/\/[^\s）)】\]]+/g
  const parts = []
  let last = 0, m
  while ((m = URL_RE.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    parts.push(
      <a key={`${keyPrefix}-u${m.index}`} href={m[0]} target="_blank" rel="noopener noreferrer"
        className="text-primary-400 hover:text-primary-300 underline break-all">
        {m[0]}
      </a>
    )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length === 1 && typeof parts[0] === 'string' ? text : parts
}

// 將行內 **bold** 與 URL 都渲染出來
function renderInline(line, lineKey) {
  const segments = line.split(/(\*\*[^*]+\*\*)/)
  return segments.map((seg, j) => {
    const bold = seg.match(/^\*\*(.+)\*\*$/)
    if (bold) return <strong key={`${lineKey}-b${j}`} className="text-gray-100 font-semibold">{bold[1]}</strong>
    return <span key={`${lineKey}-s${j}`}>{linkify(seg, `${lineKey}-s${j}`)}</span>
  })
}

function renderReport(content) {
  if (!content) return null
  return content.split('\n').map((line, i) => {
    if (/^#{1,4}\s/.test(line)) {
      const level = line.match(/^(#{1,4})\s/)[1].length
      const text = line.replace(/^#{1,4}\s/, '')
      const cls = level === 1
        ? 'text-lg font-bold text-gray-100 mt-6 mb-2'
        : level === 2
        ? 'text-base font-semibold text-gray-200 mt-5 mb-1.5'
        : level === 3
        ? 'text-[15px] font-medium text-primary-300 mt-4 mb-1'
        : 'text-[15px] font-medium text-gray-300 mt-3 mb-0.5'
      return <div key={i} className={cls}>{text}</div>
    }
    if (/^---+$/.test(line.trim())) return <hr key={i} className="border-dark-700 my-3" />
    // Whole-line bold: **text**
    const boldMatch = line.match(/^\*\*(.+)\*\*$/)
    if (boldMatch) return <div key={i} className="text-[15px] font-semibold text-gray-200 mt-2">{boldMatch[1]}</div>
    if (line.trim() === '') return <div key={i} className="h-1.5" />
    // Source indent lines starting with spaces (分類版 **來源**: ...)
    const isIndented = /^\s{2,}/.test(line)
    return (
      <div key={i} className={`text-[15px] leading-relaxed ${isIndented ? 'text-gray-400 pl-4 mt-0.5' : 'text-gray-300'}`}>
        {renderInline(line.trimStart(), i)}
      </div>
    )
  })
}

// 葉節點設定：leafKey = `${engine}_${kind}`，對應每個引擎×類型的報告來源
const TAB_CONFIG = {
  extension_news: {
    emptyMsg: '尚無 Extension 新聞分析報告',
    emptyHint: 'Chrome Extension 選擇「新聞 notebook」後產生的報告會出現在這裡',
    getById: (id) => radarAPI.getExtensionReportById(id),
    group: 'extension',
  },
  extension_yt: {
    emptyMsg: '尚無 Extension YouTube 分析報告',
    emptyHint: 'Chrome Extension 選擇「YouTube notebook」後產生的報告會出現在這裡',
    getById: (id) => radarAPI.getExtensionReportById(id),
    group: 'extension',
  },
  gemini_news: {
    emptyMsg: '尚無 Gemini 新聞分析報告',
    emptyHint: 'VM 每 3 小時自動執行 Gemini 深度分析',
    getById: (id) => radarAPI.getGeminiReportById(id),
    group: 'gemini',
  },
  gemini_yt: {
    emptyMsg: '尚無 Gemini YouTube 分析報告',
    emptyHint: 'VM 每 3 小時自動執行 Gemini 深度分析',
    getById: (id) => radarAPI.getGeminiReportById(id),
    group: 'gemini',
  },
  nlm_news: {
    emptyMsg: '尚無 NLM 新聞分析報告',
    emptyHint: 'NotebookLM 腳本執行後報告將自動同步至此',
    getById: (id) => radarAPI.getNlmReportById(id),
    group: 'nlm',
  },
  nlm_yt: {
    emptyMsg: '尚無 NLM YouTube 分析報告',
    emptyHint: 'NotebookLM 腳本執行後報告將自動同步至此',
    getById: (id) => radarAPI.getNlmReportById(id),
    group: 'nlm',
  },
}

// 頂層資料夾（分析引擎）
const ENGINES = [
  { key: 'extension', label: 'Extension', group: 'extension', icon: '🧩' },
  { key: 'gemini', label: 'Gemini', group: 'gemini', icon: '🤖' },
  { key: 'nlm', label: 'NotebookLM', group: 'nlm', icon: '📔' },
]
// 子資料夾（報告類型）
const KINDS = [
  { key: 'news', label: '新聞', icon: '📰' },
  { key: 'yt', label: 'YouTube', icon: '📺' },
]

const groupBadge = (g) => g === 'gemini' ? 'bg-blue-600/20 text-blue-400'
  : g === 'extension' ? 'bg-violet-600/20 text-violet-400'
  : 'bg-primary-600/20 text-primary-400'
const groupBadgeLabel = (g) => g === 'gemini' ? 'Gemini' : g === 'extension' ? 'Extension' : 'NotebookLM'

export default function AnalysisPage() {
  const isAdmin = hasRole('admin')
  const [path, setPath] = useState([])          // [] | [engine] | [engine, kind]
  const [viewing, setViewing] = useState(null)  // null | { leafKey, id }
  const [histories, setHistories] = useState({})
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)

  // 載入所有 leaf 的歷史清單（資料夾內的「檔案」）
  const loadHistory = async () => {
    try {
      const [nList, yList, gnList, gyList, extNewsList, extYtList] = await Promise.all([
        radarAPI.listNlmReports('news'),
        radarAPI.listNlmReports('yt'),
        radarAPI.listGeminiReports('gemini_news'),
        radarAPI.listGeminiReports('gemini_yt'),
        radarAPI.listExtensionReports('news'),
        radarAPI.listExtensionReports('yt'),
      ])
      setHistories({
        nlm_news: nList.data || [],
        nlm_yt: yList.data || [],
        gemini_news: gnList.data || [],
        gemini_yt: gyList.data || [],
        extension_news: extNewsList.data || [],
        extension_yt: extYtList.data || [],
      })
    } catch {
      // 靜默失敗
    }
  }
  useEffect(() => { loadHistory() }, [])

  // 開啟某份檔案時載入內容
  useEffect(() => {
    if (!viewing) { setReport(null); return }
    let cancelled = false
    setLoading(true)
    TAB_CONFIG[viewing.leafKey].getById(viewing.id)
      .then((res) => { if (!cancelled) setReport(res.data) })
      .catch(() => { if (!cancelled) setReport(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [viewing])

  const fmtDate = (iso) => {
    if (!iso) return '—'
    return new Date(iso).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  const handleTriggerGemini = async () => {
    setAnalyzing(true)
    try {
      await radarAPI.triggerGeminiAnalysis()
    } catch {
      // 靜默失敗
    } finally {
      setTimeout(() => setAnalyzing(false), 3000)
    }
  }

  const handleDeleteReport = async (id, label) => {
    if (!id) return
    if (!confirm(`確定刪除「${label}」這份分析報告嗎？此動作無法復原。`)) return
    try {
      await radarAPI.deleteReport(id)
      toast.success('已刪除')
      if (viewing?.id === id) setViewing(null)
      await loadHistory()
    } catch {
      toast.error('刪除失敗')
    }
  }

  // 導覽衍生狀態
  const engineKey = path[0] || null
  const kindKey = path[1] || null
  const engine = engineKey ? ENGINES.find((e) => e.key === engineKey) : null
  const leafKey = engineKey && kindKey ? `${engineKey}_${kindKey}` : null
  const leafCfg = leafKey ? TAB_CONFIG[leafKey] : null
  const files = leafKey ? (histories[leafKey] || []) : []
  const viewCfg = viewing ? TAB_CONFIG[viewing.leafKey] : null

  const countFor = (ek, kk) => (histories[`${ek}_${kk}`] || []).length
  const engineTotal = (ek) => KINDS.reduce((s, k) => s + countFor(ek, k.key), 0)

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* 麵包屑 */}
      <div className="flex items-center gap-1.5 text-sm flex-wrap">
        <button
          onClick={() => { setPath([]); setViewing(null) }}
          className={`hover:text-white transition-colors ${path.length === 0 && !viewing ? 'text-white font-medium' : 'text-dark-300'}`}
        >
          📁 分析結果
        </button>
        {engineKey && (
          <>
            <span className="text-dark-600">/</span>
            <button
              onClick={() => { setPath([engineKey]); setViewing(null) }}
              className={`hover:text-white transition-colors ${path.length === 1 && !viewing ? 'text-white font-medium' : 'text-dark-300'}`}
            >
              {engine?.label}
            </button>
          </>
        )}
        {kindKey && (
          <>
            <span className="text-dark-600">/</span>
            <button
              onClick={() => { setPath([engineKey, kindKey]); setViewing(null) }}
              className={`hover:text-white transition-colors ${path.length === 2 && !viewing ? 'text-white font-medium' : 'text-dark-300'}`}
            >
              {KINDS.find((k) => k.key === kindKey)?.label}
            </button>
          </>
        )}
        {viewing && report && (
          <>
            <span className="text-dark-600">/</span>
            <span className="text-white font-medium">{fmtDate(report.generated_at)}</span>
          </>
        )}
      </div>

      {/* === 閱讀器 === */}
      {viewing ? (
        <div className="card">
          <button
            onClick={() => setViewing(null)}
            className="text-sm text-dark-400 hover:text-white transition-colors mb-4"
          >
            ← 返回清單
          </button>
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500" />
            </div>
          ) : !report?.content ? (
            <div className="text-center py-16 text-dark-500">
              <div className="text-4xl mb-3">📄</div>
              <div className="text-sm">無法載入這份報告</div>
            </div>
          ) : (
            <div>
              {/* 報告 meta */}
              <div className="flex items-center justify-between pb-4 mb-4 border-b border-dark-700">
                <div className="text-xs text-dark-500 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${groupBadge(viewCfg?.group)}`}>
                      {groupBadgeLabel(viewCfg?.group)}
                    </span>
                    <span>生成時間：<span className="text-dark-400">
                      {report.generated_at ? new Date(report.generated_at).toLocaleString('zh-TW') : '—'}
                    </span></span>
                  </div>
                  {report.source_title && (
                    <div>來源批次：<span className="text-dark-400">{report.source_title}</span></div>
                  )}
                </div>
                {isAdmin && report?.id && (
                  <button
                    onClick={() => handleDeleteReport(report.id, fmtDate(report.generated_at))}
                    className="text-xs text-dark-500 hover:text-red-400 transition-colors px-2 py-1 rounded border border-dark-700 hover:border-red-500/40 shrink-0"
                    title="刪除這份報告"
                  >
                    🗑 刪除
                  </button>
                )}
              </div>
              {/* 報告本文 */}
              <div className="space-y-0">
                {renderReport(report.content)}
              </div>
            </div>
          )}
        </div>
      ) : path.length === 0 ? (
        /* === 根目錄：引擎資料夾 === */
        <div className="card p-0 overflow-hidden divide-y divide-dark-700">
          {ENGINES.map((e) => (
            <button
              key={e.key}
              onClick={() => setPath([e.key])}
              className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-dark-800 transition-colors text-left"
            >
              <span className="text-xl shrink-0">📁</span>
              <span className="text-base shrink-0">{e.icon}</span>
              <span className="flex-1 font-medium text-gray-200">{e.label}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${groupBadge(e.group)}`}>{groupBadgeLabel(e.group)}</span>
              <span className="text-xs text-dark-500 shrink-0 w-16 text-right">共 {engineTotal(e.key)} 份</span>
            </button>
          ))}
        </div>
      ) : path.length === 1 ? (
        /* === 引擎資料夾：類型子資料夾 === */
        <div className="space-y-2">
          {isAdmin && engine?.group === 'gemini' && (
            <div className="flex justify-end">
              <button
                onClick={handleTriggerGemini}
                disabled={analyzing}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600/20 text-blue-400 border border-blue-600/40 hover:bg-blue-600/30 disabled:opacity-50 transition-colors"
              >
                {analyzing ? '分析中...' : '手動觸發 Gemini 分析'}
              </button>
            </div>
          )}
          <div className="card p-0 overflow-hidden divide-y divide-dark-700">
            {KINDS.map((k) => (
              <button
                key={k.key}
                onClick={() => setPath([engineKey, k.key])}
                className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-dark-800 transition-colors text-left"
              >
                <span className="text-xl shrink-0">📁</span>
                <span className="text-base shrink-0">{k.icon}</span>
                <span className="flex-1 font-medium text-gray-200">{k.label}</span>
                <span className="text-xs text-dark-500 shrink-0">{countFor(engineKey, k.key)} 份</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        /* === 子資料夾：報告檔案清單 === */
        files.length === 0 ? (
          <div className="card text-center py-16 text-dark-500">
            <div className="text-4xl mb-3">{engine?.icon}</div>
            <div className="text-sm">{leafCfg?.emptyMsg}</div>
            <div className="text-xs text-dark-600 mt-1">{leafCfg?.emptyHint}</div>
          </div>
        ) : (
          <div className="card p-0 overflow-hidden divide-y divide-dark-700">
            {files.map((h) => (
              <div
                key={h.id}
                className="group/item flex items-center gap-3 px-4 py-3 hover:bg-dark-800 transition-colors"
              >
                <button
                  onClick={() => setViewing({ leafKey, id: h.id })}
                  className="flex items-center gap-3 flex-1 text-left min-w-0"
                >
                  <span className="text-lg shrink-0">📄</span>
                  <span className="font-medium text-gray-200 shrink-0">{fmtDate(h.generated_at)}</span>
                  {h.source_title && (
                    <span className="text-xs text-dark-500 truncate">{h.source_title}</span>
                  )}
                </button>
                {isAdmin && (
                  <button
                    onClick={() => handleDeleteReport(h.id, fmtDate(h.generated_at))}
                    className="text-dark-500 hover:text-red-400 px-2 opacity-0 group-hover/item:opacity-100 transition-opacity shrink-0"
                    title="刪除這份報告"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}
