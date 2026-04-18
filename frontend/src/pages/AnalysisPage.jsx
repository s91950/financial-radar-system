import { useEffect, useState } from 'react'
import { radarAPI } from '../services/api'

function renderReport(content) {
  if (!content) return null
  return content.split('\n').map((line, i) => {
    if (/^#{1,3}\s/.test(line)) {
      const level = line.match(/^(#{1,3})\s/)[1].length
      const text = line.replace(/^#{1,3}\s/, '')
      const cls = level === 1
        ? 'text-base font-bold text-dark-100 mt-6 mb-2'
        : level === 2
        ? 'text-sm font-semibold text-dark-200 mt-5 mb-1'
        : 'text-sm font-medium text-dark-300 mt-3 mb-1'
      return <div key={i} className={cls}>{text}</div>
    }
    if (/^---+$/.test(line.trim())) return <hr key={i} className="border-dark-700 my-3" />
    // Bold line: **text**
    const boldMatch = line.match(/^\*\*(.+)\*\*$/)
    if (boldMatch) return <div key={i} className="text-sm font-semibold text-dark-200 mt-2">{boldMatch[1]}</div>
    if (line.trim() === '') return <div key={i} className="h-1.5" />
    // Inline bold rendering
    const parts = line.split(/(\*\*[^*]+\*\*)/)
    return (
      <div key={i} className="text-sm text-dark-400 leading-relaxed">
        {parts.map((p, j) => {
          const m = p.match(/^\*\*(.+)\*\*$/)
          return m ? <strong key={j} className="text-dark-200 font-semibold">{m[1]}</strong> : p
        })}
      </div>
    )
  })
}

export default function AnalysisPage() {
  const [tab, setTab] = useState('news')
  const [historyNews, setHistoryNews] = useState([])
  const [historyYt, setHistoryYt] = useState([])
  const [selectedIdNews, setSelectedIdNews] = useState(null)
  const [selectedIdYt, setSelectedIdYt] = useState(null)
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [reportLoading, setReportLoading] = useState(false)

  // 載入歷史清單
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const [nList, yList] = await Promise.all([
          radarAPI.listNlmReports('news'),
          radarAPI.listNlmReports('yt'),
        ])
        setHistoryNews(nList.data || [])
        setHistoryYt(yList.data || [])
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
        const selectedId = tab === 'news' ? selectedIdNews : selectedIdYt
        let res
        if (selectedId) {
          res = await radarAPI.getNlmReportById(selectedId)
        } else {
          res = tab === 'news'
            ? await radarAPI.getNlmReport()
            : await radarAPI.getNlmYtReport()
        }
        setReport(res.data)
      } catch {
        setReport(null)
      } finally {
        setLoading(false)
      }
    }
    loadReport()
  }, [tab, selectedIdNews, selectedIdYt])

  const history = tab === 'news' ? historyNews : historyYt
  const selectedId = tab === 'news' ? selectedIdNews : selectedIdYt
  const setSelectedId = tab === 'news' ? setSelectedIdNews : setSelectedIdYt
  const emptyMsg = tab === 'news' ? '尚無新聞分析報告' : '尚無 YouTube 分析報告'

  const fmtDate = (iso) => {
    if (!iso) return '—'
    return new Date(iso).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* Tab 切換 */}
      <div className="flex gap-2">
        {[
          ['news', '📰 新聞分析'],
          ['yt', '📺 YouTube 影片分析'],
        ].map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 rounded-lg font-medium text-sm transition-colors ${
              tab === key
                ? 'bg-primary-600 text-white'
                : 'bg-dark-800 text-dark-400 hover:text-white border border-dark-700'
            }`}
          >{label}</button>
        ))}
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
                  ? 'bg-primary-600/20 text-primary-400 border border-primary-600/40'
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
              <div className="text-4xl mb-3">📋</div>
              <div className="text-sm">{emptyMsg}</div>
              <div className="text-xs text-dark-600 mt-1">NotebookLM 腳本執行後報告將自動同步至此</div>
            </div>
          ) : (
            <div>
              {/* 報告 meta */}
              <div className="flex items-center justify-between pb-4 mb-4 border-b border-dark-700">
                <div className="text-xs text-dark-500 space-y-0.5">
                  <div>生成時間：<span className="text-dark-400">
                    {report.generated_at ? new Date(report.generated_at).toLocaleString('zh-TW') : '—'}
                  </span></div>
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
