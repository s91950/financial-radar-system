import { useCallback, useEffect, useRef, useState } from 'react'

export default function useWebSocket(url = 'ws://localhost:8000/ws') {
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
