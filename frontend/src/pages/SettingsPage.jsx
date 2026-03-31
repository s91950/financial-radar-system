import { useCallback, useEffect, useState } from 'react'
import { settingsAPI } from '../services/api'
import { toast } from 'react-hot-toast'

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

// Shared inner editing layout used by both the card and the builder
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

export default function SettingsPage() {
  const [sources, setSources] = useState([])
  const [notifications, setNotifications] = useState([])
  const [sheetsStatus, setSheetsStatus] = useState(null)
  const [lineStatus, setLineStatus] = useState(null)
  const [sheetsTestResult, setSheetsTestResult] = useState(null)
  const [sheetsTesting, setSheetsTesting] = useState(false)
  const [loading, setLoading] = useState(true)
  const [newSource, setNewSource] = useState({ name: '', type: 'rss', url: '', keywords: '' })
  const [showAddSource, setShowAddSource] = useState(false)
  const [aiModel, setAiModel] = useState(null)
  const [switchingAI, setSwitchingAI] = useState(false)
  const [radarTopics, setRadarTopics] = useState([])
  const [radarHoursBack, setRadarHoursBack] = useState(24)
  const [radarIntervalMinutes, setRadarIntervalMinutes] = useState(5)
  const [newTopic, setNewTopic] = useState('')
  const [savingTopics, setSavingTopics] = useState(false)
  const [sourcesExpanded, setSourcesExpanded] = useState(false)
  const [expandedSources, setExpandedSources] = useState(new Set())
  const [severityKws, setSeverityKws] = useState({ critical: [], high: [], default_critical: [], default_high: [] })
  const [newCritKw, setNewCritKw] = useState('')
  const [newHighKw, setNewHighKw] = useState('')
  const [savingSeverity, setSavingSeverity] = useState(false)
  const [showGroupBuilder, setShowGroupBuilder] = useState(false)
  const [activeTopicPicker, setActiveTopicPicker] = useState(null)
  const [discordWebhookInput, setDiscordWebhookInput] = useState('')
  const [savingDiscord, setSavingDiscord] = useState(false)

  const toggleSourceExpand = (id) => {
    setExpandedSources(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const loadSettings = useCallback(async () => {
    try {
      const [srcRes, notifRes, sheetsRes, aiRes, topicsRes, sevRes, lineRes] = await Promise.all([
        settingsAPI.getSources(),
        settingsAPI.getNotificationSettings(),
        settingsAPI.getGoogleSheetsStatus(),
        settingsAPI.getAIModel(),
        settingsAPI.getRadarTopics(),
        settingsAPI.getSeverityKeywords(),
        settingsAPI.getLineStatus(),
      ])
      setSources(srcRes.data)
      setNotifications(notifRes.data)
      setSheetsStatus(sheetsRes.data)
      setLineStatus(lineRes.data)
      const discordNotif = notifRes.data.find(n => n.channel === 'discord')
      if (discordNotif) setDiscordWebhookInput(discordNotif.config?.webhook_url || '')
      setAiModel(aiRes.data)
      setRadarTopics(topicsRes.data.topics || [])
      setRadarHoursBack(topicsRes.data.hours_back ?? 24)
      setRadarIntervalMinutes(topicsRes.data.interval_minutes ?? 5)
      setSeverityKws(sevRes.data)
    } catch (err) {
      console.error('Failed to load settings:', err)
    }
    setLoading(false)
  }, [])

  const handleSwitchAIModel = async (model) => {
    setSwitchingAI(true)
    try {
      const res = await settingsAPI.updateAIModel(model)
      setAiModel(prev => ({ ...prev, model: res.data.model }))
      toast.success(res.data.message)
    } catch (err) {
      toast.error('切換 AI 引擎失敗')
    }
    setSwitchingAI(false)
  }

  useEffect(() => { loadSettings() }, [loadSettings])

  const handleAddSource = async (e) => {
    e.preventDefault()
    try {
      const keywords = newSource.keywords.split(',').map(k => k.trim()).filter(Boolean)
      await settingsAPI.createSource({ ...newSource, keywords })
      setNewSource({ name: '', type: 'rss', url: '', keywords: '' })
      setShowAddSource(false)
      loadSettings()
      toast.success('來源新增成功')
    } catch (err) {
      toast.error('新增失敗')
    }
  }

  const handleToggleSource = async (source) => {
    try {
      await settingsAPI.updateSource(source.id, { is_active: !source.is_active })
      setSources(prev => prev.map(s => s.id === source.id ? { ...s, is_active: !s.is_active } : s))
    } catch (err) {
      toast.error('更新失敗')
    }
  }

  const handleDeleteSource = async (id) => {
    if (!confirm('確定刪除此來源？')) return
    try {
      await settingsAPI.deleteSource(id)
      setSources(prev => prev.filter(s => s.id !== id))
      toast.success('已刪除')
    } catch (err) {
      toast.error('刪除失敗')
    }
  }

  const handleToggleNotification = async (channel) => {
    const current = notifications.find(n => n.channel === channel)
    if (!current) return
    try {
      await settingsAPI.updateNotification(channel, { is_enabled: !current.is_enabled })
      setNotifications(prev => prev.map(n =>
        n.channel === channel ? { ...n, is_enabled: !n.is_enabled } : n
      ))
    } catch (err) {
      toast.error('更新失敗')
    }
  }

  const handleLineMinSeverityChange = async (val) => {
    const current = notifications.find(n => n.channel === 'line')
    if (!current) return
    const newConfig = { ...(current.config || {}), min_severity: val }
    try {
      await settingsAPI.updateNotification('line', { config: newConfig })
      setNotifications(prev => prev.map(n =>
        n.channel === 'line' ? { ...n, config: newConfig } : n
      ))
      toast.success('LINE 推播門檻已更新')
    } catch {
      toast.error('更新失敗')
    }
  }

  const handleTestNotification = async (channel) => {
    try {
      const { data } = await settingsAPI.testNotification(channel)
      if (data.success) {
        toast.success('測試訊息已發送，請確認 LINE 是否收到')
      } else {
        toast.error(data.error || `${channel} 測試失敗`)
      }
    } catch (err) {
      toast.error('測試失敗')
    }
  }

  const handleSaveDiscordWebhook = async () => {
    setSavingDiscord(true)
    try {
      const newConfig = { webhook_url: discordWebhookInput.trim() }
      await settingsAPI.updateNotification('discord', { config: newConfig })
      setNotifications(prev => prev.map(n =>
        n.channel === 'discord' ? { ...n, config: newConfig } : n
      ))
      toast.success('Discord Webhook URL 已儲存')
    } catch {
      toast.error('儲存失敗')
    }
    setSavingDiscord(false)
  }

  const handleAddTopic = () => {
    const t = newTopic.trim()
    if (!t || radarTopics.includes(t)) return
    setRadarTopics(prev => [...prev, t])
    setNewTopic('')
  }

  const handleRemoveTopic = (topic) => {
    setRadarTopics(prev => prev.filter(t => t !== topic))
  }

  const handleSaveTopics = async () => {
    setSavingTopics(true)
    try {
      await settingsAPI.updateRadarTopics(radarTopics, radarHoursBack, radarIntervalMinutes)
      toast.success('設定已儲存，掃描頻率立即生效')
    } catch {
      toast.error('儲存失敗')
    }
    setSavingTopics(false)
  }

  const handleSaveSeverityKws = async () => {
    setSavingSeverity(true)
    try {
      await settingsAPI.updateSeverityKeywords({ critical: severityKws.critical, high: severityKws.high })
      toast.success('風險關鍵字已儲存，下次掃描生效')
    } catch {
      toast.error('儲存失敗')
    }
    setSavingSeverity(false)
  }

  const handleResetSeverityKws = () => {
    setSeverityKws(prev => ({ ...prev, critical: prev.default_critical, high: prev.default_high }))
  }

  const handleAddToSeverity = (level, keyword) => {
    setSeverityKws(prev => ({
      ...prev,
      [level]: prev[level].includes(keyword)
        ? prev[level].filter(k => k !== keyword)
        : [...prev[level], keyword],
    }))
  }

  useEffect(() => {
    if (!activeTopicPicker) return
    const handler = () => setActiveTopicPicker(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [activeTopicPicker])

  const typeLabels = { rss: 'RSS', website: '網頁', social: '社群', newsapi: 'NewsAPI' }
  const channelLabels = { web: '網頁通知', line: 'LINE', email: 'Email', discord: 'Discord' }
  const channelIcons = {
    web: '🌐',
    line: '💬',
    email: '📧',
    discord: '🎮',
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500" />
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Monitor Sources */}
      <section className="card">
        {/* Section header — click to collapse/expand */}
        <div
          className="flex items-center justify-between cursor-pointer select-none"
          onClick={() => setSourcesExpanded(v => !v)}
        >
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-bold">監控來源</h3>
              <span className="text-xs text-dark-500">({sources.length} 個)</span>
              <svg
                className={`w-4 h-4 text-dark-500 transition-transform ${sourcesExpanded ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
            <p className="text-sm text-dark-400">管理雷達掃描的資料來源</p>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); setShowAddSource(!showAddSource) }}
            className="btn-primary text-sm"
          >
            + 新增來源
          </button>
        </div>

        {/* Collapsible body */}
        {sourcesExpanded && (
        <div className="mt-4">

        {/* Add Source Form */}
        {showAddSource && (
          <form onSubmit={handleAddSource} className="mb-4 p-4 bg-dark-900 rounded-lg space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm text-dark-400 mb-1">名稱</label>
                <input
                  value={newSource.name}
                  onChange={(e) => setNewSource(prev => ({ ...prev, name: e.target.value }))}
                  className="input"
                  placeholder="例：金管會公告"
                  required
                />
              </div>
              <div>
                <label className="block text-sm text-dark-400 mb-1">類型</label>
                <select
                  value={newSource.type}
                  onChange={(e) => setNewSource(prev => ({ ...prev, type: e.target.value }))}
                  className="input"
                >
                  <option value="rss">RSS Feed</option>
                  <option value="website">網頁爬蟲</option>
                  <option value="social">社群媒體</option>
                  <option value="newsapi">NewsAPI</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm text-dark-400 mb-1">URL</label>
              <input
                value={newSource.url}
                onChange={(e) => setNewSource(prev => ({ ...prev, url: e.target.value }))}
                className="input"
                placeholder="https://..."
                required
              />
            </div>
            <div>
              <label className="block text-sm text-dark-400 mb-1">關鍵字（逗號分隔）</label>
              <input
                value={newSource.keywords}
                onChange={(e) => setNewSource(prev => ({ ...prev, keywords: e.target.value }))}
                className="input"
                placeholder="例：利率, 升息, 降息"
              />
            </div>
            <div className="flex gap-2">
              <button type="submit" className="btn-primary text-sm">新增</button>
              <button type="button" onClick={() => setShowAddSource(false)} className="btn-secondary text-sm">取消</button>
            </div>
          </form>
        )}

        {/* Sources List */}
        <div className="space-y-2">
          {sources.map(source => {
            const isExpanded = expandedSources.has(source.id)
            return (
              <div key={source.id} className="rounded-lg bg-dark-900 overflow-hidden">
                {/* Header row — always visible, click to expand */}
                <div
                  className="flex items-center justify-between p-3 cursor-pointer hover:bg-dark-800/50 transition-colors"
                  onClick={() => toggleSourceExpand(source.id)}
                >
                  <div className="flex items-center gap-3">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleToggleSource(source) }}
                      className={`w-10 h-6 rounded-full transition-colors relative shrink-0 ${
                        source.is_active ? 'bg-primary-600' : 'bg-dark-600'
                      }`}
                    >
                      <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${
                        source.is_active ? 'translate-x-5' : 'translate-x-1'
                      }`} />
                    </button>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{source.name}</span>
                      <span className="badge bg-dark-700 text-dark-300">{typeLabels[source.type] || source.type}</span>
                      {source.keywords && source.keywords.length > 0 && (
                        <span className="text-xs text-dark-500">{source.keywords.length} 個關鍵字</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteSource(source.id) }}
                      className="p-1.5 hover:bg-red-500/10 rounded text-dark-500 hover:text-red-400 transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                      </svg>
                    </button>
                    <svg
                      className={`w-4 h-4 text-dark-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="px-4 pb-3 border-t border-dark-700/50 pt-3 space-y-2">
                    <div>
                      <span className="text-xs text-dark-500 mr-2">URL</span>
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-xs text-primary-400 hover:underline break-all"
                      >{source.url}</a>
                    </div>
                    {source.keywords && source.keywords.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {source.keywords.map(kw => (
                          <span key={kw} className="text-xs px-1.5 py-0.5 rounded bg-dark-700 text-dark-300">{kw}</span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        </div>
        )}
      </section>

      {/* Radar Search Topics */}
      <section className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold">Google News 搜尋關鍵字</h3>
            <p className="text-sm text-dark-400">雷達每 {radarIntervalMinutes} 分鐘以這些關鍵字搜尋 Google News</p>
          </div>
          <button
            onClick={handleSaveTopics}
            disabled={savingTopics}
            className="btn-primary text-sm flex items-center gap-1.5"
          >
            {savingTopics && <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white" />}
            儲存
          </button>
        </div>

        {/* Topic Tags — split simple vs boolean */}
        {(() => {
          const simpleTopics = radarTopics.filter(t => !t.includes('('))
          const groupedTopics = radarTopics.filter(t => t.includes('('))
          return (
            <div className="mb-3 space-y-3">
              {/* Simple keywords */}
              {simpleTopics.length > 0 && (
                <div>
                  <div className="text-xs text-dark-500 mb-1.5">單一關鍵字</div>
                  <div className="flex flex-wrap gap-2">
                    {simpleTopics.map(topic => {
                      const isCrit = severityKws.critical.includes(topic)
                      const isHigh = severityKws.high.includes(topic)
                      const pickerOpen = activeTopicPicker === topic
                      return (
                        <div key={topic} className="relative">
                          {pickerOpen && (
                            <div
                              className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 bg-dark-800 border border-dark-600 rounded-lg shadow-xl p-1.5 flex items-center gap-1"
                              onClick={e => e.stopPropagation()}
                            >
                              <span className="text-[9px] text-dark-500 pr-1 border-r border-dark-600 mr-0.5 whitespace-nowrap">風險標記</span>
                              <button
                                onClick={() => handleAddToSeverity('critical', topic)}
                                className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                                  isCrit
                                    ? 'bg-red-500/30 text-red-300 border-red-400/50'
                                    : 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/25'
                                }`}
                              >緊急</button>
                              <button
                                onClick={() => handleAddToSeverity('high', topic)}
                                className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                                  isHigh
                                    ? 'bg-orange-500/30 text-orange-300 border-orange-400/50'
                                    : 'bg-orange-500/10 text-orange-400 border-orange-500/20 hover:bg-orange-500/25'
                                }`}
                              >高</button>
                            </div>
                          )}
                          <span
                            onClick={e => { e.stopPropagation(); setActiveTopicPicker(pickerOpen ? null : topic) }}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-primary-600/20 text-primary-400 border border-primary-500/30 text-sm cursor-pointer select-none hover:bg-primary-600/30 transition-colors"
                          >
                            {isCrit && <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />}
                            {!isCrit && isHigh && <span className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" />}
                            {topic}
                            <button
                              onClick={e => { e.stopPropagation(); handleRemoveTopic(topic) }}
                              className="ml-0.5 text-primary-500 hover:text-red-400 transition-colors leading-none"
                            >×</button>
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
              {/* Boolean groups */}
              {groupedTopics.length > 0 && (
                <div>
                  <div className="text-xs text-dark-500 mb-1.5">布林組合</div>
                  <div className="flex flex-col gap-2">
                    {groupedTopics.map(topic => {
                      const groups = parseGroupedKeyword(topic)
                      if (!groups) return null
                      return (
                        <GroupedKeywordCard
                          key={topic}
                          groups={groups}
                          onSave={(newGroups) => {
                            const newStr = serializeGroups(newGroups)
                            setRadarTopics(prev => prev.map(t => t === topic ? newStr : t))
                          }}
                          onRemove={() => handleRemoveTopic(topic)}
                          onSplit={(terms) => setRadarTopics(prev => {
                            const without = prev.filter(t => t !== topic)
                            const toAdd = terms.filter(t => !without.includes(t))
                            return [...without, ...toAdd]
                          })}
                          severityKws={severityKws}
                          onAddToSeverity={handleAddToSeverity}
                        />
                      )
                    })}
                  </div>
                </div>
              )}
              {radarTopics.length === 0 && <span className="text-sm text-dark-500">尚無關鍵字</span>}
            </div>
          )
        })()}

        {/* Add Topic Input */}
        <div className="flex gap-2">
          <input
            type="text"
            value={newTopic}
            onChange={(e) => setNewTopic(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddTopic()}
            placeholder="輸入單一關鍵字後按 Enter 或點新增"
            className="input text-sm flex-1"
          />
          <button onClick={handleAddTopic} className="btn-secondary text-sm px-4">新增</button>
          <button
            type="button"
            onClick={() => setShowGroupBuilder(v => !v)}
            className="btn-secondary text-sm px-3 whitespace-nowrap"
          >
            {showGroupBuilder ? '取消' : '+ 布林組合'}
          </button>
        </div>
        {showGroupBuilder && (
          <NewGroupedBuilder
            onAdd={(groups) => {
              const str = serializeGroups(groups)
              if (!radarTopics.includes(str)) setRadarTopics(prev => [...prev, str])
              setShowGroupBuilder(false)
            }}
            onClose={() => setShowGroupBuilder(false)}
          />
        )}
        {/* Hours Back + Interval Settings */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 mt-4 pt-4 border-t border-dark-700">
          <div className="flex items-center gap-3">
            <span className="text-sm text-dark-400 whitespace-nowrap">掃描時間範圍</span>
            <select
              value={radarHoursBack}
              onChange={(e) => setRadarHoursBack(Number(e.target.value))}
              className="input text-sm w-40"
            >
              <option value={1}>最近 1 小時</option>
              <option value={3}>最近 3 小時</option>
              <option value={6}>最近 6 小時</option>
              <option value={12}>最近 12 小時</option>
              <option value={24}>最近 24 小時</option>
              <option value={48}>最近 48 小時</option>
              <option value={72}>最近 72 小時</option>
            </select>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-dark-400 whitespace-nowrap">自動掃描頻率</span>
            <select
              value={radarIntervalMinutes}
              onChange={(e) => setRadarIntervalMinutes(Number(e.target.value))}
              className="input text-sm w-36"
            >
              <option value={1}>每 1 分鐘</option>
              <option value={3}>每 3 分鐘</option>
              <option value={5}>每 5 分鐘</option>
              <option value={10}>每 10 分鐘</option>
              <option value={15}>每 15 分鐘</option>
              <option value={30}>每 30 分鐘</option>
              <option value={60}>每 60 分鐘</option>
            </select>
            <span className="text-xs text-dark-500">儲存後立即生效，無需重啟</span>
          </div>
        </div>
        <p className="text-xs text-dark-500 mt-2">
          每個標籤直接作為 Google News 搜尋字串送出，支援 Google 搜尋語法：<br />
          <span className="text-dark-400">
            <code className="bg-dark-700 px-1 rounded">OR</code> 聯集 ·{' '}
            <code className="bg-dark-700 px-1 rounded">"精確詞"</code> 完全比對 ·{' '}
            <code className="bg-dark-700 px-1 rounded">-排除詞</code> 排除 ·{' '}
            <code className="bg-dark-700 px-1 rounded">AND</code> 交集（預設空格即為 AND）<br />
            例：<code className="bg-dark-700 px-1 rounded">("元大銀" OR "元大金控") ("重訊" OR "獨家") -廣告</code>
          </span>
        </p>
      </section>

      {/* Severity Keywords */}
      <section className="card space-y-5">
        <div>
          <h3 className="text-lg font-bold">風險程度關鍵字</h3>
          <p className="text-sm text-dark-400 mt-1">
            文章標題或內文包含對應關鍵字時，自動標記風險等級。判斷順序：緊急 → 高 → 低（預設）。
          </p>
        </div>

        {/* Critical */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs px-2 py-0.5 rounded border bg-red-500/20 text-red-400 border-red-500/30 font-medium">緊急</span>
            <span className="text-xs text-dark-500">符合任一關鍵字即標記為緊急</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2 min-h-8">
            {severityKws.critical.map(kw => (
              <span key={kw} className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20">
                {kw}
                <button onClick={() => setSeverityKws(p => ({ ...p, critical: p.critical.filter(k => k !== kw) }))}
                  className="hover:text-red-300 ml-0.5 text-red-500">×</button>
              </span>
            ))}
            {severityKws.critical.length === 0 && <span className="text-xs text-dark-600">尚無關鍵字</span>}
          </div>
          <div className="flex gap-2">
            <input type="text" value={newCritKw} onChange={e => setNewCritKw(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && newCritKw.trim()) { setSeverityKws(p => ({ ...p, critical: [...p.critical, newCritKw.trim()] })); setNewCritKw('') }}}
              placeholder="新增關鍵字後按 Enter" className="input text-sm flex-1" />
            <button onClick={() => { if (newCritKw.trim()) { setSeverityKws(p => ({ ...p, critical: [...p.critical, newCritKw.trim()] })); setNewCritKw('') }}}
              className="btn-secondary text-sm px-3">新增</button>
          </div>
        </div>

        {/* High */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs px-2 py-0.5 rounded border bg-orange-500/20 text-orange-400 border-orange-500/30 font-medium">高</span>
            <span className="text-xs text-dark-500">符合任一關鍵字即標記為高（未命中緊急時）</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2 min-h-8">
            {severityKws.high.map(kw => (
              <span key={kw} className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-orange-500/10 text-orange-400 border border-orange-500/20">
                {kw}
                <button onClick={() => setSeverityKws(p => ({ ...p, high: p.high.filter(k => k !== kw) }))}
                  className="hover:text-orange-300 ml-0.5 text-orange-500">×</button>
              </span>
            ))}
            {severityKws.high.length === 0 && <span className="text-xs text-dark-600">尚無關鍵字</span>}
          </div>
          <div className="flex gap-2">
            <input type="text" value={newHighKw} onChange={e => setNewHighKw(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && newHighKw.trim()) { setSeverityKws(p => ({ ...p, high: [...p.high, newHighKw.trim()] })); setNewHighKw('') }}}
              placeholder="新增關鍵字後按 Enter" className="input text-sm flex-1" />
            <button onClick={() => { if (newHighKw.trim()) { setSeverityKws(p => ({ ...p, high: [...p.high, newHighKw.trim()] })); setNewHighKw('') }}}
              className="btn-secondary text-sm px-3">新增</button>
          </div>
        </div>

        <div className="flex items-center gap-3 pt-2 border-t border-dark-700">
          <button onClick={handleSaveSeverityKws} disabled={savingSeverity} className="btn-primary text-sm">
            {savingSeverity ? '儲存中...' : '儲存設定'}
          </button>
          <button onClick={handleResetSeverityKws} className="btn-secondary text-sm">還原預設值</button>
          <span className="text-xs text-dark-500">修改後下次雷達掃描及文章載入即生效</span>
        </div>
      </section>

      {/* Notification Settings */}
      <section className="card">
        <div className="mb-4">
          <h3 className="text-lg font-bold">通知設定</h3>
          <p className="text-sm text-dark-400">設定即時警報的通知管道</p>
        </div>

        <div className="space-y-3">
          {notifications.map(notif => (
            <div key={notif.channel} className="flex items-center justify-between p-4 rounded-lg bg-dark-900">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{channelIcons[notif.channel]}</span>
                <div>
                  <span className="font-medium">{channelLabels[notif.channel]}</span>
                  <p className="text-xs text-dark-500">
                    {notif.channel === 'web' && '瀏覽器內 Toast 通知'}
                    {notif.channel === 'line' && (
                      lineStatus
                        ? lineStatus.token_configured
                          ? notif.is_enabled
                            ? <span className="text-green-400">已設定 ✓ 廣播給所有好友</span>
                            : <span className="text-yellow-400">Token 已設定，但通知已關閉（請開啟右側開關）</span>
                          : <span className="text-red-400">.env 未設定 LINE_CHANNEL_ACCESS_TOKEN</span>
                        : 'LINE Messaging API 廣播推送'
                    )}
                    {notif.channel === 'email' && 'SMTP 郵件通知'}
                    {notif.channel === 'discord' && (
                      notif.config?.webhook_url
                        ? <span className="text-green-400">Webhook URL 已設定 ✓</span>
                        : <span className="text-yellow-400">請在下方設定 Webhook URL</span>
                    )}
                  </p>
                  {notif.channel === 'line' && (
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-dark-400">推播門檻：</span>
                      <select
                        value={notif.config?.min_severity || 'critical'}
                        onChange={e => handleLineMinSeverityChange(e.target.value)}
                        className="input text-xs py-0.5 px-2 h-6"
                      >
                        <option value="critical">僅緊急</option>
                        <option value="high">高＋緊急</option>
                        <option value="all">所有警報</option>
                      </select>
                    </div>
                  )}
                  {notif.channel === 'discord' && (
                    <div className="flex items-center gap-2 mt-2">
                      <input
                        type="text"
                        placeholder="https://discord.com/api/webhooks/..."
                        value={discordWebhookInput}
                        onChange={e => setDiscordWebhookInput(e.target.value)}
                        className="input text-xs py-1 px-2 h-7 w-72"
                      />
                      <button
                        onClick={handleSaveDiscordWebhook}
                        disabled={savingDiscord}
                        className="btn-primary text-xs py-1 px-2 h-7"
                      >
                        {savingDiscord ? '儲存中...' : '儲存'}
                      </button>
                    </div>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <button onClick={() => handleTestNotification(notif.channel)}
                  className="btn-secondary text-xs">
                  測試
                </button>
                <button
                  onClick={() => handleToggleNotification(notif.channel)}
                  className={`w-10 h-6 rounded-full transition-colors relative ${
                    notif.is_enabled ? 'bg-primary-600' : 'bg-dark-600'
                  }`}
                >
                  <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${
                    notif.is_enabled ? 'translate-x-5' : 'translate-x-1'
                  }`} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* LINE 設定說明 */}
      <section className="card">
        <div className="mb-3">
          <h3 className="text-lg font-bold">LINE 推播設定說明</h3>
          <p className="text-sm text-dark-400 mt-1">
            啟用上方「LINE」開關後，每次偵測到新信號即自動推播
          </p>
        </div>
        <ol className="text-sm text-dark-300 space-y-1 list-decimal list-inside">
          <li>前往 <span className="text-primary-400">LINE Developers Console</span> 建立 Messaging API 頻道</li>
          <li>取得 <code className="bg-dark-700 px-1 rounded">Channel access token (long-lived)</code></li>
          <li>取得 <code className="bg-dark-700 px-1 rounded">LINE_TARGET_ID</code>（個人 User ID 或群組 ID）</li>
          <li>
            寫入 <code className="bg-dark-700 px-1 rounded">.env</code>：
            <pre className="bg-dark-900 rounded p-2 mt-1 text-xs text-green-400 overflow-x-auto">{`LINE_CHANNEL_ACCESS_TOKEN=your_token\nLINE_TARGET_ID=Uxxxxxxxxxx`}</pre>
          </li>
          <li>重啟後端，再按「LINE」旁的「測試」按鈕確認</li>
        </ol>
        <div className="flex items-center gap-3 mt-3">
          <button
            onClick={() => handleTestNotification('line')}
            className="btn-secondary text-sm"
          >
            傳送測試訊息
          </button>
          <span className="text-xs text-dark-500">收到 LINE 訊息即代表設定正確</span>
        </div>

        {/* LINE Bot Reply（免費無限制）*/}
        <div className="mt-4 pt-4 border-t border-dark-700">
          <h4 className="text-sm font-semibold text-green-400 mb-1">💡 LINE Bot 回覆模式（免費、無月額限制）</h4>
          <p className="text-xs text-dark-400 mb-2">
            傳任意訊息給 LINE Bot → Bot 立即回覆最新 5 筆警報。使用 Reply API，完全免費不計入 200 則月額。
          </p>
          <ol className="text-xs text-dark-300 space-y-1 list-decimal list-inside">
            <li>
              在 <code className="bg-dark-700 px-1 rounded">.env</code> 填入 Channel Secret：
              <pre className="bg-dark-900 rounded p-2 mt-1 text-xs text-green-400 overflow-x-auto">{`LINE_CHANNEL_SECRET=your_channel_secret`}</pre>
            </li>
            <li>開啟 ngrok：<code className="bg-dark-700 px-1 rounded">ngrok http 8000</code></li>
            <li>
              在 LINE Developers Console → Messaging API → Webhook settings 填入：
              <pre className="bg-dark-900 rounded p-2 mt-1 text-xs text-yellow-400 overflow-x-auto">{`https://[ngrok-domain].ngrok-free.app/api/line/webhook`}</pre>
            </li>
            <li>開啟「Use webhook」開關</li>
            <li>傳任意訊息給 Bot → 回覆最新警報（傳「詳情 1」查看第 1 筆完整內容）</li>
          </ol>
        </div>
      </section>

      {/* Discord 設定說明 */}
      <section className="card">
        <div className="mb-3">
          <h3 className="text-lg font-bold">Discord Webhook 設定說明</h3>
          <p className="text-sm text-dark-400 mt-1">完全免費、無訊息數限制，支援 Embed 富文本格式</p>
        </div>
        <ol className="text-sm text-dark-300 space-y-1 list-decimal list-inside">
          <li>在 Discord 頻道設定 → 整合 → Webhook → 建立 Webhook</li>
          <li>複製 Webhook URL（格式：<code className="bg-dark-700 px-1 rounded">https://discord.com/api/webhooks/...</code>）</li>
          <li>貼入上方「Discord」管道的輸入框並按「儲存」</li>
          <li>開啟右側開關，再按「測試」確認 Discord 頻道收到訊息</li>
        </ol>
        <div className="flex items-center gap-3 mt-3">
          <button
            onClick={() => handleTestNotification('discord')}
            className="btn-secondary text-sm"
          >
            傳送測試訊息
          </button>
          <span className="text-xs text-dark-500">Discord 頻道收到 Embed 訊息即代表設定正確</span>
        </div>
      </section>

      {/* Google Sheets */}
      <section className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold">Google Sheets 連結</h3>
            <p className="text-sm text-dark-400">部位資料讀取 & 新聞留存</p>
          </div>
          <button
            onClick={async () => {
              setSheetsTesting(true)
              setSheetsTestResult(null)
              try {
                const { data } = await settingsAPI.testGoogleSheets()
                setSheetsTestResult(data)
              } catch (err) {
                setSheetsTestResult({ success: false, message: '連線失敗' })
              }
              setSheetsTesting(false)
            }}
            disabled={sheetsTesting}
            className="btn-secondary text-sm flex items-center gap-1.5"
          >
            {sheetsTesting && <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-current" />}
            測試連線
          </button>
        </div>

        {sheetsStatus && (
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">金鑰檔案</span>
              <p className="text-sm mt-1 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${sheetsStatus.credentials_exists ? 'bg-green-500' : 'bg-red-500'}`} />
                {sheetsStatus.credentials_file}
              </p>
            </div>
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">試算表 ID</span>
              <p className="text-sm mt-1 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${sheetsStatus.configured ? 'bg-green-500' : 'bg-yellow-500'}`} />
                {sheetsStatus.spreadsheet_id || '未設定'}
              </p>
            </div>
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">部位資料 Tab</span>
              <p className="text-sm mt-1">{sheetsStatus.position_sheet}</p>
            </div>
            <div className="p-3 bg-dark-900 rounded-lg">
              <span className="text-xs text-dark-400">新聞留存 Tab</span>
              <p className="text-sm mt-1">{sheetsStatus.news_sheet}</p>
            </div>
          </div>
        )}

        {sheetsTestResult && (
          <div className={`p-3 rounded-lg ${sheetsTestResult.success ? 'bg-green-500/10 border border-green-500/20' : 'bg-red-500/10 border border-red-500/20'}`}>
            <p className={`text-sm ${sheetsTestResult.success ? 'text-green-400' : 'text-red-400'}`}>
              {sheetsTestResult.message}
            </p>
            {sheetsTestResult.position_count !== undefined && (
              <p className="text-xs text-dark-400 mt-1">部位數量：{sheetsTestResult.position_count}</p>
            )}
            {sheetsTestResult.tabs && (
              <p className="text-xs text-dark-400 mt-1">分頁：{sheetsTestResult.tabs.join(', ')}</p>
            )}
          </div>
        )}
      </section>

      {/* AI Engine Settings */}
      <section className="card">
        <h3 className="text-lg font-bold mb-4">AI 分析引擎</h3>
        {aiModel && (
          <div className="space-y-3">
            <p className="text-sm text-dark-400">選擇預設 AI 引擎（影響雷達通知、主題搜尋、市場分析）</p>
            <div className="flex gap-3">
              <button
                onClick={() => handleSwitchAIModel('gemini')}
                disabled={switchingAI || aiModel.model === 'gemini'}
                className={`flex-1 p-3 rounded-lg border-2 text-sm font-medium transition-all ${
                  aiModel.model === 'gemini'
                    ? 'border-blue-500 bg-blue-500/10 text-blue-400'
                    : 'border-dark-700 bg-dark-900 text-dark-300 hover:border-dark-500'
                }`}
              >
                <div className="font-bold">Gemini 2.5 Flash</div>
                <div className="text-xs opacity-70 mt-1">
                  {aiModel.gemini_configured ? '✅ 已設定' : '⚠️ 未設定 API Key'}
                </div>
                {aiModel.model === 'gemini' && <div className="text-xs text-blue-400 mt-1">● 目前使用</div>}
              </button>
              <button
                onClick={() => handleSwitchAIModel('claude')}
                disabled={switchingAI || aiModel.model === 'claude'}
                className={`flex-1 p-3 rounded-lg border-2 text-sm font-medium transition-all ${
                  aiModel.model === 'claude'
                    ? 'border-purple-500 bg-purple-500/10 text-purple-400'
                    : 'border-dark-700 bg-dark-900 text-dark-300 hover:border-dark-500'
                }`}
              >
                <div className="font-bold">Claude Sonnet 4</div>
                <div className="text-xs opacity-70 mt-1">
                  {aiModel.claude_configured ? '✅ 已設定' : '⚠️ 未設定 API Key'}
                </div>
                {aiModel.model === 'claude' && <div className="text-xs text-purple-400 mt-1">● 目前使用</div>}
              </button>
            </div>
            <p className="text-xs text-dark-500">切換立即生效，重啟後回到 .env 設定值</p>
          </div>
        )}
      </section>

      {/* System Info */}
      <section className="card">
        <h3 className="text-lg font-bold mb-4">系統資訊</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">雷達掃描間隔</span>
            <p className="font-medium mt-1">每 5 分鐘</p>
          </div>
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">每日新聞蒐集</span>
            <p className="font-medium mt-1">每日 08:00</p>
          </div>
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">資料來源數量</span>
            <p className="font-medium mt-1">{sources.filter(s => s.is_active).length} / {sources.length} 啟用</p>
          </div>
          <div className="p-3 bg-dark-900 rounded-lg">
            <span className="text-dark-400">AI 分析引擎</span>
            <p className="font-medium mt-1">
              {aiModel ? (aiModel.model === 'gemini' ? 'Gemini 2.5 Flash' : 'Claude Sonnet 4') : '載入中...'}
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
