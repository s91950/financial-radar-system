import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'react-hot-toast'
import { youtubeAPI, copyToClipboard } from '../services/api'

// ─── Helpers ────────────────────────────────────────────────────────────────

function timeAgo(iso) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 60) return `${m} 分鐘前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小時前`
  const d = Math.floor(h / 24)
  return `${d} 天前`
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-TW', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

// ─── Add Channel Modal ───────────────────────────────────────────────────────

function AddChannelModal({ onClose, onAdded }) {
  const [url, setUrl] = useState('')
  const [interval, setInterval] = useState(30)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!url.trim()) return
    setLoading(true)
    setError('')
    try {
      const { data } = await youtubeAPI.addChannel({ url: url.trim(), check_interval_minutes: interval })
      if (data.error) { setError(data.error); return }
      toast.success(`已新增頻道：${data.name}`)
      onAdded(data)
      onClose()
    } catch {
      setError('新增失敗，請稍後再試')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-dark-800 border border-dark-600 rounded-xl p-6 w-full max-w-md mx-4 shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-white mb-4">新增 YouTube 頻道</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-dark-300 mb-1">頻道 ID、網址或 @handle</label>
            <input
              className="input w-full"
              placeholder="例：UCxxxxxx / https://youtube.com/@CNBC / @BBCNews"
              value={url}
              onChange={e => setUrl(e.target.value)}
              autoFocus
            />
            <p className="text-xs text-dark-500 mt-1">支援頻道 ID（UCxxxxxx）、完整頻道網址或 @handle</p>
          </div>
          <div>
            <label className="block text-sm text-dark-300 mb-1">自動偵測間隔（分鐘）</label>
            <select
              className="input w-full"
              value={interval}
              onChange={e => setInterval(Number(e.target.value))}
            >
              <option value={10}>每 10 分鐘</option>
              <option value={15}>每 15 分鐘</option>
              <option value={30}>每 30 分鐘</option>
              <option value={60}>每 60 分鐘</option>
            </select>
          </div>
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <button type="button" className="btn-secondary" onClick={onClose}>取消</button>
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? '解析中…' : '新增'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Channel Card ────────────────────────────────────────────────────────────

function ChannelCard({ channel, isSelected, onClick, onDelete, onToggle }) {
  return (
    <div
      className={`card cursor-pointer transition-all ${isSelected ? 'border-primary-500/60 bg-primary-600/10' : 'card-hover'}`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          {/* YouTube icon placeholder */}
          <div className="w-10 h-10 rounded-lg bg-red-600/20 border border-red-500/30 flex items-center justify-center flex-shrink-0">
            <svg className="w-5 h-5 text-red-400" viewBox="0 0 24 24" fill="currentColor">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
            </svg>
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-white truncate">{channel.name}</p>
            <p className="text-xs text-dark-400 truncate">{channel.channel_id}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          {channel.new_video_count > 0 && (
            <span className="text-xs bg-red-500 text-white rounded-full px-2 py-0.5 font-bold">
              {channel.new_video_count} 新
            </span>
          )}
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between">
        <span className={`text-xs px-2 py-0.5 rounded-full ${channel.is_active ? 'bg-green-500/15 text-green-400' : 'bg-dark-700 text-dark-400'}`}>
          {channel.is_active ? `每 ${channel.check_interval_minutes} 分鐘` : '已暫停'}
        </span>
        <div className="flex items-center gap-1.5" onClick={e => e.stopPropagation()}>
          <button
            className="text-xs text-dark-400 hover:text-white px-2 py-0.5 rounded hover:bg-dark-700"
            onClick={() => onToggle(channel)}
          >
            {channel.is_active ? '暫停' : '啟用'}
          </button>
          <button
            className="text-xs text-dark-400 hover:text-red-400 px-2 py-0.5 rounded hover:bg-dark-700"
            onClick={() => onDelete(channel)}
          >
            刪除
          </button>
        </div>
      </div>
      {channel.last_checked_at && (
        <p className="mt-1 text-xs text-dark-500">上次檢查：{timeAgo(channel.last_checked_at)}</p>
      )}
    </div>
  )
}

// ─── Video Card ──────────────────────────────────────────────────────────────

function VideoCard({ video, onMarkSeen, isSelected, onToggleSelect }) {
  return (
    <div className={`card relative group ${video.is_new ? 'border-red-500/40' : ''} ${isSelected ? 'ring-2 ring-primary-500/60' : ''}`}>
      {/* Selection checkbox */}
      <div className="absolute top-2 left-2 z-10" onClick={e => { e.stopPropagation(); onToggleSelect(video.id) }}>
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => {}}
          className="w-4 h-4 rounded cursor-pointer accent-primary-500"
        />
      </div>
      {video.is_new && (
        <span className="absolute top-2 right-2 text-[10px] bg-red-500 text-white font-bold px-1.5 py-0.5 rounded z-10">
          NEW
        </span>
      )}
      <a href={video.url} target="_blank" rel="noopener noreferrer" className="block">
        <div className="relative w-full aspect-video rounded-lg overflow-hidden bg-dark-700 mb-3">
          <img
            src={video.thumbnail_url}
            alt={video.title}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
            onError={e => { e.target.style.display = 'none' }}
          />
          {/* Play button overlay */}
          <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="w-12 h-12 rounded-full bg-black/60 flex items-center justify-center">
              <svg className="w-5 h-5 text-white ml-1" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z"/>
              </svg>
            </div>
          </div>
        </div>
        <p className="text-sm font-medium text-white line-clamp-2 leading-snug">{video.title}</p>
      </a>
      <div className="mt-2 flex items-center justify-between">
        <div>
          {video.channel_name && (
            <p className="text-xs text-dark-400">{video.channel_name}</p>
          )}
          <p className="text-xs text-dark-500">{timeAgo(video.published_at)} · {formatDate(video.published_at)}</p>
        </div>
        {video.is_new && (
          <button
            className="text-xs text-dark-400 hover:text-white px-2 py-1 rounded hover:bg-dark-700 flex-shrink-0"
            onClick={() => onMarkSeen(video)}
          >
            標記已看
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function YouTubePage({ wsSubscribe }) {
  const [channels, setChannels] = useState([])
  const [videos, setVideos] = useState([])
  const [selectedChannel, setSelectedChannel] = useState(null) // null = all
  const [showNewOnly, setShowNewOnly] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)
  const [loadingCheck, setLoadingCheck] = useState(false)
  const [loadingVideos, setLoadingVideos] = useState(false)
  const [selectedVideos, setSelectedVideos] = useState(new Set())
  const pollRef = useRef(null)

  const loadChannels = useCallback(async () => {
    try {
      const { data } = await youtubeAPI.getChannels()
      setChannels(data)
    } catch { /* silent */ }
  }, [])

  const loadVideos = useCallback(async () => {
    setLoadingVideos(true)
    setSelectedVideos(new Set())
    try {
      const params = { limit: 60 }
      if (selectedChannel) params.channel_id = selectedChannel
      if (showNewOnly) params.new_only = true
      const { data } = await youtubeAPI.getVideos(params)
      setVideos(data)
    } catch { /* silent */ } finally {
      setLoadingVideos(false)
    }
  }, [selectedChannel, showNewOnly])

  // Initial load
  useEffect(() => { loadChannels() }, [loadChannels])
  useEffect(() => { loadVideos() }, [loadVideos])

  // Poll every 2 min for new counts
  useEffect(() => {
    pollRef.current = setInterval(loadChannels, 120_000)
    return () => clearInterval(pollRef.current)
  }, [loadChannels])

  // WebSocket: refresh when new YouTube videos arrive
  useEffect(() => {
    if (!wsSubscribe) return
    const unsub = wsSubscribe('youtube_new_videos', (msg) => {
      toast(`🎬 ${msg.data.message}`, {
        duration: 5000,
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
      loadChannels()
      loadVideos()
    })
    return unsub
  }, [wsSubscribe, loadChannels, loadVideos])

  async function handleCheckAll() {
    setLoadingCheck(true)
    try {
      const { data } = await youtubeAPI.checkAll()
      const total = data.reduce((s, r) => s + r.new_videos, 0)
      toast.success(total > 0 ? `發現 ${total} 支新影片！` : '目前無新影片')
      loadChannels()
      loadVideos()
    } catch {
      toast.error('偵測失敗')
    } finally {
      setLoadingCheck(false)
    }
  }

  async function handleCheckOne(channel) {
    try {
      const { data } = await youtubeAPI.checkChannel(channel.id)
      toast.success(data.new_videos > 0 ? `${channel.name} 有 ${data.new_videos} 支新影片` : '無新影片')
      loadChannels()
      loadVideos()
    } catch { toast.error('偵測失敗') }
  }

  async function handleToggle(channel) {
    try {
      await youtubeAPI.updateChannel(channel.id, { is_active: !channel.is_active })
      loadChannels()
    } catch { toast.error('更新失敗') }
  }

  async function handleDelete(channel) {
    if (!window.confirm(`確定要刪除頻道「${channel.name}」及所有影片記錄嗎？`)) return
    try {
      await youtubeAPI.deleteChannel(channel.id)
      if (selectedChannel === channel.id) setSelectedChannel(null)
      loadChannels()
      loadVideos()
      toast.success('已刪除')
    } catch { toast.error('刪除失敗') }
  }

  async function handleMarkSeen(video) {
    try {
      await youtubeAPI.markSeen(video.id)
      setVideos(prev => prev.map(v => v.id === video.id ? { ...v, is_new: false } : v))
      setChannels(prev => prev.map(c =>
        c.id === video.channel_db_id
          ? { ...c, new_video_count: Math.max(0, c.new_video_count - 1) }
          : c
      ))
    } catch { /* silent */ }
  }

  function handleToggleSelect(videoId) {
    setSelectedVideos(prev => {
      const next = new Set(prev)
      if (next.has(videoId)) next.delete(videoId)
      else next.add(videoId)
      return next
    })
  }

  function handleSelectAll() {
    if (selectedVideos.size === videos.length) {
      setSelectedVideos(new Set())
    } else {
      setSelectedVideos(new Set(videos.map(v => v.id)))
    }
  }

  function handleCopySelected() {
    const urls = videos.filter(v => selectedVideos.has(v.id)).map(v => v.url).join('\n')
    if (!urls) return
    copyToClipboard(urls).then(() => {
      toast.success(`已複製 ${selectedVideos.size} 個連結`)
    }).catch(() => toast.error('複製失敗'))
  }

  async function handleMarkAllSeen() {
    try {
      await youtubeAPI.markAllSeen(selectedChannel)
      setVideos(prev => prev.map(v => ({ ...v, is_new: false })))
      setChannels(prev => prev.map(c =>
        (!selectedChannel || c.id === selectedChannel) ? { ...c, new_video_count: 0 } : c
      ))
      toast.success('全部標記為已看')
    } catch { toast.error('操作失敗') }
  }

  const totalNew = channels.reduce((s, c) => s + c.new_video_count, 0)
  const displayedNew = selectedChannel
    ? (channels.find(c => c.id === selectedChannel)?.new_video_count || 0)
    : totalNew

  return (
    <div className="flex gap-6 h-[calc(100vh-120px)]">
      {/* ── Left sidebar: channel list ── */}
      <div className="w-64 flex-shrink-0 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-dark-300 uppercase tracking-wide">監控頻道</h2>
          <button
            className="btn-primary text-xs px-3 py-1.5"
            onClick={() => setShowAddModal(true)}
          >
            + 新增
          </button>
        </div>

        {/* All channels option */}
        <div
          className={`card cursor-pointer transition-all ${selectedChannel === null ? 'border-primary-500/60 bg-primary-600/10' : 'card-hover'}`}
          onClick={() => setSelectedChannel(null)}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-white">全部頻道</span>
            {totalNew > 0 && (
              <span className="text-xs bg-red-500 text-white rounded-full px-2 py-0.5 font-bold">
                {totalNew}
              </span>
            )}
          </div>
          <p className="text-xs text-dark-400 mt-0.5">{channels.length} 個頻道</p>
        </div>

        {/* Channel cards */}
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {channels.length === 0 ? (
            <div className="card text-center py-8">
              <svg className="w-8 h-8 text-dark-500 mx-auto mb-2" viewBox="0 0 24 24" fill="currentColor">
                <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
              </svg>
              <p className="text-xs text-dark-500">尚未新增頻道</p>
            </div>
          ) : (
            channels.map(c => (
              <ChannelCard
                key={c.id}
                channel={c}
                isSelected={selectedChannel === c.id}
                onClick={() => setSelectedChannel(c.id)}
                onDelete={handleDelete}
                onToggle={handleToggle}
              />
            ))
          )}
        </div>

        {/* Check all button */}
        <button
          className="btn-secondary w-full flex items-center justify-center gap-2 text-sm"
          onClick={handleCheckAll}
          disabled={loadingCheck || channels.length === 0}
        >
          {loadingCheck ? (
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          )}
          立即偵測全部
        </button>
      </div>

      {/* ── Right: video feed ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-white">
              {selectedChannel
                ? channels.find(c => c.id === selectedChannel)?.name || '影片'
                : '全部影片'}
            </h2>
            {displayedNew > 0 && (
              <span className="text-xs bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-0.5 rounded-full">
                {displayedNew} 支新影片
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <label className="flex items-center gap-1.5 text-sm text-dark-300 cursor-pointer select-none">
              <input
                type="checkbox"
                className="rounded"
                checked={showNewOnly}
                onChange={e => setShowNewOnly(e.target.checked)}
              />
              只顯示新影片
            </label>
            {videos.length > 0 && (
              <button
                className="btn-secondary text-xs px-3 py-1.5"
                onClick={handleSelectAll}
              >
                {selectedVideos.size === videos.length ? '取消全選' : '全選'}
              </button>
            )}
            {selectedVideos.size > 0 && (
              <button
                className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1"
                onClick={handleCopySelected}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                複製連結（{selectedVideos.size}）
              </button>
            )}
            {displayedNew > 0 && (
              <button className="btn-secondary text-xs px-3 py-1.5" onClick={handleMarkAllSeen}>
                全部標記已看
              </button>
            )}
            {selectedChannel && (
              <button
                className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1"
                onClick={() => handleCheckOne(channels.find(c => c.id === selectedChannel))}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                偵測此頻道
              </button>
            )}
          </div>
        </div>

        {/* Video grid */}
        {loadingVideos ? (
          <div className="flex-1 flex items-center justify-center">
            <svg className="w-8 h-8 text-dark-500 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </div>
        ) : videos.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center">
            <svg className="w-16 h-16 text-dark-600 mb-3" viewBox="0 0 24 24" fill="currentColor">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
            </svg>
            <p className="text-dark-400">
              {channels.length === 0
                ? '新增頻道後，系統會自動偵測新影片'
                : showNewOnly ? '目前沒有未看的新影片' : '尚無影片記錄，點擊「立即偵測」載入'}
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {videos.map(v => (
                <VideoCard
                  key={v.id}
                  video={v}
                  onMarkSeen={handleMarkSeen}
                  isSelected={selectedVideos.has(v.id)}
                  onToggleSelect={handleToggleSelect}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {showAddModal && (
        <AddChannelModal
          onClose={() => setShowAddModal(false)}
          onAdded={(ch) => {
            setChannels(prev => [...prev, ch])
            loadVideos()
          }}
        />
      )}
    </div>
  )
}
