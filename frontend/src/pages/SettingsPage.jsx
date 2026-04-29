import { useCallback, useEffect, useState } from 'react'
import { settingsAPI } from '../services/api'
import { toast } from 'react-hot-toast'

// 將 API/RSS URL 轉換為可瀏覽的新聞網站連結
function getBrowseUrl(url) {
  if (!url) return null
  // 鉅亨網 JSON API → news.cnyes.com
  const cnyesMatch = url.match(/api\.cnyes\.com\/media\/api\/v1\/newslist\/category\/([^/?]+)/)
  if (cnyesMatch) return `https://news.cnyes.com/news/cat/${cnyesMatch[1]}`
  // RSS feed → 取出 hostname 作為來源首頁
  try {
    const { hostname, protocol } = new URL(url)
    // 若 URL 本身就是可瀏覽網頁（非 api. 開頭，非 feeds. 開頭，非 .xml/.rss 結尾）
    if (!hostname.startsWith('api.') && !hostname.startsWith('feeds.') &&
        !url.endsWith('.xml') && !url.endsWith('.rss') && !url.includes('/rss') &&
        !url.includes('feedburner') && !url.includes('rss.')) {
      return null // URL 本身就可點，不需要另外顯示
    }
    return `${protocol}//${hostname}`
  } catch {
    return null
  }
}

// Extract "NOT term" / "NOT \"multi word\"" from a keyword string
function stripNotTerms(kw) {
  const notTerms = []
  const regex = /\bNOT\s+(?:"([^"]+)"|(\S+))/gi
  let m
  while ((m = regex.exec(kw)) !== null) {
    notTerms.push(m[1] !== undefined ? m[1] : m[2])
  }
  const cleaned = kw.replace(/\bNOT\s+(?:"[^"]+"|\S+)\s*/gi, '').trim()
  return { cleaned, notTerms }
}

