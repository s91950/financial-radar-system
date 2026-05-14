import { useCallback, useEffect, useRef, useState } from 'react'

// 動態組 WebSocket URL：協定跟著當前頁面（https → wss、http → ws），
// host 也用瀏覽器當前 host，避免寫死 localhost 讓部署到 VM 的使用者
// 一律連到自己的 127.0.0.1 而顯示「離線中」。
// 生產：nginx /ws → 127.0.0.1:8000；dev：vite.config 也有 /ws proxy。
function _defaultWsUrl() {
  if (typeof window === 'undefined') return 'ws://localhost:8000/ws'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

export default function useWebSocket(url = _defaultWsUrl()) {
  const [lastMessage, setLastMessage] = useState(null)
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const listenersRef = useRef(new Map())

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
        setIsConnected(true)
        console.log('WebSocket connected')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          setLastMessage(data)

          // Notify type-specific listeners
          const type = data.type
          if (type && listenersRef.current.has(type)) {
            listenersRef.current.get(type).forEach(cb => cb(data))
          }

          // Notify wildcard listeners
          if (listenersRef.current.has('*')) {
            listenersRef.current.get('*').forEach(cb => cb(data))
          }
        } catch (e) {
          console.error('WebSocket message parse error:', e)
        }
      }

      ws.onclose = () => {
        setIsConnected(false)
        console.log('WebSocket disconnected, reconnecting in 5s...')
        reconnectTimer.current = setTimeout(connect, 5000)
      }

      ws.onerror = (err) => {
        console.error('WebSocket error:', err)
        ws.close()
      }

      wsRef.current = ws
    } catch (e) {
      console.error('WebSocket connection error:', e)
      reconnectTimer.current = setTimeout(connect, 5000)
    }
  }, [url])

  const subscribe = useCallback((type, callback) => {
    if (!listenersRef.current.has(type)) {
      listenersRef.current.set(type, new Set())
    }
    listenersRef.current.get(type).add(callback)

    return () => {
      const listeners = listenersRef.current.get(type)
      if (listeners) {
        listeners.delete(callback)
        if (listeners.size === 0) {
          listenersRef.current.delete(type)
        }
      }
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [connect])

  return { lastMessage, isConnected, subscribe }
}
