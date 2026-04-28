import { useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import api from '../services/api'

const CATEGORIES = [
  { value: 'feature', label: '功能建議', icon: '💡' },
  { value: 'bug', label: '問題回報', icon: '🐛' },
  { value: 'ui', label: '介面改善', icon: '🎨' },
  { value: 'general', label: '其他意見', icon: '💬' },
]

export default function FeedbackPage() {
  const [category, setCategory] = useState('feature')
  const [content, setContent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [feedbacks, setFeedbacks] = useState([])
  const [loading, setLoading] = useState(true)

  const loadFeedbacks = async () => {
    try {
      const { data } = await api.get('/feedback/')
      setFeedbacks(data)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { loadFeedbacks() }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!content.trim()) return
    setSubmitting(true)
    try {
      await api.post('/feedback/', { category, content: content.trim() })
      toast.success('感謝您的回饋！')
      setContent('')
      loadFeedbacks()
    } catch {
      toast.error('提交失敗，請稍後再試')
    }
    setSubmitting(false)
  }

  const handleDelete = async (id) => {
    try {
      await api.delete(`/feedback/${id}`)
      setFeedbacks(prev => prev.filter(f => f.id !== id))
    } catch { /* ignore */ }
  }

  const catLabel = (v) => CATEGORIES.find(c => c.value === v)?.label || v
  const catIcon = (v) => CATEGORIES.find(c => c.value === v)?.icon || '💬'

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* 提交表單 */}
      <div className="card">
        <h3 className="text-base font-semibold text-gray-200 mb-4">提交改善建議</h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 類別選擇 */}
          <div className="flex gap-2 flex-wrap">
            {CATEGORIES.map(c => (
              <button
                key={c.value}
                type="button"
                onClick={() => setCategory(c.value)}
                className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors border ${
                  category === c.value
                    ? 'bg-primary-600/20 text-primary-400 border-primary-500/40'
                    : 'bg-dark-800 text-dark-400 border-dark-700 hover:border-dark-500 hover:text-dark-200'
                }`}
              >
                {c.icon} {c.label}
              </button>
            ))}
          </div>

          {/* 內容輸入 */}
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="請描述您的建議或遇到的問題..."
            rows={5}
            className="input w-full resize-y text-sm leading-relaxed"
          />

          {/* 提交按鈕 */}
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={submitting || !content.trim()}
              className="btn-primary flex items-center gap-2"
            >
              {submitting && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />}
              提交回饋
            </button>
          </div>
        </form>
      </div>

      {/* 歷史回饋 */}
      {!loading && feedbacks.length > 0 && (
        <div className="card">
          <h3 className="text-base font-semibold text-gray-200 mb-4">
            歷史回饋
            <span className="text-sm text-dark-500 font-normal ml-2">({feedbacks.length})</span>
          </h3>

          <div className="space-y-3">
            {feedbacks.map(fb => (
              <div key={fb.id} className="p-3 rounded-lg bg-dark-800/50 border border-dark-700 group">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{catIcon(fb.category)}</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-dark-700 text-dark-300 font-medium">
                      {catLabel(fb.category)}
                    </span>
                    <span className="text-xs text-dark-500">
                      {fb.created_at && new Date(fb.created_at).toLocaleString('zh-TW')}
                    </span>
                  </div>
                  <button
                    onClick={() => handleDelete(fb.id)}
                    className="text-dark-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                    title="刪除"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <p className="text-sm text-gray-300 whitespace-pre-wrap">{fb.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