// Parse "(A OR B) (C OR D)" → [[A,B],[C,D]]; simple keyword → null
// Strips NOT terms before parsing so they don't interfere.
function parseGroupedKeyword(kw) {
  const { cleaned } = stripNotTerms(kw)
  if (!cleaned.includes('(')) return null
  const matches = cleaned.match(/\(([^)]+)\)/g)
  if (!matches) return null
  return matches.map(m => {
    const inner = m.slice(1, -1)
    return inner.split(/\bOR\b/i).map(t => t.trim().replace(/^["']|["']$/g, '')).filter(Boolean)
  })
}

function computeCombinations(groups) {
  return groups.reduce((acc, g) => acc * g.length, 1)
}

function serializeGroups(groups, notTerms = []) {
  const base = groups.filter(g => g.length > 0).map(g => `(${g.map(t => `"${t}"`).join(' OR ')})`).join(' ')
  const notPart = notTerms.map(t => t.includes(' ') ? `NOT "${t}"` : `NOT ${t}`).join(' ')
  return notPart ? `${base} ${notPart}` : base
}

// Parse a severity rule condition string into [[term,...], [term,...]] groups
// Handles "(A OR B) word" and plain space-separated words
function parseCondition(condStr) {
  if (!condStr) return [['']]
  const parts = []
  const regex = /\(([^)]+)\)|(\S+)/g
  let match
  while ((match = regex.exec(condStr)) !== null) {
    if (match[1] !== undefined) {
      const terms = match[1].split(/\bOR\b/i).map(t => t.trim().replace(/^["']|["']$/g, '')).filter(Boolean)
      if (terms.length > 0) parts.push(terms)
    } else {
      const word = match[2].replace(/^["']|["']$/g, '')
      if (word) parts.push([word])
    }
  }
  return parts.length > 0 ? parts : [['']]
}

// Serialize groups to condition string — single-term groups are bare words, multi-term groups use (A OR B)
function serializeCondition(groups) {
  return groups
    .map(g => g.filter(Boolean))
    .filter(g => g.length > 0)
    .map(g => g.length === 1 ? g[0] : `(${g.join(' OR ')})`)
    .join(' ')
}

// Returns true if a topic string contains no CJK/Japanese characters (i.e. is purely English/ASCII)
function isEnglishTopic(topic) {
  const hasCJK = (s) => /[\u4e00-\u9fff\u3040-\u30ff\uff00-\uffef]/.test(s)
  if (topic.includes('(')) {
    const groups = parseGroupedKeyword(topic)
    if (!groups) return !hasCJK(topic)
    return groups.every(g => g.every(t => !hasCJK(t)))
  }
  return !hasCJK(topic)
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

function GroupedKeywordCard({ topicStr, onSave, onRemove, onSplit, severityKws = {}, onAddToSeverity }) {
  const { cleaned: cleanedStr, notTerms: parsedNotTerms } = stripNotTerms(topicStr)
  const groups = parseGroupedKeyword(cleanedStr) || [[]]

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(() => groups.map(g => [...g]))
  const [notTermsDraft, setNotTermsDraft] = useState(() => [...parsedNotTerms])
  const [newNotTerm, setNewNotTerm] = useState('')
  const [newTerms, setNewTerms] = useState(() => groups.map(() => ''))
  const [activePickerTerm, setActivePickerTerm] = useState(null)

  useEffect(() => {
    if (!activePickerTerm) return
    const handler = () => setActivePickerTerm(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [activePickerTerm])

  const startEdit = () => {
    setDraft(groups.map(g => [...g]))
    setNewTerms(groups.map(() => ''))
    setNotTermsDraft([...parsedNotTerms])
    setNewNotTerm('')
    setEditing(true)
  }
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

  const addNotTerm = () => {
    const t = newNotTerm.trim()
    if (!t || notTermsDraft.includes(t)) return
    setNotTermsDraft(prev => [...prev, t])
    setNewNotTerm('')
  }

  const handleSave = () => {
    const cleaned = draft.filter(g => g.length > 0)
    if (cleaned.length === 0) { onRemove(); return }
    onSave(serializeGroups(cleaned, notTermsDraft))
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
            {parsedNotTerms.map((t, ti) => (
              <span key={`not-${ti}`} className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 whitespace-nowrap" title="排除詞：包含此詞的文章不抓取">
                <span className="text-[9px] font-bold opacity-70">NOT</span>{t}
              </span>
            ))}
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
    <div className="bg-dark-800 border border-primary-500/40 rounded-lg p-3 w-full space-y-3">
      <GroupEditor draft={draft} newTerms={newTerms} setNewTerms={setNewTerms}
        addTerm={addTerm} removeTerm={removeTerm} addGroup={addGroup} removeGroup={removeGroup} />
      {/* NOT terms (exclusion within this boolean group) */}
      <div>
        <div className="text-[10px] text-dark-500 mb-1.5 font-medium">排除詞（NOT）— 包含以下任一詞的文章不抓取</div>
        <div className="flex flex-wrap gap-1 mb-1.5 min-h-5">
          {notTermsDraft.map((t, ti) => (
            <span key={ti} className="flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/30">
              {t}
              <button type="button" onClick={() => setNotTermsDraft(prev => prev.filter((_, i) => i !== ti))} className="hover:text-red-300 ml-0.5 leading-none">×</button>
            </span>
          ))}
          {notTermsDraft.length === 0 && <span className="text-xs text-dark-600">（無）</span>}
        </div>
        <div className="flex gap-1">
          <input
            value={newNotTerm}
            onChange={e => setNewNotTerm(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addNotTerm() } }}
            placeholder="新增排除詞..."
            className="input text-xs py-0.5 px-1.5 flex-1 min-w-0 w-24 border-red-500/30 focus:border-red-500/60"
          />
          <button type="button" onClick={addNotTerm} className="text-red-500 hover:text-red-400 text-sm px-1">+</button>
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={cancel} className="btn-secondary text-xs py-1 px-3">取消</button>
        <button type="button" onClick={handleSave} className="btn-primary text-xs py-1 px-3">儲存</button>
      </div>
    </div>
  )
}

function NewGroupedBuilder({ onAdd, onClose }) {
  const [draft, setDraft] = useState([[]])
  const [newTerms, setNewTerms] = useState([''])
  const [notTerms, setNotTerms] = useState([])
  const [newNotTerm, setNewNotTerm] = useState('')

  const addTerm = (gi) => {
    const t = (newTerms[gi] || '').trim()
    if (!t) return
    setDraft(prev => prev.map((g, i) => i === gi ? [...g, t] : g))
    setNewTerms(prev => prev.map((v, i) => i === gi ? '' : v))
  }
  const removeTerm = (gi, ti) => setDraft(prev => prev.map((g, i) => i === gi ? g.filter((_, j) => j !== ti) : g))
  const addGroup = () => { setDraft(prev => [...prev, []]); setNewTerms(prev => [...prev, '']) }
  const removeGroup = (gi) => { setDraft(prev => prev.filter((_, i) => i !== gi)); setNewTerms(prev => prev.filter((_, i) => i !== gi)) }

  const addNotTerm = () => {
    const t = newNotTerm.trim()
    if (!t || notTerms.includes(t)) return
    setNotTerms(prev => [...prev, t])
    setNewNotTerm('')
  }

  const handleAdd = () => {
    const cleaned = draft.filter(g => g.length > 0)
    if (cleaned.length === 0) { onClose(); return }
    onAdd(serializeGroups(cleaned, notTerms))
  }

  return (
    <div className="bg-dark-800 border border-primary-500/40 rounded-lg p-3 w-full space-y-3">
      <div className="text-xs text-dark-400 font-medium">新增布林組合</div>
      <GroupEditor draft={draft} newTerms={newTerms} setNewTerms={setNewTerms}
        addTerm={addTerm} removeTerm={removeTerm} addGroup={addGroup} removeGroup={removeGroup} />
      {/* NOT terms */}
      <div>
        <div className="text-[10px] text-dark-500 mb-1.5 font-medium">排除詞（NOT）— 包含以下任一詞的文章不抓取</div>
        <div className="flex flex-wrap gap-1 mb-1.5 min-h-5">
          {notTerms.map((t, ti) => (
            <span key={ti} className="flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/30">
              {t}
              <button type="button" onClick={() => setNotTerms(prev => prev.filter((_, i) => i !== ti))} className="hover:text-red-300 ml-0.5 leading-none">×</button>
            </span>
          ))}
          {notTerms.length === 0 && <span className="text-xs text-dark-600">（選填）</span>}
        </div>
        <div className="flex gap-1">
          <input
            value={newNotTerm}
            onChange={e => setNewNotTerm(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addNotTerm() } }}
            placeholder="新增排除詞..."
            className="input text-xs py-0.5 px-1.5 flex-1 min-w-0 w-24 border-red-500/30 focus:border-red-500/60"
          />
          <button type="button" onClick={addNotTerm} className="text-red-500 hover:text-red-400 text-sm px-1">+</button>
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onClose} className="btn-secondary text-xs py-1 px-3">取消</button>
        <button type="button" onClick={handleAdd} className="btn-primary text-xs py-1 px-3">新增</button>
      </div>
    </div>
  )
}

// 關鍵字分類顏色系統
const CAT_COLORS = [
  { dot: 'bg-sky-400',     text: 'text-sky-400',     bg: 'bg-sky-500/15',     border: 'border-sky-500/30' },
  { dot: 'bg-violet-400',  text: 'text-violet-400',  bg: 'bg-violet-500/15',  border: 'border-violet-500/30' },
  { dot: 'bg-emerald-400', text: 'text-emerald-400', bg: 'bg-emerald-500/15', border: 'border-emerald-500/30' },
  { dot: 'bg-amber-400',   text: 'text-amber-400',   bg: 'bg-amber-500/15',   border: 'border-amber-500/30' },
  { dot: 'bg-rose-400',    text: 'text-rose-400',    bg: 'bg-rose-500/15',    border: 'border-rose-500/30' },
  { dot: 'bg-cyan-400',    text: 'text-cyan-400',    bg: 'bg-cyan-500/15',    border: 'border-cyan-500/30' },
  { dot: 'bg-orange-400',  text: 'text-orange-400',  bg: 'bg-orange-500/15',  border: 'border-orange-500/30' },
  { dot: 'bg-fuchsia-400', text: 'text-fuchsia-400', bg: 'bg-fuchsia-500/15', border: 'border-fuchsia-500/30' },
]

function SeverityRuleCard({ rule, onSave, onRemove, canMoveUp, canMoveDown, onMoveUp, onMoveDown }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(() => parseCondition(rule.condition))
  const [newTerms, setNewTerms] = useState(() => parseCondition(rule.condition).map(() => ''))
  const [draftSeverity, setDraftSeverity] = useState(rule.severity)
  const [draftNote, setDraftNote] = useState(rule.note || '')

  const startEdit = () => {
    const g = parseCondition(rule.condition)
    setDraft(g); setNewTerms(g.map(() => ''))
    setDraftSeverity(rule.severity); setDraftNote(rule.note || '')
    setEditing(true)
  }
  const addTerm = (gi) => {
    const t = (newTerms[gi] || '').trim(); if (!t) return
    setDraft(p => p.map((g, i) => i === gi ? [...g.filter(Boolean), t] : g))
    setNewTerms(p => p.map((v, i) => i === gi ? '' : v))
  }
  const removeTerm = (gi, ti) => setDraft(p => p.map((g, i) => i === gi ? g.filter((_, j) => j !== ti) : g))
  const addGroup = () => { setDraft(p => [...p, ['']]); setNewTerms(p => [...p, '']) }
  const removeGroup = (gi) => { setDraft(p => p.filter((_, i) => i !== gi)); setNewTerms(p => p.filter((_, i) => i !== gi)) }
  const handleSave = () => {
    const condition = serializeCondition(draft)
    if (!condition) return
    onSave({ condition, severity: draftSeverity, note: draftNote })
    setEditing(false)
  }

  const groups = parseCondition(rule.condition)
  const sevCls = rule.severity === 'critical' ? 'bg-red-500/20 text-red-400 border-red-500/30' :
    rule.severity === 'high' ? 'bg-orange-500/20 text-orange-400 border-orange-500/30' :
    'bg-gray-500/20 text-gray-400 border-gray-500/30'
  const sevLabel = rule.severity === 'critical' ? '緊急' : rule.severity === 'high' ? '高' : '低'

  return (
    <div className="rounded-lg bg-dark-800 border border-dark-600 overflow-hidden">
      <div className="flex items-center gap-2 p-2.5">
        {/* Move buttons */}
        <div className="flex flex-col gap-0.5 shrink-0">
          <button onClick={onMoveUp} disabled={!canMoveUp}
            className={`text-[10px] px-1 leading-none ${canMoveUp ? 'text-dark-500 hover:text-dark-300' : 'text-dark-700 cursor-default'}`}>▲</button>
          <button onClick={onMoveDown} disabled={!canMoveDown}
            className={`text-[10px] px-1 leading-none ${canMoveDown ? 'text-dark-500 hover:text-dark-300' : 'text-dark-700 cursor-default'}`}>▼</button>
        </div>
        {/* Severity badge */}
        <span className={`text-xs px-2 py-0.5 rounded border font-medium shrink-0 ${sevCls}`}>{sevLabel}</span>
        {/* Visual condition blocks (click to edit) */}
        <div
          className="flex items-center flex-wrap gap-1.5 flex-1 min-w-0 cursor-pointer group/rule"
          onClick={!editing ? startEdit : undefined}
        >
          {groups.map((terms, gi) => (
            <div key={gi} className="flex items-stretch">
              {gi > 0 && (
                <div className="flex items-center px-1.5 border-x border-dark-600">
                  <span className="text-[10px] font-bold text-dark-500 select-none">AND</span>
                </div>
              )}
              <div className="bg-dark-700 rounded px-2 py-1 flex items-center gap-1 flex-wrap">
                {terms.filter(Boolean).map((t, ti) => (
                  <span key={ti} className="flex items-center gap-0.5">
                    {ti > 0 && <span className="text-[9px] text-dark-400 select-none font-bold">OR</span>}
                    <span className="text-xs text-primary-300">{t}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
          {rule.note && <span className="text-xs text-dark-500 truncate ml-1">— {rule.note}</span>}
          {!editing && (
            <span className="text-[10px] text-dark-700 group-hover/rule:text-dark-500 transition-colors select-none ml-0.5">✎</span>
          )}
        </div>
        {/* Delete */}
        <button onClick={onRemove} className="text-dark-600 hover:text-red-400 text-base px-1 shrink-0 leading-none ml-1">×</button>
      </div>
      {/* Edit panel */}
      {editing && (
        <div className="px-3 pb-3 border-t border-dark-600 pt-3 space-y-3 bg-dark-900/40">
          <GroupEditor draft={draft} newTerms={newTerms} setNewTerms={setNewTerms}
            addTerm={addTerm} removeTerm={removeTerm} addGroup={addGroup} removeGroup={removeGroup} />
          <div className="flex flex-wrap gap-2 items-center">
            <select value={draftSeverity} onChange={e => setDraftSeverity(e.target.value)} className="input text-xs py-1 w-20 shrink-0">
              <option value="critical">緊急</option>
              <option value="high">高</option>
              <option value="low">低</option>
            </select>
            <input value={draftNote} onChange={e => setDraftNote(e.target.value)} placeholder="備註（選填）"
              className="input text-xs py-1 flex-1 min-w-0" />
            <button onClick={handleSave} className="btn-primary text-xs px-3 py-1">確認</button>
            <button onClick={() => setEditing(false)} className="btn-secondary text-xs px-3 py-1">取消</button>
          </div>
        </div>
      )}
    </div>
  )
}

function NewRuleBuilder({ onAdd, onClose }) {
  const [groups, setGroups] = useState([[]])
  const [newTerms, setNewTerms] = useState([''])
  const [severity, setSeverity] = useState('critical')
  const [note, setNote] = useState('')

  const addTerm = (gi) => {
    const t = (newTerms[gi] || '').trim(); if (!t) return
    setGroups(p => p.map((g, i) => i === gi ? [...g.filter(Boolean), t] : g))
    setNewTerms(p => p.map((v, i) => i === gi ? '' : v))
  }
  const removeTerm = (gi, ti) => setGroups(p => p.map((g, i) => i === gi ? g.filter((_, j) => j !== ti) : g))
  const addGroup = () => { setGroups(p => [...p, []]); setNewTerms(p => [...p, '']) }
  const removeGroup = (gi) => { setGroups(p => p.filter((_, i) => i !== gi)); setNewTerms(p => p.filter((_, i) => i !== gi)) }

  const handleAdd = () => {
    const condition = serializeCondition(groups)
    if (!condition) return
    onAdd({ condition, severity, note: note.trim() })
  }

  return (
    <div className="p-3 rounded-lg border border-dashed border-primary-500/40 bg-dark-900/40 space-y-3">
      <div className="text-xs text-dark-400 font-medium">新增布林規則</div>
      <GroupEditor draft={groups} newTerms={newTerms} setNewTerms={setNewTerms}
        addTerm={addTerm} removeTerm={removeTerm} addGroup={addGroup} removeGroup={removeGroup} />
      <div className="flex flex-wrap gap-2 items-center">
        <select value={severity} onChange={e => setSeverity(e.target.value)} className="input text-xs py-1 w-20 shrink-0">
          <option value="critical">緊急</option>
          <option value="high">高</option>
          <option value="low">低</option>
        </select>
        <input value={note} onChange={e => setNote(e.target.value)} placeholder="備註（選填）"
          className="input text-xs py-1 flex-1 min-w-0" />
        <button onClick={handleAdd} className="btn-primary text-xs px-3 py-1">加入</button>
        <button onClick={onClose} className="btn-secondary text-xs px-3 py-1">取消</button>
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
  const [radarRssOnly, setRadarRssOnly] = useState(false)
  const [radarTopicsUs, setRadarTopicsUs] = useState([])
  const [savingTopics, setSavingTopics] = useState(false)
  const [exclusionKeywords, setExclusionKeywords] = useState([])
  const [newExclusionKw, setNewExclusionKw] = useState('')
  const [sourcesExpanded, setSourcesExpanded] = useState(false)
  const [expandedSources, setExpandedSources] = useState(new Set())
  const [severityKws, setSeverityKws] = useState({ critical: [], high: [], default_critical: [], default_high: [] })
  const [newCritKw, setNewCritKw] = useState('')
  const [newHighKw, setNewHighKw] = useState('')
  const [savingSeverity, setSavingSeverity] = useState(false)
  const [discordWebhookInput, setDiscordWebhookInput] = useState('')
  const [savingDiscord, setSavingDiscord] = useState(false)
  const [rssTestStates, setRssTestStates] = useState({})
  // 來源內嵌編輯
  const [editingKwSources, setEditingKwSources] = useState(new Set())
  const [draftKws, setDraftKws] = useState({})         // { [id]: string[] }
  const [newKwInput, setNewKwInput] = useState({})      // { [id]: string }
  const [editingUrlSources, setEditingUrlSources] = useState(new Set())
  const [draftUrl, setDraftUrl] = useState({})          // { [id]: string }
  // 關鍵字分類：[{name, lang: "tw"|"en", keywords: [...]}]
  const [topicCategories, setTopicCategories] = useState([])
  const [newCatName, setNewCatName] = useState('')
  const [newCatLang, setNewCatLang] = useState('tw')
  const [newCatKws, setNewCatKws] = useState({})   // { catIndex: 輸入框值 }
  const [showCatGroupBuilder, setShowCatGroupBuilder] = useState(null)  // catIndex or null
  // 布林嚴重度規則
  const [severityRules, setSeverityRules] = useState([])
  const [showRuleBuilder, setShowRuleBuilder] = useState(false)
  const [savingRules, setSavingRules] = useState(false)
  // 嚴重度設定 tab
  const [severityTab, setSeverityTab] = useState('keywords')
  // 來源 tab
  const [sourceTab, setSourceTab] = useState('news')
  // 財經相關性篩選
  const [financeFilterEnabled, setFinanceFilterEnabled] = useState(false)
  const [financeThreshold, setFinanceThreshold] = useState(0.15)
  const [savingFinanceFilter, setSavingFinanceFilter] = useState(false)
  // RSS 優先模式
  const [rssMinArticles, setRssMinArticles] = useState(0)
  const [savingRssPriority, setSavingRssPriority] = useState(false)
  // Google News 僅緊急模式
  const [gnCriticalOnly, setGnCriticalOnly] = useState(true)
  // 拖曳排序
  const [dragSourceId, setDragSourceId] = useState(null)
  const [dragOverId, setDragOverId] = useState(null)
  // 來源名稱 inline 編輯
  const [editingSourceName, setEditingSourceName] = useState({})  // { [id]: string }
  // 關鍵字分類 picker

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
      const [srcRes, notifRes, sheetsRes, aiRes, topicsRes, sevRes, lineRes, catsRes, rulesRes, finRes, rssRes, gnCriticalOnlyRes] = await Promise.all([
        settingsAPI.getSources(),
        settingsAPI.getNotificationSettings(),
        settingsAPI.getGoogleSheetsStatus(),
        settingsAPI.getAIModel(),
        settingsAPI.getRadarTopics(),
        settingsAPI.getSeverityKeywords(),
        settingsAPI.getLineStatus(),
        settingsAPI.getTopicCategories(),
        settingsAPI.getSeverityRules(),
        settingsAPI.getFinanceFilter(),
        settingsAPI.getRssPriority(),
        settingsAPI.getGnCriticalOnly(),
      ])
      setSources(srcRes.data)
      setNotifications(notifRes.data)
      setSheetsStatus(sheetsRes.data)
      setLineStatus(lineRes.data)
      const discordNotif = notifRes.data.find(n => n.channel === 'discord')
      if (discordNotif) setDiscordWebhookInput(discordNotif.config?.webhook_url || '')
      setAiModel(aiRes.data)
      // Auto-migrate purely-English topics from TW region to US region (one-time, state-level only)
      const allTwTopics = topicsRes.data.topics || []
      const allUsTopics = topicsRes.data.topics_us || []
      const englishFromTw = allTwTopics.filter(isEnglishTopic)
      const twOnly = allTwTopics.filter(t => !isEnglishTopic(t))
      const mergedUs = [...allUsTopics, ...englishFromTw.filter(t => !allUsTopics.includes(t))]
      setRadarTopics(twOnly)
      setRadarTopicsUs(mergedUs)
      setRadarHoursBack(topicsRes.data.hours_back ?? 24)
      setRadarIntervalMinutes(topicsRes.data.interval_minutes ?? 5)
      setRadarRssOnly(topicsRes.data.rss_only ?? false)
      setExclusionKeywords(topicsRes.data.exclusion_keywords || [])
      setSeverityKws(sevRes.data)
      // 建構分類結構
      const savedCats = catsRes.data.categories
      if (Array.isArray(savedCats) && savedCats.length > 0 && savedCats[0]?.name) {
        // 新格式：[{name, lang, keywords}]
        setTopicCategories(savedCats)
      } else {
        // 舊格式或空：從 radarTopics 建構預設「未分類」
        const cats = []
        if (twOnly.length > 0) cats.push({ name: '未分類', lang: 'tw', keywords: twOnly })
        if (mergedUs.length > 0) cats.push({ name: '未分類 (EN)', lang: 'en', keywords: mergedUs })
        setTopicCategories(cats)
      }
      setSeverityRules(rulesRes.data.rules || [])
      setFinanceFilterEnabled(finRes.data.enabled ?? false)
      setFinanceThreshold(finRes.data.threshold ?? 0.15)
      setRssMinArticles(rssRes.data.min_articles ?? 0)
      setGnCriticalOnly(gnCriticalOnlyRes.data.enabled ?? true)
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

  const handleSaveRules = async () => {
    setSavingRules(true)
    try {
      await settingsAPI.updateSeverityRules(severityRules)
      toast.success('布林規則已儲存，下次掃描生效')
    } catch {
      toast.error('儲存失敗')
    }
    setSavingRules(false)
  }

  // 分類操作 helpers
  const addCategory = () => {
    const name = newCatName.trim()
    if (!name) return
    if (topicCategories.some(c => c.name === name && c.lang === newCatLang)) return
    setTopicCategories(prev => [...prev, { name, lang: newCatLang, keywords: [] }])
    setNewCatName('')
  }
  const removeCategory = (idx) => setTopicCategories(prev => prev.filter((_, i) => i !== idx))
  const addKwToCategory = (idx, kw) => {
    if (!kw) return
    setTopicCategories(prev => prev.map((c, i) => i === idx && !c.keywords.includes(kw) ? { ...c, keywords: [...c.keywords, kw] } : c))
  }
  const removeKwFromCategory = (idx, kw) => {
    setTopicCategories(prev => prev.map((c, i) => i === idx ? { ...c, keywords: c.keywords.filter(k => k !== kw) } : c))
  }

  const handleTestRss = async (sourceId) => {
    setRssTestStates(prev => ({ ...prev, [sourceId]: { loading: true, result: null } }))
    try {
      const { data } = await settingsAPI.testRssSource(sourceId)
      setRssTestStates(prev => ({ ...prev, [sourceId]: { loading: false, result: data } }))
    } catch {
      setRssTestStates(prev => ({ ...prev, [sourceId]: { loading: false, result: { success: false, error: '測試請求失敗' } } }))
    }
  }

  const handleStartEditKws = (source) => {
    setEditingKwSources(prev => new Set([...prev, source.id]))
    setDraftKws(prev => ({ ...prev, [source.id]: [...(source.keywords || [])] }))
    setNewKwInput(prev => ({ ...prev, [source.id]: '' }))
  }
  const handleCancelEditKws = (id) => {
    setEditingKwSources(prev => { const n = new Set(prev); n.delete(id); return n })
  }
  const handleSaveSourceKws = async (id) => {
    try {
      await settingsAPI.updateSource(id, { keywords: draftKws[id] || [] })
      setSources(prev => prev.map(s => s.id === id ? { ...s, keywords: draftKws[id] || [] } : s))
      handleCancelEditKws(id)
      toast.success('關鍵字已更新')
    } catch {
      toast.error('更新失敗')
    }
  }
  const handleStartEditUrl = (source) => {
    setEditingUrlSources(prev => new Set([...prev, source.id]))
    setDraftUrl(prev => ({ ...prev, [source.id]: source.url }))
  }
  const handleCancelEditUrl = (id) => {
    setEditingUrlSources(prev => { const n = new Set(prev); n.delete(id); return n })
  }
  const handleSaveSourceUrl = async (id) => {
    try {
      await settingsAPI.updateSource(id, { url: draftUrl[id] })
      setSources(prev => prev.map(s => s.id === id ? { ...s, url: draftUrl[id] } : s))
      handleCancelEditUrl(id)
      toast.success('URL 已更新')
    } catch {
      toast.error('更新失敗')
    }
  }

  const handleRenameSave = async (id, name) => {
    const trimmed = (name || '').trim()
    setEditingSourceName(p => { const n = { ...p }; delete n[id]; return n })
    if (!trimmed) return
    try {
      await settingsAPI.updateSource(id, { name: trimmed })
      setSources(prev => prev.map(s => s.id === id ? { ...s, name: trimmed } : s))
    } catch { toast.error('更名失敗') }
  }

  const handleDragStart = (e, sourceId) => {
    setDragSourceId(sourceId)
    e.dataTransfer.effectAllowed = 'move'
  }
  const handleDragOver = (e, targetId) => {
    e.preventDefault()
    if (targetId !== dragSourceId) setDragOverId(targetId)
  }
  const handleDrop = async (e, targetId) => {
    e.preventDefault()
    const fromId = dragSourceId
    setDragSourceId(null)
    setDragOverId(null)
    if (!fromId || fromId === targetId) return
    const tabSources = sources.filter(s => sourceTab === 'research' ? s.type === 'research' : s.type !== 'research')
    const fromIdx = tabSources.findIndex(s => s.id === fromId)
    const toIdx = tabSources.findIndex(s => s.id === targetId)
    if (fromIdx < 0 || toIdx < 0) return
    const reordered = [...tabSources]
    const [moved] = reordered.splice(fromIdx, 1)
    reordered.splice(toIdx, 0, moved)
    const orderIds = reordered.map(s => s.id)
    setSources(prev => {
      const others = prev.filter(s => sourceTab === 'research' ? s.type !== 'research' : s.type === 'research')
      return sourceTab === 'research' ? [...others, ...reordered] : [...reordered, ...others]
    })
    try {
      await settingsAPI.reorderSources(orderIds)
    } catch { toast.error('排序儲存失敗'); loadSettings() }
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


  const handleSaveFinanceFilter = async () => {
    setSavingFinanceFilter(true)
    try {
      await settingsAPI.updateFinanceFilter(financeFilterEnabled, financeThreshold)
      toast.success('財經篩選設定已儲存')
    } catch {
      toast.error('儲存失敗')
    }
    setSavingFinanceFilter(false)
  }

  const handleSaveRssPriority = async () => {
    setSavingRssPriority(true)
    try {
      await settingsAPI.updateRssPriority(rssMinArticles)
      toast.success('RSS 優先設定已儲存')
    } catch {
      toast.error('儲存失敗')
    }
    setSavingRssPriority(false)
  }

  const handleSaveGnCriticalOnly = async () => {
    try {
      await settingsAPI.updateGnCriticalOnly(gnCriticalOnly)
      toast.success('Google News 篩選設定已儲存')
    } catch {
      toast.error('儲存失敗')
    }
  }

  const handleSaveTopics = async () => {
    setSavingTopics(true)
    try {
      // 從分類結構展平成 radar_topics / radar_topics_us
      const twKws = topicCategories.filter(c => c.lang === 'tw').flatMap(c => c.keywords)
      const enKws = topicCategories.filter(c => c.lang === 'en').flatMap(c => c.keywords)
      await settingsAPI.updateRadarTopics(twKws, radarHoursBack, radarIntervalMinutes, enKws, radarRssOnly, exclusionKeywords)
      await settingsAPI.updateTopicCategories(topicCategories)
      setRadarTopics(twKws)
      setRadarTopicsUs(enKws)
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
              <span className="text-xs text-dark-500">({sources.filter(s => sourceTab === 'research' ? s.type === 'research' : s.type !== 'research').length} 個)</span>
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

        {/* 來源分類 tab */}
        <div className="flex rounded-lg bg-dark-800 p-0.5 w-fit mb-4">
          <button
            onClick={() => setSourceTab('news')}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${sourceTab === 'news' ? 'bg-primary-600 text-white' : 'text-dark-400 hover:text-white'}`}
          >
            新聞來源 ({sources.filter(s => s.type !== 'research').length})
          </button>
          <button
            onClick={() => setSourceTab('research')}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${sourceTab === 'research' ? 'bg-primary-600 text-white' : 'text-dark-400 hover:text-white'}`}
          >
            研究報告 ({sources.filter(s => s.type === 'research').length})
          </button>
        </div>

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
          {sources.filter(s => sourceTab === 'research' ? s.type === 'research' : s.type !== 'research').map(source => {
            const isExpanded = expandedSources.has(source.id)
            return (
              <div
                key={source.id}
                className={`rounded-lg bg-dark-900 overflow-hidden transition-all ${dragOverId === source.id ? 'ring-2 ring-primary-500/40' : ''}`}
                onDragOver={(e) => handleDragOver(e, source.id)}
                onDrop={(e) => handleDrop(e, source.id)}
              >
                {/* Header row */}
                <div className="flex items-center p-3 hover:bg-dark-800/50 transition-colors gap-2">
                  {/* Drag handle */}
                  <div
                    draggable
                    onDragStart={(e) => handleDragStart(e, source.id)}
                    onDragEnd={() => { setDragSourceId(null); setDragOverId(null) }}
                    className="cursor-grab active:cursor-grabbing text-dark-700 hover:text-dark-500 transition-colors select-none shrink-0 px-0.5 text-base leading-none"
                    title="拖曳排序"
                  >⠿</div>
                  {/* Expand clickable area */}
                  <div
                    className="flex items-center gap-3 flex-1 min-w-0 cursor-pointer"
                    onClick={() => toggleSourceExpand(source.id)}
                  >
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
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      {/* Inline name edit */}
                      {editingSourceName[source.id] !== undefined ? (
                        <input
                          value={editingSourceName[source.id]}
                          onChange={e => setEditingSourceName(p => ({ ...p, [source.id]: e.target.value }))}
                          onKeyDown={e => {
                            if (e.key === 'Enter') handleRenameSave(source.id, editingSourceName[source.id])
                            if (e.key === 'Escape') setEditingSourceName(p => { const n = { ...p }; delete n[source.id]; return n })
                          }}
                          onBlur={() => handleRenameSave(source.id, editingSourceName[source.id])}
                          onClick={e => e.stopPropagation()}
                          className="input text-sm py-0.5 px-2 w-36 shrink-0"
                          autoFocus
                        />
                      ) : (
                        <div className="flex items-center gap-0.5 group/name shrink-0" onClick={e => e.stopPropagation()}>
                          <span className="font-medium text-sm">{source.name}</span>
                          <button
                            onClick={e => { e.stopPropagation(); setEditingSourceName(p => ({ ...p, [source.id]: source.name })) }}
                            className="text-dark-700 hover:text-dark-400 text-xs opacity-0 group-hover/name:opacity-100 transition-opacity px-0.5"
                            title="重新命名"
                          >✎</button>
                        </div>
                      )}
                      <span className="badge bg-dark-700 text-dark-300 shrink-0">{typeLabels[source.type] || source.type}</span>
                      {source.fetch_all && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-teal-500/20 text-teal-400 border border-teal-500/30 shrink-0" title="全文讀取：所有文章皆納入，關鍵字僅用於標記與風險評估">全文讀取</span>
                      )}
                      {source.fixed_severity && (
                        <span className={`text-xs px-1.5 py-0.5 rounded border shrink-0 ${
                          source.fixed_severity === 'critical' ? 'bg-red-500/20 text-red-400 border-red-500/30' :
                          source.fixed_severity === 'high' ? 'bg-orange-500/20 text-orange-400 border-orange-500/30' :
                          'bg-green-500/20 text-green-400 border-green-500/30'
                        }`} title="最低風險等級下限，關鍵字仍可調升">{source.fixed_severity === 'critical' ? '最低緊急' : source.fixed_severity === 'high' ? '最低高風險' : '最低低風險'}</span>
                      )}
                      {source.keywords && source.keywords.length > 0
                        ? <span className="text-xs text-dark-500">{source.keywords.length} 個關鍵字</span>
                        : !source.fetch_all && (
                          <span className="text-xs text-yellow-600/70" title="未設定關鍵字，將以雷達主題關鍵字篩選">使用雷達主題篩選</span>
                        )
                      }
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
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
                      className={`w-4 h-4 text-dark-500 transition-transform cursor-pointer ${isExpanded ? 'rotate-180' : ''}`}
                      onClick={() => toggleSourceExpand(source.id)}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="px-4 pb-3 border-t border-dark-700/50 pt-3 space-y-2" onClick={e => e.stopPropagation()}>
                    {/* URL row */}
                    {editingUrlSources.has(source.id) ? (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-dark-500 shrink-0">URL</span>
                        <input
                          value={draftUrl[source.id] || ''}
                          onChange={e => setDraftUrl(prev => ({ ...prev, [source.id]: e.target.value }))}
                          onKeyDown={e => e.key === 'Enter' && handleSaveSourceUrl(source.id)}
                          className="input text-xs py-0.5 flex-1 min-w-0"
                        />
                        <button onClick={() => handleSaveSourceUrl(source.id)} className="btn-primary text-xs px-2 py-0.5 shrink-0">儲存</button>
                        <button onClick={() => handleCancelEditUrl(source.id)} className="btn-secondary text-xs px-2 py-0.5 shrink-0">取消</button>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-dark-500 shrink-0">URL</span>
                          <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-xs text-dark-400 hover:underline break-all flex-1 min-w-0 font-mono">{source.url}</a>
                          <button onClick={() => handleStartEditUrl(source)} className="text-dark-600 hover:text-primary-400 text-xs px-1 transition-colors shrink-0" title="編輯 URL">✎</button>
                        </div>
                        {getBrowseUrl(source.url) && (
                          <div className="flex items-center gap-2 pl-8">
                            <span className="text-xs text-dark-600 shrink-0">網站</span>
                            <a href={getBrowseUrl(source.url)} target="_blank" rel="noopener noreferrer"
                               className="text-xs text-primary-400 hover:underline break-all flex-1 min-w-0">
                              {getBrowseUrl(source.url)}
                            </a>
                          </div>
                        )}
                      </div>
                    )}
                    {/* 來源類型 */}
                    {source.type !== 'mops' && source.type !== 'research' && (
                      <div className="flex items-center gap-2 py-0.5">
                        <span className="text-xs text-dark-500 shrink-0">類型</span>
                        <select
                          value={source.type}
                          onChange={async (e) => {
                            const newType = e.target.value
                            try {
                              await settingsAPI.updateSource(source.id, { type: newType })
                              setSources(prev => prev.map(s => s.id === source.id ? { ...s, type: newType } : s))
                              toast.success('類型已更新')
                            } catch {
                              toast.error('更新失敗')
                            }
                          }}
                          className="text-xs bg-dark-700 border border-dark-600 rounded px-2 py-1 text-dark-300"
                        >
                          <option value="rss">RSS</option>
                          <option value="website">網頁爬蟲</option>
                          <option value="social">社群</option>
                        </select>
                      </div>
                    )}
                    {/* Keywords row */}
                    {editingKwSources.has(source.id) ? (
                      <div className="space-y-1.5">
                        <div className="flex flex-wrap gap-1 min-h-6">
                          {(draftKws[source.id] || []).map((kw, i) => (
                            <span key={i} className="flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-dark-700 text-dark-300">
                              {kw}
                              <button onClick={() => setDraftKws(prev => ({ ...prev, [source.id]: prev[source.id].filter((_, j) => j !== i) }))} className="hover:text-red-400 ml-0.5 leading-none">×</button>
                            </span>
                          ))}
                          {(draftKws[source.id] || []).length === 0 && <span className="text-xs text-dark-600">尚無關鍵字（將以雷達主題篩選）</span>}
                        </div>
                        <div className="flex gap-1.5">
                          <input
                            value={newKwInput[source.id] || ''}
                            onChange={e => setNewKwInput(prev => ({ ...prev, [source.id]: e.target.value }))}
                            onKeyDown={e => {
                              if (e.key === 'Enter') {
                                const kw = (newKwInput[source.id] || '').trim()
                                if (!kw) return
                                setDraftKws(prev => ({ ...prev, [source.id]: [...(prev[source.id] || []), kw] }))
                                setNewKwInput(prev => ({ ...prev, [source.id]: '' }))
                              }
                            }}
                            placeholder="輸入後 Enter 新增"
                            className="input text-xs py-0.5 flex-1"
                          />
                          <button
                            onClick={() => {
                              const kw = (newKwInput[source.id] || '').trim()
                              if (!kw) return
                              setDraftKws(prev => ({ ...prev, [source.id]: [...(prev[source.id] || []), kw] }))
                              setNewKwInput(prev => ({ ...prev, [source.id]: '' }))
                            }}
                            className="text-dark-400 hover:text-primary-400 text-sm px-1.5"
                          >+</button>
                        </div>
                        <div className="flex gap-1.5">
                          <button onClick={() => handleSaveSourceKws(source.id)} className="btn-primary text-xs px-3 py-1">儲存</button>
                          <button onClick={() => handleCancelEditKws(source.id)} className="btn-secondary text-xs px-3 py-1">取消</button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start gap-2">
                        <div className="flex flex-wrap gap-1 flex-1 min-w-0">
                          {source.keywords && source.keywords.length > 0
                            ? source.keywords.map(kw => (
                                <span key={kw} className="text-xs px-1.5 py-0.5 rounded bg-dark-700 text-dark-300">{kw}</span>
                              ))
                            : <span className="text-xs text-dark-600">尚無關鍵字（將以雷達主題篩選）</span>
                          }
                        </div>
                        <button onClick={() => handleStartEditKws(source)} className="text-dark-600 hover:text-primary-400 text-xs px-1 transition-colors shrink-0 whitespace-nowrap" title="編輯關鍵字">✎ 關鍵字</button>
                      </div>
                    )}
                    {/* 全文讀取 toggle */}
                    <div className="flex items-center justify-between py-1">
                        <div>
                          <span className="text-xs text-dark-300 font-medium">全文讀取</span>
                          <span className="text-xs text-dark-500 ml-2">
                            {source.fetch_all ? '所有文章皆納入，關鍵字僅標記與評估風險' : '只納入符合關鍵字的文章'}
                          </span>
                        </div>
                        <button
                          onClick={async () => {
                            try {
                              await settingsAPI.updateSource(source.id, { fetch_all: !source.fetch_all })
                              setSources(prev => prev.map(s => s.id === source.id ? { ...s, fetch_all: !source.fetch_all } : s))
                              toast.success(source.fetch_all ? '已關閉全文讀取' : '已開啟全文讀取')
                            } catch {
                              toast.error('更新失敗')
                            }
                          }}
                          className={`w-10 h-6 rounded-full transition-colors relative shrink-0 ${
                            source.fetch_all ? 'bg-teal-600' : 'bg-dark-600'
                          }`}
                        >
                          <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${
                            source.fetch_all ? 'translate-x-5' : 'translate-x-1'
                          }`} />
                        </button>
                    </div>
                    {/* 固定風險等級 */}
                    <div className="flex items-center justify-between py-1">
                      <div>
                        <span className="text-xs text-dark-300 font-medium">最低風險等級</span>
                        <span className="text-xs text-dark-500 ml-2">
                          {source.fixed_severity ? `最低為「${
                            source.fixed_severity === 'critical' ? '緊急' :
                            source.fixed_severity === 'high' ? '高風險' : '低風險'
                          }」，關鍵字可再調升` : '依關鍵字動態評估'}
                        </span>
                      </div>
                      <select
                        value={source.fixed_severity || ''}
                        onChange={async (e) => {
                          const val = e.target.value
                          try {
                            await settingsAPI.updateSource(source.id, { fixed_severity: val })
                            setSources(prev => prev.map(s => s.id === source.id
                              ? { ...s, fixed_severity: val || null }
                              : s
                            ))
                            toast.success(val ? `已設為${val === 'critical' ? '緊急' : val === 'high' ? '高風險' : '低風險'}` : '已恢復動態評估')
                          } catch {
                            toast.error('更新失敗')
                          }
                        }}
                        className="text-xs bg-dark-700 border border-dark-600 rounded px-2 py-1 text-dark-300"
                      >
                        <option value="">動態評估</option>
                        <option value="critical">🔴 緊急</option>
                        <option value="high">🟠 高風險</option>
                        <option value="low">🟢 低風險</option>
                      </select>
                    </div>
                    {/* 連線測試按鈕（RSS / social / website / mops 均支援）*/}
                    {(source.type === 'rss' || source.type === 'social' || source.type === 'website' || source.type === 'mops') && (
                      <div>
                        <button
                          onClick={() => handleTestRss(source.id)}
                          disabled={rssTestStates[source.id]?.loading}
                          className="text-xs px-2.5 py-1 rounded border border-dark-600 text-dark-400 hover:text-primary-400 hover:border-primary-500/50 transition-colors disabled:opacity-50"
                        >
                          {rssTestStates[source.id]?.loading ? '測試中...' : (source.type === 'website' ? '測試連線' : source.type === 'mops' ? '測試爬蟲' : '測試 RSS 連線')}
                        </button>
                        {rssTestStates[source.id]?.result && (
                          <div className={`mt-2 p-2 rounded text-xs border ${
                            rssTestStates[source.id].result.success
                              ? 'bg-green-500/10 text-green-400 border-green-500/20'
                              : 'bg-red-500/10 text-red-400 border-red-500/20'
                          }`}>
                            {rssTestStates[source.id].result.success ? (
                              <>
                                <div>✓ 成功
                                  {rssTestStates[source.id].result.count >= 0 && (
                                    <span>：共 {rssTestStates[source.id].result.count} 則文章</span>
                                  )}
                                  {rssTestStates[source.id].result.feed_title && (
                                    <span className="text-dark-400 ml-1">（{rssTestStates[source.id].result.feed_title}）</span>
                                  )}
                                </div>
                                {rssTestStates[source.id].result.sample_titles?.length > 0 && (
                                  <ul className="mt-1 space-y-0.5 text-dark-400">
                                    {rssTestStates[source.id].result.sample_titles.map((t, i) => (
                                      <li key={i} className="truncate">・{t}</li>
                                    ))}
                                  </ul>
                                )}
                              </>
                            ) : (
                              <div>✗ {rssTestStates[source.id].result.error}</div>
                            )}
                          </div>
                        )}
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
      <section className="card space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold">雷達關鍵字</h3>
            <p className="text-sm text-dark-400">用於 Google News 搜尋，同時也是未設關鍵字的 RSS 來源之篩選依據</p>
          </div>
          <button onClick={handleSaveTopics} disabled={savingTopics} className="btn-primary text-sm flex items-center gap-1.5">
            {savingTopics && <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white" />}
            儲存
          </button>
        </div>

        {/* RSS-only toggle */}
        <div className="flex items-center justify-between p-3 rounded-lg border border-dark-700 bg-dark-900/40">
          <div>
            <p className="text-sm font-medium">僅使用 RSS 來源</p>
            <p className="text-xs text-dark-400 mt-0.5">停用 Google News 搜尋，雷達只抓訂閱的 RSS 來源（雜訊更少）</p>
          </div>
          <button
            type="button"
            onClick={() => setRadarRssOnly(v => !v)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${radarRssOnly ? 'bg-primary-600' : 'bg-dark-600'}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${radarRssOnly ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>

        {/* 分類關鍵字卡片 */}
        {topicCategories.map((cat, ci) => {
          const c = CAT_COLORS[ci % CAT_COLORS.length]
          const simpleKws = cat.keywords.filter(k => !k.includes('('))
          const groupedKws = cat.keywords.filter(k => k.includes('('))
          const isEn = cat.lang === 'en'
          return (
            <div key={ci} className={`p-4 rounded-lg border space-y-3 ${isEn ? 'border-amber-500/20 bg-amber-500/5' : 'border-dark-700 bg-dark-900/40'}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-2.5 h-2.5 rounded-full ${c.dot}`} />
                  <span className={`text-sm font-semibold ${c.text}`}>{cat.name}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${isEn ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'}`}>
                    {isEn ? 'EN' : 'TW'}
                  </span>
                  <span className="text-xs text-dark-500">{cat.keywords.length} 個關鍵字</span>
                </div>
                <button onClick={() => removeCategory(ci)} className="text-dark-600 hover:text-red-400 text-xs transition-colors">刪除分類</button>
              </div>

              {/* 單一關鍵字 */}
              {simpleKws.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {simpleKws.map(kw => {
                    const isCrit = severityKws.critical.includes(kw)
                    const isHigh = severityKws.high.includes(kw)
                    return (
                      <span key={kw} className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${c.bg} ${c.text} ${c.border}`}>
                        {isCrit && <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />}
                        {!isCrit && isHigh && <span className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" />}
                        {kw}
                        <button onClick={() => removeKwFromCategory(ci, kw)} className="ml-0.5 opacity-60 hover:text-red-400 hover:opacity-100 leading-none">×</button>
                      </span>
                    )
                  })}
                </div>
              )}

              {/* 布林組合 */}
              {groupedKws.length > 0 && (
                <div className="flex flex-col gap-2">
                  {groupedKws.map(topic => (
                    <GroupedKeywordCard key={topic} topicStr={topic}
                      onSave={newStr => setTopicCategories(prev => prev.map((cc, i) => i === ci ? { ...cc, keywords: cc.keywords.map(k => k === topic ? newStr : k) } : cc))}
                      onRemove={() => removeKwFromCategory(ci, topic)}
                      onSplit={terms => setTopicCategories(prev => prev.map((cc, i) => i === ci ? { ...cc, keywords: [...cc.keywords.filter(k => k !== topic), ...terms.filter(t => !cc.keywords.includes(t))] } : cc))}
                      severityKws={severityKws} onAddToSeverity={handleAddToSeverity}
                    />
                  ))}
                </div>
              )}

              {cat.keywords.length === 0 && <span className="text-xs text-dark-500">尚無關鍵字</span>}

              {/* 新增關鍵字 */}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newCatKws[ci] || ''}
                  onChange={e => setNewCatKws(p => ({ ...p, [ci]: e.target.value }))}
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      const kw = (newCatKws[ci] || '').trim()
                      if (kw) { addKwToCategory(ci, kw); setNewCatKws(p => ({ ...p, [ci]: '' })) }
                    }
                  }}
                  placeholder={isEn ? 'English keyword, press Enter' : '輸入關鍵字，按 Enter 新增'}
                  className="input text-sm flex-1"
                />
                <button onClick={() => { const kw = (newCatKws[ci] || '').trim(); if (kw) { addKwToCategory(ci, kw); setNewCatKws(p => ({ ...p, [ci]: '' })) } }} className="btn-secondary text-sm px-3">新增</button>
                <button type="button" onClick={() => setShowCatGroupBuilder(showCatGroupBuilder === ci ? null : ci)} className="btn-secondary text-sm px-3 whitespace-nowrap">{showCatGroupBuilder === ci ? '取消' : '+ 布林'}</button>
              </div>
              {showCatGroupBuilder === ci && (
                <NewGroupedBuilder onAdd={str => { addKwToCategory(ci, str); setShowCatGroupBuilder(null) }} onClose={() => setShowCatGroupBuilder(null)} />
              )}
            </div>
          )
        })}

        {/* 新增分類 */}
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={newCatName}
            onChange={e => setNewCatName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addCategory() }}
            placeholder="新增分類名稱（例：央行政策）"
            className="input text-sm flex-1"
          />
          <select value={newCatLang} onChange={e => setNewCatLang(e.target.value)} className="input text-sm w-24">
            <option value="tw">TW</option>
            <option value="en">EN</option>
          </select>
          <button onClick={addCategory} className="btn-secondary text-sm px-4">新增分類</button>
        </div>

        {/* 全域排除關鍵字 */}
        <div className="p-3 rounded-lg border border-red-500/20 bg-red-500/5 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-red-400">全域排除關鍵字</span>
            <span className="text-xs text-dark-500">文章標題或內文包含以下任一詞，即不抓取（適用所有來源）</span>
          </div>
          <div className="flex flex-wrap gap-1.5 min-h-6">
            {exclusionKeywords.map((kw, i) => (
              <span key={i} className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">
                {kw}
                <button
                  onClick={() => setExclusionKeywords(prev => prev.filter((_, j) => j !== i))}
                  className="hover:text-red-300 ml-0.5 leading-none">×</button>
              </span>
            ))}
            {exclusionKeywords.length === 0 && <span className="text-xs text-dark-600">尚無排除關鍵字</span>}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={newExclusionKw}
              onChange={e => setNewExclusionKw(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  const kw = newExclusionKw.trim()
                  if (!kw || exclusionKeywords.includes(kw)) { setNewExclusionKw(''); return }
                  setExclusionKeywords(prev => [...prev, kw])
                  setNewExclusionKw('')
                }
              }}
              placeholder="輸入排除詞後按 Enter"
              className="input text-sm flex-1 border-red-500/30 focus:border-red-500/60"
            />
            <button
              onClick={() => {
                const kw = newExclusionKw.trim()
                if (!kw || exclusionKeywords.includes(kw)) { setNewExclusionKw(''); return }
                setExclusionKeywords(prev => [...prev, kw])
                setNewExclusionKw('')
              }}
              className="btn-secondary text-sm px-3"
            >新增</button>
          </div>
        </div>

        {/* Hours Back + Interval Settings */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 pt-3 border-t border-dark-700">
          <div className="flex items-center gap-3">
            <span className="text-sm text-dark-400 whitespace-nowrap">掃描時間範圍</span>
            <select value={radarHoursBack} onChange={e => setRadarHoursBack(Number(e.target.value))} className="input text-sm w-40">
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
            <select value={radarIntervalMinutes} onChange={e => setRadarIntervalMinutes(Number(e.target.value))} className="input text-sm w-36">
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
        <p className="text-xs text-dark-500">
          支援 Google 搜尋語法：<code className="bg-dark-700 px-1 rounded">OR</code> 聯集 · <code className="bg-dark-700 px-1 rounded">"精確詞"</code> 完全比對 · <code className="bg-dark-700 px-1 rounded">AND</code> 交集（空格即 AND）· 布林組合可在「排除詞（NOT）」欄位加入關鍵字排除
        </p>
      </section>

      {/* 新聞篩選強化設定 */}
      <section className="card space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold">新聞篩選強化</h3>
            <p className="text-sm text-dark-400 mt-0.5">降低雜訊：RSS 優先策略 + 本地財經相關性篩選（不呼叫 API）</p>
          </div>
          <button onClick={() => { handleSaveFinanceFilter(); handleSaveRssPriority(); handleSaveGnCriticalOnly() }}
            disabled={savingFinanceFilter || savingRssPriority}
            className="btn-primary text-sm flex items-center gap-1.5">
            {(savingFinanceFilter || savingRssPriority) && <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white" />}
            儲存
          </button>
        </div>

        {/* RSS 優先模式 */}
        <div className="p-3 rounded-lg border border-dark-700 bg-dark-900/40 space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">RSS 優先模式</p>
              <p className="text-xs text-dark-400 mt-0.5">RSS 文章數達到門檻後自動跳過 Google News，減少不相關新聞</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-xs text-dark-400 whitespace-nowrap">RSS 文章數門檻</label>
            <input
              type="number"
              min="0"
              max="50"
              value={rssMinArticles}
              onChange={e => setRssMinArticles(parseInt(e.target.value) || 0)}
              className="input w-20 text-sm"
            />
            <span className="text-xs text-dark-400">篇（0 = 停用，每次都執行 Google News）</span>
          </div>
        </div>

        {/* Google News 僅緊急 */}
        <div className="p-3 rounded-lg border border-dark-700 bg-dark-900/40 space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Google News 僅緊急</p>
              <p className="text-xs text-dark-400 mt-0.5">Google News 文章篩選為僅緊急，RSS 來源不受影響</p>
            </div>
            <button
              type="button"
              onClick={() => setGnCriticalOnly(v => !v)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${gnCriticalOnly ? 'bg-primary-600' : 'bg-dark-600'}`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${gnCriticalOnly ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>
        </div>

        {/* 財經相關性篩選 */}
        <div className="p-3 rounded-lg border border-dark-700 bg-dark-900/40 space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">財經相關性篩選</p>
              <p className="text-xs text-dark-400 mt-0.5">依內文財經詞彙密度過濾非相關文章（本地計算，無 API 費用）</p>
            </div>
            <button
              type="button"
              onClick={() => setFinanceFilterEnabled(v => !v)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${financeFilterEnabled ? 'bg-primary-600' : 'bg-dark-600'}`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${financeFilterEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>
          {financeFilterEnabled && (
            <div className="flex items-center gap-3">
              <label className="text-xs text-dark-400 whitespace-nowrap">相關性門檻</label>
              <input
                type="number"
                min="0.01"
                max="1.0"
                step="0.01"
                value={financeThreshold}
                onChange={e => setFinanceThreshold(parseFloat(e.target.value) || 0.15)}
                className="input w-24 text-sm"
              />
              <span className="text-xs text-dark-400">（建議 0.10 ~ 0.25，越高越嚴格）</span>
            </div>
          )}
        </div>
      </section>

      {/* Severity Settings (Keywords + Boolean Rules merged) */}
      <section className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold">風險程度設定</h3>
            <p className="text-sm text-dark-400 mt-0.5">判斷順序：布林規則（優先）→ 關鍵字列表 → 低（預設）</p>
          </div>
          <div className="flex rounded-lg overflow-hidden border border-dark-600 shrink-0">
            <button
              onClick={() => setSeverityTab('keywords')}
              className={`text-sm px-4 py-1.5 transition-colors ${severityTab === 'keywords' ? 'bg-primary-600 text-white' : 'bg-dark-800 text-dark-400 hover:text-white'}`}
            >關鍵字</button>
            <button
              onClick={() => setSeverityTab('rules')}
              className={`text-sm px-4 py-1.5 transition-colors border-l border-dark-600 ${severityTab === 'rules' ? 'bg-primary-600 text-white' : 'bg-dark-800 text-dark-400 hover:text-white'}`}
            >布林規則 {severityRules.length > 0 && <span className="ml-1 text-xs bg-primary-500/30 text-primary-300 px-1.5 rounded-full">{severityRules.length}</span>}</button>
          </div>
        </div>

        {severityTab === 'keywords' && (
          <div className="space-y-5">
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
          </div>
        )}

        {severityTab === 'rules' && (
          <div className="space-y-3">
            <p className="text-xs text-dark-500">優先於關鍵字列表評估；第一條命中的規則決定嚴重度。每個方塊為 AND 條件，同方塊內多詞為 OR 選一。</p>

            <div className="space-y-2">
              {severityRules.length === 0 && !showRuleBuilder && (
                <div className="text-xs text-dark-500 py-1">尚無規則，目前僅使用關鍵字列表</div>
              )}
              {severityRules.map((rule, idx) => (
                <SeverityRuleCard
                  key={idx}
                  rule={rule}
                  onSave={updated => setSeverityRules(r => r.map((x, i) => i === idx ? updated : x))}
                  onRemove={() => setSeverityRules(r => r.filter((_, i) => i !== idx))}
                  canMoveUp={idx > 0}
                  canMoveDown={idx < severityRules.length - 1}
                  onMoveUp={() => setSeverityRules(r => { const a = [...r]; [a[idx-1], a[idx]] = [a[idx], a[idx-1]]; return a })}
                  onMoveDown={() => setSeverityRules(r => { const a = [...r]; [a[idx], a[idx+1]] = [a[idx+1], a[idx]]; return a })}
                />
              ))}
            </div>

            {showRuleBuilder
              ? <NewRuleBuilder
                  onAdd={rule => { setSeverityRules(r => [...r, rule]); setShowRuleBuilder(false) }}
                  onClose={() => setShowRuleBuilder(false)}
                />
              : <button
                  type="button"
                  onClick={() => setShowRuleBuilder(true)}
                  className="text-sm px-3 py-1.5 rounded border border-dashed border-dark-600 text-dark-500 hover:text-primary-400 hover:border-primary-500/50 transition-colors"
                >+ 新增規則</button>
            }

            <div className="flex items-center gap-3 pt-2 border-t border-dark-700">
              <button onClick={handleSaveRules} disabled={savingRules} className="btn-primary text-sm">
                {savingRules ? '儲存中...' : '儲存規則'}
              </button>
              <span className="text-xs text-dark-500">規則按順序評估，第一條命中即採用，後續略過</span>
            </div>
          </div>
        )}
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
