import { useEffect, useState } from 'react'
import { radarAPI } from '../services/api'

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

// Tab 定義：分為兩組（NLM 和 Gemini），每組有新聞和 YT
const TAB_CONFIG = {
  // NLM tabs
  nlm_news: {
    label: '📰 NLM 新聞',
    emptyMsg: '尚無 NLM 新聞分析報告',
    emptyHint: 'NotebookLM 腳本執行後報告將自動同步至此',
    reportType: 'news',
    getLatest: () => radarAPI.getNlmReport(),
    listHistory: () => radarAPI.listNlmReports('news'),
    getById: (id) => radarAPI.getNlmReportById(id),
    group: 'nlm',
  },
  nlm_yt: {
    label: '📺 NLM YouTube',
    emptyMsg: '尚無 NLM YouTube 分析報告',
    emptyHint: 'NotebookLM 腳本執行後報告將自動同步至此',
    reportType: 'yt',
    getLatest: () => radarAPI.getNlmYtReport(),
    listHistory: () => radarAPI.listNlmReports('yt'),
    getById: (id) => radarAPI.getNlmReportById(id),
    group: 'nlm',
  },
  // Gemini tabs
  gemini_news: {
    label: '📰 Gemini 新聞',
    emptyMsg: '尚無 Gemini 新聞分析報告',
    emptyHint: 'VM 每 3 小時自動執行 Gemini 深度分析',
    reportType: 'gemini_news',
    getLatest: () => radarAPI.getGeminiReport(),
    listHistory: () => radarAPI.listGeminiReports('gemini_news'),
    getById: (id) => radarAPI.getGeminiReportById(id),
    group: 'gemini',
  },
  gemini_yt: {
    label: '📺 Gemini YouTube',
    emptyMsg: '尚無 Gemini YouTube 分析報告',
    emptyHint: 'VM 每 3 小時自動執行 Gemini 深度分析',
    reportType: 'gemini_yt',
    getLatest: () => radarAPI.getGeminiYtReport(),
    listHistory: () => radarAPI.listGeminiReports('gemini_yt'),
    getById: (id) => radarAPI.getGeminiReportById(id),
    group: 'gemini',
  },
  // Extension 手動分析（Chrome Extension）
  extension: {
    label: '🧩 Extension 分析',
    emptyMsg: '尚無 Extension 手動分析報告',
    emptyHint: '安裝 Chrome Extension 後，按下「產生分析報告」會推送至此',
    reportType: 'extension_manual',
    getLatest: () => radarAPI.getExtensionReport(),
    listHistory: () => radarAPI.listExtensionReports(),
    getById: (id) => radarAPI.getExtensionReportById(id),
    group: 'extension',
  },
}

