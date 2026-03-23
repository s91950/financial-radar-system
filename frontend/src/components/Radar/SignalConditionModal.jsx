import { useEffect, useState } from 'react'
import { radarAPI } from '../../services/api'
import { toast } from 'react-hot-toast'

const OPERATORS = [
  { value: 'gt', label: '>' },
  { value: 'lt', label: '<' },
  { value: 'gte', label: '>=' },
  { value: 'lte', label: '<=' },
  { value: 'between', label: '介於' },
]

const SIGNALS = [
  { value: 'positive', label: '正面', color: 'text-green-400', dot: 'bg-green-400' },
  { value: 'neutral', label: '中性', color: 'text-yellow-400', dot: 'bg-yellow-400' },
  { value: 'negative', label: '負面', color: 'text-red-400', dot: 'bg-red-400' },
]

export default function SignalConditionModal({ item, onClose }) {
  const [conditions, setConditions] = useState([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(defaultForm())

  function defaultForm() {
    return { name: '', operator: 'gt', value: '', value2: '', signal: 'negative', message: '', priority: 0 }
  }

  useEffect(() => {
    loadConditions()
  }, [item.id])

  async function loadConditions() {
    try {
      const { data } = await radarAPI.getConditions(item.id)
      setConditions(data)
    } catch (err) {
      console.error(err)
    }
    setLoading(false)
  }

  async function handleSave() {
    if (!form.name || !form.value) {
      toast.error('請填入條件名稱和數值')
      return
    }
    const payload = {
      ...form,
      value: parseFloat(form.value),
      value2: form.operator === 'between' && form.value2 ? parseFloat(form.value2) : null,
      priority: parseInt(form.priority) || 0,
    }
    try {
      if (editingId) {
        await radarAPI.updateCondition(editingId, payload)
        toast.success('條件已更新')
      } else {
        await radarAPI.createCondition(item.id, payload)
        toast.success('條件已新增')
      }
      setForm(defaultForm())
      setEditingId(null)
      loadConditions()
    } catch (err) {
      toast.error('操作失敗')
    }
  }

  async function handleDelete(condId) {
    try {
      await radarAPI.deleteCondition(condId)
      toast.success('條件已刪除')
      loadConditions()
    } catch (err) {
      toast.error('刪除失敗')
    }
  }

  function startEdit(cond) {
    setEditingId(cond.id)
    setForm({
      name: cond.name || '',
      operator: cond.operator,
      value: String(cond.value ?? ''),
      value2: String(cond.value2 ?? ''),
      signal: cond.signal,
      message: cond.message || '',
      priority: cond.priority ?? 0,
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setForm(defaultForm())
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-dark-800 rounded-xl border border-dark-600 w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-dark-700">
          <div>
            <h3 className="font-semibold text-lg">{item.name}</h3>
            <p className="text-sm text-dark-400">信號條件設定 — {item.symbol}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-dark-700 text-dark-400 hover:text-white">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Condition List */}
        <div className="px-5 py-4 space-y-2">
          {loading ? (
            <div className="text-center text-dark-400 py-4">載入中...</div>
          ) : conditions.length === 0 ? (
            <div className="text-center text-dark-400 py-4 text-sm">尚無信號條件，請新增</div>
          ) : (
            conditions.map((cond) => (
              <div key={cond.id} className="flex items-center gap-3 bg-dark-700/50 rounded-lg px-3 py-2">
                <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                  SIGNALS.find(s => s.value === cond.signal)?.dot || 'bg-gray-400'
                }`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{cond.name}</span>
                    <span className="text-xs text-dark-400">P:{cond.priority}</span>
                  </div>
                  <div className="text-xs text-dark-400">{cond.message}</div>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => startEdit(cond)} className="p-1 rounded hover:bg-dark-600 text-dark-400 hover:text-white">
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                    </svg>
                  </button>
                  <button onClick={() => handleDelete(cond.id)} className="p-1 rounded hover:bg-dark-600 text-dark-400 hover:text-red-400">
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                    </svg>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Add / Edit Form */}
        <div className="px-5 py-4 border-t border-dark-700 space-y-3">
          <h4 className="text-sm font-medium text-dark-300">
            {editingId ? '編輯條件' : '新增條件'}
          </h4>

          <div className="grid grid-cols-2 gap-3">
            <input
              type="text"
              placeholder="條件名稱"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="col-span-2 bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            />

            <select
              value={form.operator}
              onChange={e => setForm({ ...form, operator: e.target.value })}
              className="bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            >
              {OPERATORS.map(op => <option key={op.value} value={op.value}>{op.label}</option>)}
            </select>

            <input
              type="number"
              step="any"
              placeholder="數值"
              value={form.value}
              onChange={e => setForm({ ...form, value: e.target.value })}
              className="bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            />

            {form.operator === 'between' && (
              <input
                type="number"
                step="any"
                placeholder="第二數值"
                value={form.value2}
                onChange={e => setForm({ ...form, value2: e.target.value })}
                className="col-span-2 bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
              />
            )}

            <div className="flex gap-2">
              {SIGNALS.map(sig => (
                <button
                  key={sig.value}
                  onClick={() => setForm({ ...form, signal: sig.value })}
                  className={`flex items-center gap-1 px-2 py-1 rounded text-xs border transition-colors ${
                    form.signal === sig.value
                      ? 'border-primary-500/50 bg-primary-500/10 text-white'
                      : 'border-dark-600 text-dark-400 hover:border-dark-500'
                  }`}
                >
                  <span className={`w-2 h-2 rounded-full ${sig.dot}`} />
                  {sig.label}
                </button>
              ))}
            </div>

            <input
              type="number"
              placeholder="優先序 (數字小優先)"
              value={form.priority}
              onChange={e => setForm({ ...form, priority: e.target.value })}
              className="bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            />

            <input
              type="text"
              placeholder="觸發訊息描述"
              value={form.message}
              onChange={e => setForm({ ...form, message: e.target.value })}
              className="col-span-2 bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            />
          </div>

          <div className="flex gap-2 justify-end">
            {editingId && (
              <button onClick={cancelEdit} className="btn-secondary text-sm px-4 py-1.5">取消</button>
            )}
            <button onClick={handleSave} className="btn-primary text-sm px-4 py-1.5">
              {editingId ? '更新' : '新增'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
