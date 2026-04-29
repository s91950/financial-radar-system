import { useState, useEffect, useCallback } from 'react'
import { toast } from 'react-hot-toast'
import { topicsAPI, resolveUrl, settingsAPI, copyToClipboard } from '../services/api'

// --- Severity helpers ---
const SEV_LABELS = { critical: '緊急', high: '高', medium: '中', low: '低' }
const SEV_STYLES = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high:     'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium:   'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low:      'bg-green-500/20 text-green-400 border-green-500/30',
}
function SeverityBadge({ severity }) {
  if (!severity) return null
  return (
    <span className={`shrink-0 mt-0.5 text-[10px] px-1.5 py-0.5 rounded border font-medium whitespace-nowrap ${SEV_STYLES[severity] || SEV_STYLES.low}`}>
      {SEV_LABELS[severity] || severity}
    </span>
  )
}

// Parse "(A OR B) (C OR D)" → [[A,B],[C,D]]; simple keyword → null
function parseGroupedKeyword(kw) {
  if (!kw.includes('(')) return null
  const matches = kw.match(/\(([^)]+)\)/g)
  if (!matches) return null
  return matches.map(m => {
    const inner = m.slice(1, -1)
    return inner.split(/\bOR\b/i).map(t => t.trim().replace(/^["']|["']$/g, '')).filter(Boolean)
  })
}

function computeCombinations(groups) {
  return groups.reduce((acc, g) => acc * g.length, 1)
}

function serializeGroups(groups) {
  return groups.filter(g => g.length > 0).map(g => `(${g.map(t => `"${t}"`).join(' OR ')})`).join(' ')
}

function GroupEditor({ draft, newTerms, setNewTerms, addTerm, removeTerm, addGroup, removeGroup }) {
  return (
    <div className="flex flex-wrap gap-3 items-start">
      {draft.map((terms, gi) => (
        <div key={gi} className="flex items-start gap-2">
          {gi > 0 && <span className="text-[10px] font-bold text-dark-500 mt-3 shrink-0 select-none">AND</span>}
          <div className="bg-dark-700 rounded-lg p-2 min-w-[90px]">
            <div className="flex flex-wrap gap-1 mb-1.5 min-h-[24px]">
              {terms.map((t, ti) => (
                <span key={ti} className="flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-primary-600/20 text-primary-400 border border-primary-500/30">
                  {t}
                  <button type="button" onClick={() => removeTerm(gi, ti)} className="hover:text-red-400 ml-0.5 leading-none">×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-1">
              <input
                value={newTerms[gi] || ''}
                onChange={e => setNewTerms(prev => prev.map((v, i) => i === gi ? e.target.value : v))}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTerm(gi) } }}
                placeholder="新增..."
                className="input text-xs py-0.5 px-1.5 flex-1 min-w-0 w-20"
              />
              <button type="button" onClick={() => addTerm(gi)} className="text-dark-400 hover:text-primary-400 text-sm px-1">+</button>
            </div>
            {draft.length > 1 && (
              <button type="button" onClick={() => removeGroup(gi)} className="text-[10px] text-dark-600 hover:text-red-400 mt-1.5 block">移除群組</button>
            )}
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={addGroup}
        className="self-start mt-1 text-xs px-2.5 py-1 rounded border border-dashed border-dark-600 text-dark-500 hover:text-primary-400 hover:border-primary-500/50 transition-colors whitespace-nowrap"
      >
        + AND 群組
      </button>
    </div>
  )
}

function GroupedKeywordCard({ groups, onSave, onRemove, onSplit, severityKws = {}, onAddToSeverity }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(() => groups.map(g => [...g]))
  const [newTerms, setNewTerms] = useState(() => groups.map(() => ''))
  const [activePickerTerm, setActivePickerTerm] = useState(null)

  useEffect(() => {
    if (!activePickerTerm) return
    const handler = () => setActivePickerTerm(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [activePickerTerm])

  const startEdit = () => { setDraft(groups.map(g => [...g])); setNewTerms(groups.map(() => '')); setEditing(true) }
  const cancel = () => setEditing(false)

  const addTerm = (gi) => {
    const t = (newTerms[gi] || '').trim()
    if (!t) return
    setDraft(prev => prev.map((g, i) => i === gi ? [...g, t] : g))
    setNewTerms(prev => prev.map((v, i) => i === gi ? '' : v))
  }
  const removeTerm = (gi, ti) => setDraft(prev => prev.map((g, i) => i === gi ? g.filter((_, j) => j !== ti) : g))
  const addGroup = () => { setDraft(prev => [...prev, []]); setNewTerms(prev => [...prev, '']) }
  const removeGroup = (gi) => { setDraft(prev => prev.filter((_, i) => i !== gi)); setNewTerms(prev => prev.filter((_, i) => i !== gi)) }

  const handleSave = () => {
    const cleaned = draft.filter(g => g.length > 0)
    if (cleaned.length === 0) { onRemove(); return }
    onSave(cleaned)
    setEditing(false)
  }

  if (!editing) {
    const combos = computeCombinations(groups)
    const items = groups.flatMap((terms, gi) =>
      gi === 0
        ? [{ t: 'g', key: `g-${gi}`, terms }]
        : [{ t: 'a', key: `a-${gi}` }, { t: 'g', key: `g-${gi}`, terms }]
    )
    return (
      <div className="flex items-stretch bg-dark-800 border border-dark-600 rounded-lg">
        {items.map(item => item.t === 'a' ? (
          <div key={item.key} className="flex items-center px-2 border-x border-dark-600 shrink-0">
            <span className="text-[10px] font-bold text-dark-500 select-none">AND</span>
          </div>
        ) : (
          <div key={item.key} className="flex-1 flex flex-wrap gap-1 p-2.5 min-w-0">
            {item.terms.map((t, ti) => {
              const isCrit = severityKws.critical?.includes(t)
              const isHigh = severityKws.high?.includes(t)
              const pickerOpen = activePickerTerm === t
              return (
                <div key={ti} className="relative">
                  {pickerOpen && (
                    <div
                      className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 bg-dark-800 border border-dark-600 rounded-lg shadow-xl p-1.5 flex items-center gap-1"
                      onClick={e => e.stopPropagation()}
                    >
                      <span className="text-[9px] text-dark-500 pr-1 border-r border-dark-600 mr-0.5 whitespace-nowrap">風險標記</span>
                      <button
                        onClick={() => onAddToSeverity?.('critical', t)}
                        className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                          isCrit ? 'bg-red-500/30 text-red-300 border-red-400/50' : 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/25'
                        }`}
                      >緊急</button>
                      <button
                        onClick={() => onAddToSeverity?.('high', t)}
                        className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                          isHigh ? 'bg-orange-500/30 text-orange-300 border-orange-400/50' : 'bg-orange-500/10 text-orange-400 border-orange-500/20 hover:bg-orange-500/25'
                        }`}
                      >高</button>
                    </div>
                  )}
                  <span
                    onClick={e => { e.stopPropagation(); setActivePickerTerm(pickerOpen ? null : t) }}
                    className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-primary-600/20 text-primary-400 border border-primary-500/30 whitespace-nowrap cursor-pointer select-none hover:bg-primary-600/30 transition-colors"
                  >
                    {isCrit && <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />}
                    {!isCrit && isHigh && <span className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" />}
                    {t}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
        <div className="flex flex-col items-end justify-between px-2 py-1.5 shrink-0 border-l border-dark-600 min-w-[40px]">
          <div className="flex items-center gap-1">
            <button onClick={startEdit} className="text-dark-500 hover:text-primary-400 transition-colors text-xs" title="編輯">✎</button>
            <button onClick={onRemove} className="text-dark-500 hover:text-red-400 transition-colors text-base leading-none">×</button>
          </div>
          <div className="flex flex-col items-end gap-0.5">
            {groups.length === 1 && onSplit && (
              <button onClick={() => onSplit(groups[0])} className="text-[10px] text-dark-400 hover:text-yellow-400 transition-colors whitespace-nowrap" title="拆成單一關鍵字">拆分</button>
            )}
            <span className="text-[10px] text-dark-500">{combos} 組</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-dark-800 border border-primary-500/40 rounded-lg p-3 w-full">
      <GroupEditor draft={draft} newTerms={newTerms} setNewTerms={setNewTerms}
        addTerm={addTerm} removeTerm={removeTerm} addGroup={addGroup} removeGroup={removeGroup} />
      <div className="flex gap-2 justify-end mt-3">
        <button type="button" onClick={cancel} className="btn-secondary text-xs py-1 px-3">取消</button>
        <button type="button" onClick={handleSave} className="btn-primary text-xs py-1 px-3">儲存</button>
      </div>
    </div>
  )
}

function NewGroupedBuilder({ onAdd, onClose }) {
  const [draft, setDraft] = useState([[]])
  const [newTerms, setNewTerms] = useState([''])

  const addTerm = (gi) => {
    const t = (newTerms[gi] || '').trim()
    if (!t) return
    setDraft(prev => prev.map((g, i) => i === gi ? [...g, t] : g))
    setNewTerms(prev => prev.map((v, i) => i === gi ? '' : v))
  }
  const removeTerm = (gi, ti) => setDraft(prev => prev.map((g, i) => i === gi ? g.filter((_, j) => j !== ti) : g))
  const addGroup = () => { setDraft(prev => [...prev, []]); setNewTerms(prev => [...prev, '']) }
  const removeGroup = (gi) => { setDraft(prev => prev.filter((_, i) => i !== gi)); setNewTerms(prev => prev.filter((_, i) => i !== gi)) }

  const handleAdd = () => {
    const cleaned = draft.filter(g => g.length > 0)
    if (cleaned.length === 0) { onClose(); return }
    onAdd(cleaned)
  }

  return (
    <div className="bg-dark-800 border border-primary-500/40 rounded-lg p-3 w-full">
      <div className="text-xs text-dark-400 mb-2 font-medium">新增布林組合</div>
      <GroupEditor draft={draft} newTerms={newTerms} setNewTerms={setNewTerms}
        addTerm={addTerm} removeTerm={removeTerm} addGroup={addGroup} removeGroup={removeGroup} />
      <div className="flex gap-2 justify-end mt-3">
        <button type="button" onClick={onClose} className="btn-secondary text-xs py-1 px-3">取消</button>
        <button type="button" onClick={handleAdd} className="btn-primary text-xs py-1 px-3">新增</button>
      </div>
    </div>
  )
}

// --- TopicModal: create / edit topic ---
function TopicModal({ topic, onClose, onSave }) {
  const [name, setName] = useState(topic?.name || '')
  const [simpleKws, setSimpleKws] = useState(() => (topic?.keywords || []).filter(k => !k.includes('(')))
  const [groupedEntries, setGroupedEntries] = useState(() =>
    (topic?.keywords || []).filter(k => k.includes('(')).map(k => ({ id: Math.random(), groups: parseGroupedKeyword(k) || [] }))
  )
  const [kw, setKw] = useState('')
  const [showBuilder, setShowBuilder] = useState(false)
  const [saving, setSaving] = useState(false)

  const addKeyword = () => {
    const v = kw.trim()
    if (v && !simpleKws.includes(v)) setSimpleKws(prev => [...prev, v])
    setKw('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    const allKeywords = [
      ...simpleKws,
      ...groupedEntries.map(e => serializeGroups(e.groups)).filter(Boolean),
    ]
    try {
      await onSave({ name: name.trim(), keywords: allKeywords })
      onClose()
    } catch {
      toast.error('儲存失敗')
    }
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="card w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <h3 className="font-bold text-lg mb-4">{topic ? '編輯主題' : '新增主題'}</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-dark-400 mb-1">主題名稱</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：台積電法說"
              className="input"
              autoFocus
            />
          </div>

          {/* Simple keywords */}
          <div>
            <label className="block text-sm text-dark-400 mb-1">單一關鍵字</label>
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                value={kw}
                onChange={(e) => setKw(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addKeyword() } }}
                placeholder="輸入後按 Enter 或點新增"
                className="input flex-1 text-sm"
              />
              <button type="button" onClick={addKeyword} className="btn-secondary text-sm px-3">新增</button>
            </div>
            <div className="flex flex-wrap gap-2 min-h-8">
              {simpleKws.map(k => (
                <span key={k} className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-primary-600/20 text-primary-400 border border-primary-500/30">
                  {k}
                  <button type="button" onClick={() => setSimpleKws(prev => prev.filter(x => x !== k))} className="hover:text-red-400 ml-0.5">×</button>
                </span>
              ))}
              {simpleKws.length === 0 && <span className="text-xs text-dark-600">尚未新增</span>}
            </div>
          </div>

          {/* Boolean groups */}
          <div>
            <label className="block text-sm text-dark-400 mb-2">布林組合關鍵字</label>
            <div className="space-y-2">
              {groupedEntries.map(entry => (
                <GroupedKeywordCard
                  key={entry.id}
                  groups={entry.groups}
                  onSave={(newGroups) => setGroupedEntries(prev => prev.map(e => e.id === entry.id ? { ...e, groups: newGroups } : e))}
                  onRemove={() => setGroupedEntries(prev => prev.filter(e => e.id !== entry.id))}
                  onSplit={(terms) => {
                    setGroupedEntries(prev => prev.filter(e => e.id !== entry.id))
                    setSimpleKws(prev => [...prev, ...terms.filter(t => !prev.includes(t))])
                  }}
                />
              ))}
              {showBuilder ? (
                <NewGroupedBuilder
                  onAdd={(groups) => { setGroupedEntries(prev => [...prev, { id: Date.now(), groups }]); setShowBuilder(false) }}
                  onClose={() => setShowBuilder(false)}
                />
              ) : (
                <button
                  type="button"
                  onClick={() => setShowBuilder(true)}
                  className="text-xs px-3 py-1.5 rounded border border-dashed border-dark-600 text-dark-500 hover:text-primary-400 hover:border-primary-500/50 transition-colors"
                >
                  + 新增布林組合
                </button>
              )}
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <button type="submit" disabled={saving || !name.trim()} className="btn-primary flex-1">
              {saving ? '儲存中...' : '儲存'}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary flex-1">取消</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// --- Main Page ---
export default function SearchPage() {
  const [topics, setTopics] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [topicData, setTopicData] = useState(null)   // { topic, articles, stats }
  const [loadingTopics, setLoadingTopics] = useState(true)
  const [loadingArticles, setLoadingArticles] = useState(false)
  const [searching, setSearching] = useState(false)
  const [hoursBack, setHoursBack] = useState(24)
  const [useCustomHours, setUseCustomHours] = useState(false)
  const [customHoursInput, setCustomHoursInput] = useState('48')
  const [showModal, setShowModal] = useState(false)
  const [editTopic, setEditTopic] = useState(null)
  const [copiedUrl, setCopiedUrl] = useState(null)
  const [selectedUrls, setSelectedUrls] = useState(new Set())
  const [severityKws, setSeverityKws] = useState({ critical: [], high: [] })
  const [activePicker, setActivePicker] = useState(null)

  // Filter & sort
  const [filterSeverity, setFilterSeverity] = useState('all')
  const [filterSource, setFilterSource] = useState('all')
  const [filterKeyword, setFilterKeyword] = useState('')
  const [sortOrder, setSortOrder] = useState('desc')

  const loadTopics = useCallback(async () => {
    try {
      const { data } = await topicsAPI.getTopics()
      setTopics(data)
    } catch {
      toast.error('載入主題失敗')
    }
    setLoadingTopics(false)
  }, [])

  useEffect(() => { loadTopics() }, [loadTopics])

  useEffect(() => {
    settingsAPI.getSeverityKeywords().then(({ data }) => {
      setSeverityKws({ critical: data.critical || [], high: data.high || [] })
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!activePicker) return
    const handler = () => setActivePicker(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [activePicker])

  const handleAddToSeverity = async (level, keyword) => {
    const updated = {
      critical: severityKws.critical.includes(keyword) && level === 'critical'
        ? severityKws.critical.filter(k => k !== keyword)
        : level === 'critical' ? [...severityKws.critical, keyword] : severityKws.critical,
      high: severityKws.high.includes(keyword) && level === 'high'
        ? severityKws.high.filter(k => k !== keyword)
        : level === 'high' ? [...severityKws.high, keyword] : severityKws.high,
    }
    setSeverityKws(updated)
    try {
      await settingsAPI.updateSeverityKeywords({ critical: updated.critical, high: updated.high })
      const label = level === 'critical' ? '緊急' : '高'
      const isAdd = level === 'critical' ? updated.critical.includes(keyword) : updated.high.includes(keyword)
      toast.success(isAdd ? `"${keyword}" 已標記為${label}風險` : `已移除 "${keyword}" 的${label}標記`)
    } catch {
      toast.error('儲存失敗')
    }
  }

  const loadArticles = useCallback(async (id) => {
    if (!id) return
    setLoadingArticles(true)
    try {
      const { data } = await topicsAPI.getArticles(id)
      setTopicData(data)
    } catch {
      toast.error('載入文章失敗')
    }
    setLoadingArticles(false)
  }, [])

  const handleSelectTopic = (id) => {
    setSelectedId(id)
    setSelectedUrls(new Set())
    setFilterSeverity('all')
    setFilterSource('all')
    setFilterKeyword('')
    setSortOrder('desc')
    loadArticles(id)
  }

  const handleSaveTopic = async (payload) => {
    if (editTopic) {
      const { data } = await topicsAPI.updateTopic(editTopic.id, payload)
      setTopics(prev => prev.map(t => t.id === editTopic.id ? data : t))
      if (selectedId === editTopic.id && topicData) {
        setTopicData(prev => ({ ...prev, topic: data }))
      }
      setEditTopic(null)
    } else {
      const { data } = await topicsAPI.createTopic(payload)
      setTopics(prev => [data, ...prev])
    }
  }

  const handleDeleteTopic = async (id, e) => {
    e.stopPropagation()
    if (!confirm('確定刪除此主題及所有相關文章？')) return
    try {
      await topicsAPI.deleteTopic(id)
      setTopics(prev => prev.filter(t => t.id !== id))
      if (selectedId === id) {
        setSelectedId(null)
        setTopicData(null)
      }
    } catch {
      toast.error('刪除失敗')
    }
  }

  const handleEditTopic = (topic, e) => {
    e.stopPropagation()
    setEditTopic(topic)
    setShowModal(true)
  }

  const handleSearch = async () => {
    if (!selectedId) return
    setSearching(true)
    try {
      const { data } = await topicsAPI.searchAndImport(selectedId, { hours_back: hoursBack })
      toast.success(`已匯入 ${data.imported} 篇新文章`)
      if (data.imported > 0) {
        await loadArticles(selectedId)
        await loadTopics()
      }
    } catch {
      toast.error('搜尋失敗')
    }
    setSearching(false)
  }

  const handleDeleteArticle = async (articleId) => {
    try {
      await topicsAPI.deleteArticle(selectedId, articleId)
      setTopicData(prev => ({
        ...prev,
        articles: prev.articles.filter(a => a.id !== articleId),
        stats: { ...prev.stats, total: prev.stats.total - 1 },
      }))
    } catch {
      toast.error('刪除失敗')
    }
  }

  const handleCopy = async (url) => {
    const finalUrl = await resolveUrl(url)
    copyToClipboard(finalUrl)
    setCopiedUrl(url)
    toast.success('已複製連結')
    setTimeout(() => setCopiedUrl(null), 2000)
  }

  // --- Compute filtered + sorted articles ---
  let displayArticles = topicData?.articles || []
  if (filterSeverity !== 'all') {
    displayArticles = displayArticles.filter(a => a.severity === filterSeverity)
  }
  if (filterSource !== 'all') {
    displayArticles = displayArticles.filter(a => a.add_source === filterSource)
  }
  if (filterKeyword) {
    const kw = filterKeyword.toLowerCase()
    displayArticles = displayArticles.filter(a =>
      a.title?.toLowerCase().includes(kw) || a.source?.toLowerCase().includes(kw)
    )
  }
  displayArticles = [...displayArticles].sort((a, b) => {
    const da = new Date(a.published_at || a.added_at || 0)
    const db = new Date(b.published_at || b.added_at || 0)
    return sortOrder === 'desc' ? db - da : da - db
  })

  const handleToggleSelectAll = () => {
    const allUrls = displayArticles.map(a => a.source_url).filter(Boolean)
    if (selectedUrls.size === allUrls.length && allUrls.length > 0) {
      setSelectedUrls(new Set())
    } else {
      setSelectedUrls(new Set(allUrls))
    }
  }

  const handleCopySelected = async () => {
    const urls = [...selectedUrls]
    const toastId = toast.loading(`解析 ${urls.length} 個連結...`)
    const resolved = await Promise.all(urls.map(u => resolveUrl(u)))
    copyToClipboard(resolved.join('\n'))
    toast.dismiss(toastId)
    toast.success(`已複製 ${urls.length} 個連結`)
  }

  const selectedTopic = topics.find(t => t.id === selectedId)

  const hasFilter = filterSeverity !== 'all' || filterSource !== 'all' || filterKeyword || sortOrder !== 'desc'

  return (
    <div className="flex flex-col md:flex-row gap-3 md:gap-4 h-auto md:h-[calc(100vh-8rem)]">
      {/* Left sidebar: topic list */}
      <div className="w-full md:w-64 shrink-0 flex flex-col gap-2">
        <button
          onClick={() => { setEditTopic(null); setShowModal(true) }}
          className="btn-primary w-full flex items-center justify-center gap-2 py-2.5"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          新增主題
        </button>

        <div className="card flex-1 overflow-x-auto md:overflow-x-hidden overflow-y-auto p-2 space-y-1 md:space-y-1 flex md:block gap-2 md:gap-0">
          {loadingTopics ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-500" />
            </div>
          ) : topics.length === 0 ? (
            <p className="text-xs text-dark-500 text-center py-6 px-2">尚未建立任何主題，點擊上方「新增主題」開始追蹤</p>
          ) : (
            topics.map(topic => (
              <div
                key={topic.id}
                onClick={() => handleSelectTopic(topic.id)}
                className={`group flex items-center justify-between p-2.5 rounded-lg cursor-pointer transition-colors shrink-0 md:shrink ${
                  selectedId === topic.id
                    ? 'bg-primary-600/20 border border-primary-500/30'
                    : 'hover:bg-dark-800/60'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${topic.is_active ? 'bg-green-400' : 'bg-dark-600'}`} />
                    <span className="text-sm font-medium text-gray-200 truncate">{topic.name}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5 pl-3.5">
                    <span className="text-xs text-dark-400">{topic.article_count} 篇</span>
                  </div>
                </div>
                <div className={`flex items-center gap-1 shrink-0 transition-opacity ${selectedId === topic.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>
                  <button
                    onClick={(e) => handleEditTopic(topic, e)}
                    className="p-1 text-dark-500 hover:text-primary-400 rounded"
                    title="編輯"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                    </svg>
                  </button>
                  <button
                    onClick={(e) => handleDeleteTopic(topic.id, e)}
                    className="p-1 text-dark-500 hover:text-red-400 rounded"
                    title="刪除"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                    </svg>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Right panel: topic detail */}
      <div className="flex-1 flex flex-col gap-3 min-w-0 overflow-hidden">
        {!selectedTopic ? (
          <div className="card flex-1 flex items-center justify-center text-center">
            <div>
              <svg className="w-12 h-12 text-dark-700 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" />
              </svg>
              <p className="text-dark-400 text-sm">選擇左側主題，或新增主題開始追蹤</p>
            </div>
          </div>
        ) : (
          <>
            {/* Topic header */}
            <div className="card py-3 px-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="font-bold text-lg">{selectedTopic.name}</h2>
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${
                      selectedTopic.is_active
                        ? 'text-green-400 border-green-500/30 bg-green-500/10'
                        : 'text-dark-400 border-dark-600 bg-dark-800'
                    }`}>
                      {selectedTopic.is_active ? '追蹤中' : '已停用'}
                    </span>
                  </div>
                  {(() => {
                    const kws = selectedTopic.keywords || []
                    const simple = kws.filter(k => !k.includes('('))
                    const grouped = kws.filter(k => k.includes('('))
                    if (kws.length === 0) return <span className="text-xs text-dark-600 mt-1 block">尚未設定關鍵字</span>
                    return (
                      <div className="mt-2 space-y-1.5">
                        {simple.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {simple.map(kw => {
                              const isCrit = severityKws.critical.includes(kw)
                              const isHigh = severityKws.high.includes(kw)
                              const pickerOpen = activePicker === kw
                              return (
                                <div key={kw} className="relative">
                                  {pickerOpen && (
                                    <div
                                      className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 bg-dark-800 border border-dark-600 rounded-lg shadow-xl p-1.5 flex items-center gap-1"
                                      onClick={e => e.stopPropagation()}
                                    >
                                      <span className="text-[9px] text-dark-500 pr-1 border-r border-dark-600 mr-0.5 whitespace-nowrap">風險標記</span>
                                      <button
                                        onClick={() => handleAddToSeverity('critical', kw)}
                                        className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                                          isCrit ? 'bg-red-500/30 text-red-300 border-red-400/50' : 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/25'
                                        }`}
                                      >緊急</button>
                                      <button
                                        onClick={() => handleAddToSeverity('high', kw)}
                                        className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                                          isHigh ? 'bg-orange-500/30 text-orange-300 border-orange-400/50' : 'bg-orange-500/10 text-orange-400 border-orange-500/20 hover:bg-orange-500/25'
                                        }`}
                                      >高</button>
                                    </div>
                                  )}
                                  <span
                                    onClick={e => { e.stopPropagation(); setActivePicker(pickerOpen ? null : kw) }}
                                    className="flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full bg-dark-700 text-dark-300 border border-dark-600 cursor-pointer select-none hover:bg-dark-600 transition-colors"
                                  >
                                    {isCrit && <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />}
                                    {!isCrit && isHigh && <span className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" />}
                                    {kw}
                                  </span>
                                </div>
                              )
                            })}
                          </div>
                        )}
                        {grouped.length > 0 && (
                          <div className="flex flex-col gap-1">
                            {grouped.map(kw => {
                              const groups = parseGroupedKeyword(kw)
                              if (!groups) return null
                              const combos = computeCombinations(groups)
                              const items = groups.flatMap((terms, gi) =>
                                gi === 0
                                  ? [{ t: 'g', key: `g-${gi}`, terms }]
                                  : [{ t: 'a', key: `a-${gi}` }, { t: 'g', key: `g-${gi}`, terms }]
                              )
                              return (
                                <div key={kw} className="flex items-stretch bg-dark-800 border border-dark-600 rounded-lg">
                                  {items.map(item => item.t === 'a' ? (
                                    <div key={item.key} className="flex items-center px-1.5 border-x border-dark-600 shrink-0">
                                      <span className="text-[10px] font-bold text-dark-500 select-none">AND</span>
                                    </div>
                                  ) : (
                                    <div key={item.key} className="flex-1 flex flex-wrap gap-1 p-1.5 min-w-0">
                                      {item.terms.map((t, ti) => {
                                        const isCrit = severityKws.critical.includes(t)
                                        const isHigh = severityKws.high.includes(t)
                                        const pickerOpen = activePicker === t
                                        return (
                                          <div key={ti} className="relative">
                                            {pickerOpen && (
                                              <div
                                                className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 bg-dark-800 border border-dark-600 rounded-lg shadow-xl p-1.5 flex items-center gap-1"
                                                onClick={e => e.stopPropagation()}
                                              >
                                                <span className="text-[9px] text-dark-500 pr-1 border-r border-dark-600 mr-0.5 whitespace-nowrap">風險標記</span>
                                                <button
                                                  onClick={() => handleAddToSeverity('critical', t)}
                                                  className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                                                    isCrit ? 'bg-red-500/30 text-red-300 border-red-400/50' : 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/25'
                                                  }`}
                                                >緊急</button>
                                                <button
                                                  onClick={() => handleAddToSeverity('high', t)}
                                                  className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                                                    isHigh ? 'bg-orange-500/30 text-orange-300 border-orange-400/50' : 'bg-orange-500/10 text-orange-400 border-orange-500/20 hover:bg-orange-500/25'
                                                  }`}
                                                >高</button>
                                              </div>
                                            )}
                                            <span
                                              onClick={e => { e.stopPropagation(); setActivePicker(pickerOpen ? null : t) }}
                                              className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-primary-600/20 text-primary-400 border border-primary-500/30 whitespace-nowrap cursor-pointer select-none hover:bg-primary-600/30 transition-colors"
                                            >
                                              {isCrit && <span className="w-1 h-1 rounded-full bg-red-400 shrink-0" />}
                                              {!isCrit && isHigh && <span className="w-1 h-1 rounded-full bg-orange-400 shrink-0" />}
                                              {t}
                                            </span>
                                          </div>
                                        )
                                      })}
                                    </div>
                                  ))}
                                  <div className="flex items-center px-1.5 border-l border-dark-600 shrink-0">
                                    <span className="text-[10px] text-dark-500 whitespace-nowrap">{combos} 組</span>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })()}
                </div>

                {/* Manual search controls */}
                <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
                  <select
                    value={useCustomHours ? 'custom' : hoursBack}
                    onChange={(e) => {
                      if (e.target.value === 'custom') {
                        setUseCustomHours(true)
                      } else {
                        setUseCustomHours(false)
                        setHoursBack(Number(e.target.value))
                      }
                    }}
                    className="input text-sm py-1.5 w-32"
                  >
                    <option value={3}>近 3 小時</option>
                    <option value={6}>近 6 小時</option>
                    <option value={12}>近 12 小時</option>
                    <option value={24}>近 24 小時</option>
                    <option value={48}>近 48 小時</option>
                    <option value={72}>近 3 天</option>
                    <option value={168}>近 7 天</option>
                    <option value="custom">自訂...</option>
                  </select>
                  {useCustomHours && (
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        value={customHoursInput}
                        onChange={(e) => {
                          setCustomHoursInput(e.target.value)
                          const v = parseInt(e.target.value)
                          if (v > 0) setHoursBack(v)
                        }}
                        placeholder="小時"
                        min="1"
                        className="input text-sm py-1.5 w-16 text-center"
                      />
                      <span className="text-xs text-dark-400 whitespace-nowrap">小時</span>
                    </div>
                  )}
                  <button
                    onClick={handleSearch}
                    disabled={searching || !selectedTopic.keywords?.length}
                    className="btn-primary text-sm py-1.5 px-4 flex items-center gap-1.5 whitespace-nowrap"
                    title={!selectedTopic.keywords?.length ? '請先設定關鍵字' : ''}
                  >
                    {searching ? (
                      <>
                        <div className="animate-spin rounded-full h-3.5 w-3.5 border-b-2 border-white" />
                        搜尋中...
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                        </svg>
                        搜尋並匯入
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

            {/* Stats bar */}
            {topicData?.stats && (
              <div className="flex items-center gap-3 px-1 text-xs text-dark-400">
                <span>共 <span className="text-gray-300 font-medium">{topicData.stats.total}</span> 篇</span>
                {displayArticles.length !== topicData.stats.total && (
                  <span className="text-primary-400">（篩選後 {displayArticles.length} 篇）</span>
                )}
                <span className="text-dark-700">|</span>
                <span>雷達自動匯入：<span className="text-green-400 font-medium">{topicData.stats.radar}</span></span>
                <span className="text-dark-700">|</span>
                <span>手動搜尋：<span className="text-blue-400 font-medium">{topicData.stats.manual}</span></span>

                <div className="flex-1" />

                {/* Select all toggle */}
                {displayArticles.length > 0 && (
                  <button
                    onClick={handleToggleSelectAll}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border transition-colors ${
                      selectedUrls.size > 0
                        ? 'bg-primary-600/20 text-primary-400 border-primary-500/30'
                        : 'bg-dark-800 text-dark-400 border-dark-600 hover:text-primary-400'
                    }`}
                  >
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    {selectedUrls.size > 0 ? `已選 ${selectedUrls.size} 篇` : '全選'}
                  </button>
                )}

                {/* Copy selected */}
                {selectedUrls.size > 0 && (
                  <button
                    onClick={handleCopySelected}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border bg-primary-600/20 text-primary-400 border-primary-500/30 hover:bg-primary-600/30 transition-colors"
                  >
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    複製連結
                  </button>
                )}
              </div>
            )}

            {/* Filter & sort bar */}
            {topicData && topicData.articles.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 px-1">
                {/* Severity pills */}
                <div className="flex items-center gap-1">
                  {[
                    { v: 'all',      label: '全部風險' },
                    { v: 'critical', label: '緊急', cls: 'text-red-400' },
                    { v: 'high',     label: '高',   cls: 'text-orange-400' },
                    { v: 'medium',   label: '中',   cls: 'text-yellow-400' },
                    { v: 'low',      label: '低',   cls: 'text-green-400' },
                  ].map(({ v, label, cls }) => (
                    <button
                      key={v}
                      onClick={() => setFilterSeverity(v)}
                      className={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
                        filterSeverity === v
                          ? 'bg-primary-600/30 text-primary-400 border-primary-500/50'
                          : `bg-dark-800 border-dark-600 ${cls || 'text-dark-400'} hover:border-dark-500`
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                <span className="text-dark-700">|</span>

                {/* Source filter */}
                <div className="flex items-center gap-1">
                  {[
                    { v: 'all',    label: '全部來源' },
                    { v: 'radar',  label: '雷達', cls: 'text-green-400' },
                    { v: 'manual', label: '手動', cls: 'text-blue-400' },
                  ].map(({ v, label, cls }) => (
                    <button
                      key={v}
                      onClick={() => setFilterSource(v)}
                      className={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
                        filterSource === v
                          ? 'bg-primary-600/30 text-primary-400 border-primary-500/50'
                          : `bg-dark-800 border-dark-600 ${cls || 'text-dark-400'} hover:border-dark-500`
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                <div className="flex-1" />

                {/* Keyword search */}
                <input
                  type="text"
                  value={filterKeyword}
                  onChange={(e) => setFilterKeyword(e.target.value)}
                  placeholder="搜尋標題..."
                  className="input text-xs py-1 px-2.5 w-36"
                />

                {/* Sort order */}
                <button
                  onClick={() => setSortOrder(v => v === 'desc' ? 'asc' : 'desc')}
                  className={`text-xs px-2.5 py-1 rounded-full border flex items-center gap-1 transition-colors ${
                    sortOrder !== 'desc'
                      ? 'bg-primary-600/20 text-primary-400 border-primary-500/30'
                      : 'bg-dark-800 border-dark-600 text-dark-400 hover:border-dark-500'
                  }`}
                >
                  {sortOrder === 'desc' ? '最新優先' : '最舊優先'}
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d={sortOrder === 'desc' ? 'M19 9l-7 7-7-7' : 'M5 15l7-7 7 7'} />
                  </svg>
                </button>

                {/* Reset filters */}
                {hasFilter && (
                  <button
                    onClick={() => { setFilterSeverity('all'); setFilterSource('all'); setFilterKeyword(''); setSortOrder('desc') }}
                    className="text-xs px-2 py-1 rounded text-dark-500 hover:text-red-400 transition-colors"
                    title="清除篩選"
                  >
                    ✕ 清除
                  </button>
                )}
              </div>
            )}

            {/* Articles list */}
            <div className="card flex-1 overflow-y-auto p-3">
              {loadingArticles ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500" />
                </div>
              ) : !topicData || topicData.articles.length === 0 ? (
                <div className="text-center py-12 text-dark-500">
                  <svg className="w-10 h-10 mx-auto mb-3 text-dark-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                      d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                  </svg>
                  <p className="text-sm">尚無文章</p>
                  <p className="text-xs mt-1">等待雷達自動掃描，或點擊「搜尋並匯入」手動獲取</p>
                </div>
              ) : displayArticles.length === 0 ? (
                <div className="text-center py-12 text-dark-500">
                  <p className="text-sm">篩選條件下無結果</p>
                  <button
                    onClick={() => { setFilterSeverity('all'); setFilterSource('all'); setFilterKeyword(''); setSortOrder('desc') }}
                    className="text-xs text-primary-400 mt-2 hover:underline"
                  >
                    清除篩選
                  </button>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {displayArticles.map(article => (
                    <div
                      key={article.id}
                      className={`group flex items-start gap-3 p-3 rounded-lg transition-colors ${
                        article.source_url && selectedUrls.has(article.source_url)
                          ? 'bg-primary-600/10 border border-primary-500/20'
                          : 'bg-dark-900 hover:bg-dark-800/60'
                      }`}
                    >
                      {/* Checkbox */}
                      <input
                        type="checkbox"
                        checked={!!(article.source_url && selectedUrls.has(article.source_url))}
                        onChange={() => {
                          if (!article.source_url) return
                          setSelectedUrls(prev => {
                            const next = new Set(prev)
                            if (next.has(article.source_url)) next.delete(article.source_url)
                            else next.add(article.source_url)
                            return next
                          })
                        }}
                        disabled={!article.source_url}
                        className="mt-0.5 shrink-0 rounded border-dark-600 bg-dark-800 text-primary-500 focus:ring-primary-500 w-3.5 h-3.5 cursor-pointer"
                      />

                      {/* Source badge */}
                      <span className={`shrink-0 mt-0.5 text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        article.add_source === 'radar'
                          ? 'bg-green-500/15 text-green-400 border border-green-500/25'
                          : 'bg-blue-500/15 text-blue-400 border border-blue-500/25'
                      }`}>
                        {article.add_source === 'radar' ? '雷達' : '手動'}
                      </span>

                      {/* Severity badge */}
                      <SeverityBadge severity={article.severity} />

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        {article.source_url ? (
                          <a
                            href={article.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm font-medium text-gray-200 hover:text-primary-400 transition-colors line-clamp-2"
                          >
                            {article.title}
                          </a>
                        ) : (
                          <p className="text-sm font-medium text-gray-300 line-clamp-2">{article.title}</p>
                        )}
                        <div className="flex items-center gap-2 mt-1 text-xs text-dark-500">
                          {article.source && <span>{article.source}</span>}
                          {article.source && article.published_at && <span>·</span>}
                          {article.published_at && (
                            <span>{new Date(article.published_at).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                          )}
                        </div>
                      </div>

                      {/* Action buttons */}
                      <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        {article.source_url && (
                          <a
                            href={article.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1.5 text-dark-500 hover:text-primary-400 rounded hover:bg-dark-700 transition-colors"
                            title="開啟連結"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                            </svg>
                          </a>
                        )}
                        {article.source_url && (
                          <button
                            onClick={() => handleCopy(article.source_url)}
                            className="p-1.5 text-dark-500 hover:text-primary-400 rounded hover:bg-dark-700 transition-colors"
                            title="複製連結"
                          >
                            {copiedUrl === article.source_url ? (
                              <svg className="w-4 h-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                              </svg>
                            ) : (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                              </svg>
                            )}
                          </button>
                        )}
                        <button
                          onClick={() => handleDeleteArticle(article.id)}
                          className="p-1.5 text-dark-500 hover:text-red-400 rounded hover:bg-dark-700 transition-colors"
                          title="移除"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <TopicModal
          topic={editTopic}
          onClose={() => { setShowModal(false); setEditTopic(null) }}
          onSave={handleSaveTopic}
        />
      )}
    </div>
  )
}
