import { useCallback, useEffect, useRef, useState } from 'react'
import type { ConnectionStatus } from '../types'

interface UseWebSocketReturn {
  send: (payload: object) => void
  status: ConnectionStatus
  lastMessage: MessageEvent | null
}

export function useWebSocket(url: string): UseWebSocketReturn {
  const [status, setStatus]           = useState<ConnectionStatus>('connecting')
  const [lastMessage, setLastMessage] = useState<MessageEvent | null>(null)

  const wsRef          = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    // Avoid double-connecting
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws
    setStatus('connecting')

    ws.onopen  = () => setStatus('connected')
    ws.onerror = () => ws.close()                          // let onclose handle retry
    ws.onclose = () => {
      setStatus('disconnected')
      reconnectTimer.current = setTimeout(connect, 3_000)  // auto-reconnect
    }
    ws.onmessage = (evt) => setLastMessage(evt)
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

  return { send, status, lastMessage }
}
