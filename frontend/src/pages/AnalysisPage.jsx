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
  const [newsReport, setNewsReport] = useState(null)
  const [ytReport, setYtReport] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [nRes, yRes] = await Promise.all([
          radarAPI.getNlmReport(),
          radarAPI.getNlmYtReport(),
        ])
        setNewsReport(nRes.data)
        setYtReport(yRes.data)
      } catch {
        // 靜默失敗
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const report = tab === 'news' ? newsReport : ytReport
  const emptyMsg = tab === 'news' ? '尚無新聞分析報告' : '尚無 YouTube 分析報告'

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