export default function AnalysisPage() {
  const [tab, setTab] = useState('gemini_news')
  const [histories, setHistories] = useState({})
  const [selectedIds, setSelectedIds] = useState({})
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)

  // 載入所有 tab 的歷史清單
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const [nList, yList, gnList, gyList, extList] = await Promise.all([
          radarAPI.listNlmReports('news'),
          radarAPI.listNlmReports('yt'),
          radarAPI.listGeminiReports('gemini_news'),
          radarAPI.listGeminiReports('gemini_yt'),
          radarAPI.listExtensionReports(),
        ])
        setHistories({
          nlm_news: nList.data || [],
          nlm_yt: yList.data || [],
          gemini_news: gnList.data || [],
          gemini_yt: gyList.data || [],
          extension: extList.data || [],
        })
      } catch {
        // 靜默失敗
      }
    }
    loadHistory()
  }, [])

  // 載入選定報告內容（或最新報告）
  useEffect(() => {
    const loadReport = async () => {
      setLoading(true)
      try {
        const cfg = TAB_CONFIG[tab]
        const selectedId = selectedIds[tab]
        let res
        if (selectedId) {
          res = await cfg.getById(selectedId)
        } else {
          res = await cfg.getLatest()
        }
        setReport(res.data)
      } catch {
        setReport(null)
      } finally {
        setLoading(false)
      }
    }
    loadReport()
  }, [tab, selectedIds])

  const cfg = TAB_CONFIG[tab]
  const history = histories[tab] || []
  const selectedId = selectedIds[tab]
  const setSelectedId = (id) => setSelectedIds((prev) => ({ ...prev, [tab]: id }))

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

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* 分析引擎切換 */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-4">
        <div className="flex gap-1 bg-dark-800 rounded-lg p-1 border border-dark-700 overflow-x-auto max-w-full">
          {Object.entries(TAB_CONFIG).map(([key, c]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-3 py-1.5 rounded-md font-medium text-xs transition-colors ${
                tab === key
                  ? c.group === 'gemini'
                    ? 'bg-blue-600 text-white'
                    : c.group === 'extension'
                    ? 'bg-violet-600 text-white'
                    : 'bg-primary-600 text-white'
                  : 'text-dark-400 hover:text-white'
              }`}
            >{c.label}</button>
          ))}
        </div>

        {/* Gemini 手動觸發按鈕 */}
        {cfg.group === 'gemini' && (
          <button
            onClick={handleTriggerGemini}
            disabled={analyzing}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600/20 text-blue-400 border border-blue-600/40 hover:bg-blue-600/30 disabled:opacity-50 transition-colors"
          >
            {analyzing ? '分析中...' : '手動觸發 Gemini 分析'}
          </button>
        )}
      </div>

      {/* 歷史清單（橫列） */}
      {history.length > 1 && (
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          <span className="text-xs text-dark-500 whitespace-nowrap shrink-0">歷史（{history.length}）</span>
          {history.map((h) => (
            <button
              key={h.id}
              onClick={() => setSelectedId(selectedId === h.id ? null : h.id)}
              className={`shrink-0 px-3 py-1.5 rounded-lg text-xs transition-colors whitespace-nowrap ${
                (selectedId === h.id || (!selectedId && h.id === history[0]?.id))
                  ? cfg.group === 'gemini'
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-600/40'
                    : cfg.group === 'extension'
                    ? 'bg-violet-600/20 text-violet-400 border border-violet-600/40'
                    : 'bg-primary-600/20 text-primary-400 border border-primary-600/40'
                  : 'text-dark-400 hover:text-dark-200 hover:bg-dark-800 border border-dark-700'
              }`}
            >
              {fmtDate(h.generated_at)}
            </button>
          ))}
        </div>
      )}

      {/* 報告內容 */}
      <div className="card">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500" />
            </div>
          ) : !report?.content ? (
            <div className="text-center py-16 text-dark-500">
              <div className="text-4xl mb-3">{cfg.group === 'gemini' ? '🤖' : cfg.group === 'extension' ? '🧩' : '📋'}</div>
              <div className="text-sm">{cfg.emptyMsg}</div>
              <div className="text-xs text-dark-600 mt-1">{cfg.emptyHint}</div>
            </div>
          ) : (
            <div>
              {/* 報告 meta */}
              <div className="flex items-center justify-between pb-4 mb-4 border-b border-dark-700">
                <div className="text-xs text-dark-500 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      cfg.group === 'gemini'
                        ? 'bg-blue-600/20 text-blue-400'
                        : cfg.group === 'extension'
                        ? 'bg-violet-600/20 text-violet-400'
                        : 'bg-primary-600/20 text-primary-400'
                    }`}>
                      {cfg.group === 'gemini' ? 'Gemini' : cfg.group === 'extension' ? 'Extension' : 'NotebookLM'}
                    </span>
                    <span>生成時間：<span className="text-dark-400">
                      {report.generated_at ? new Date(report.generated_at).toLocaleString('zh-TW') : '—'}
                    </span></span>
                  </div>
                  {report.source_title && (
                    <div>來源批次：<span className="text-dark-400">{report.source_title}</span></div>
                  )}
                </div>
                {history.length > 0 && (
                  <div className="text-xs text-dark-600">共 {history.length} 份歷史報告</div>
                )}
              </div>
              {/* 報告本文 */}
              <div className="space-y-0">
                {renderReport(report.content)}
              </div>
            </div>
          )}
        </div>
    </div>
  )
}
