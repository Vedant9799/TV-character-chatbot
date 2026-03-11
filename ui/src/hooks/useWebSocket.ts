import { useCallback, useEffect, useRef, useState } from 'react'
import type { ConnectionStatus } from '../types'

interface UseWebSocketReturn {
  send: (payload: object) => void
  status: ConnectionStatus
  /** Ref whose `.current` is called directly from ws.onmessage —
   *  bypasses React state so no messages are lost to batching. */
  onMessageRef: React.MutableRefObject<((evt: MessageEvent) => void) | null>
}

export function useWebSocket(url: string): UseWebSocketReturn {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')

  const wsRef          = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()
  const onMessageRef   = useRef<((evt: MessageEvent) => void) | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws
    setStatus('connecting')

    ws.onopen  = () => setStatus('connected')
    ws.onerror = () => ws.close()
    ws.onclose = () => {
      setStatus('disconnected')
      reconnectTimer.current = setTimeout(connect, 3_000)
    }
    // Call the ref callback directly — no React state in the hot path.
    ws.onmessage = (evt) => onMessageRef.current?.(evt)
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((payload: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [])

  return { send, status, onMessageRef }
}
