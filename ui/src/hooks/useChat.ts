import { useCallback, useEffect, useRef, useState } from 'react'
import type { ConnectionStatus, Message, WSServerMessage } from '../types'
import { DEFAULT_CHARACTER } from '../constants/characters'

interface UseChatReturn {
  messages: Message[]
  isStreaming: boolean
  activeCharacter: string
  setCharacter: (char: string) => void
  sendMessage: (text: string) => void
  clearChat: () => void
}

export function useChat(
  send: (payload: object) => void,
  lastMessage: MessageEvent | null,
  status: ConnectionStatus,
): UseChatReturn {
  const [messages,         setMessages]         = useState<Message[]>([])
  const [isStreaming,      setIsStreaming]       = useState(false)
  const [activeCharacter,  setActiveCharacter]  = useState(DEFAULT_CHARACTER)

  // Track the id of the bot message currently being streamed
  const streamingId    = useRef<string | null>(null)
  // Avoid sending set_character multiple times per connection
  const hasInitialized = useRef(false)

  // ── Token batching ────────────────────────────────────────────────────────
  // Incoming tokens are accumulated in a ref. A single requestAnimationFrame
  // fires per display frame (~16 ms) and flushes the whole buffer to state in
  // one React update — eliminating hundreds of re-renders per response.
  const tokenBuffer = useRef('')
  const rafId       = useRef<number | null>(null)

  const flushBuffer = useCallback((targetId: string) => {
    const chunk = tokenBuffer.current
    tokenBuffer.current = ''
    rafId.current = null
    if (!chunk) return
    setMessages((prev) =>
      prev.map((m) => (m.id === targetId ? { ...m, content: m.content + chunk } : m)),
    )
  }, [])

  const scheduleFlush = useCallback((targetId: string) => {
    if (rafId.current !== null) return          // flush already scheduled this frame
    rafId.current = requestAnimationFrame(() => flushBuffer(targetId))
  }, [flushBuffer])

  // Cancel any pending flush and immediately drain whatever is buffered
  const flushNow = useCallback((targetId: string) => {
    if (rafId.current !== null) {
      cancelAnimationFrame(rafId.current)
      rafId.current = null
    }
    flushBuffer(targetId)
  }, [flushBuffer])

  // ── Handle incoming server messages ──────────────────────────────────────
  useEffect(() => {
    if (!lastMessage) return

    const data = JSON.parse(lastMessage.data as string) as WSServerMessage

    switch (data.type) {
      case 'token': {
        const id = streamingId.current
        if (!id) break
        tokenBuffer.current += data.content   // accumulate in ref (no re-render)
        scheduleFlush(id)                     // one RAF per frame, not one per token
        break
      }

      case 'done': {
        const id = streamingId.current
        if (id) flushNow(id)                  // drain any remaining buffered tokens
        setMessages((prev) =>
          prev.map((m) =>
            m.id === id ? { ...m, streaming: false } : m,
          ),
        )
        streamingId.current = null
        setIsStreaming(false)
        break
      }

      case 'error':
        tokenBuffer.current = ''
        if (rafId.current !== null) { cancelAnimationFrame(rafId.current); rafId.current = null }
        setIsStreaming(false)
        streamingId.current = null
        break

      case 'character_set':
        break
    }
  }, [lastMessage, scheduleFlush, flushNow])

  // ── Send initial character selection when (re)connected ─────────────────
  useEffect(() => {
    if (status === 'connected' && !hasInitialized.current) {
      send({ type: 'set_character', character: activeCharacter })
      hasInitialized.current = true
    }
    if (status === 'disconnected') {
      hasInitialized.current = false
    }
  }, [status, activeCharacter, send])

  // ── Public actions ────────────────────────────────────────────────────────
  const setCharacter = useCallback(
    (char: string) => {
      if (rafId.current !== null) { cancelAnimationFrame(rafId.current); rafId.current = null }
      tokenBuffer.current = ''
      setActiveCharacter(char)
      setMessages([])
      setIsStreaming(false)
      streamingId.current = null
      send({ type: 'set_character', character: char })
    },
    [send],
  )

  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (isStreaming || !trimmed) return

      const userMsg: Message = {
        id:        crypto.randomUUID(),
        role:      'user',
        content:   trimmed,
        streaming: false,
      }

      const botId = crypto.randomUUID()
      const botMsg: Message = {
        id:        botId,
        role:      'bot',
        content:   '',
        streaming: true,
        character: activeCharacter,
      }

      streamingId.current = botId
      setIsStreaming(true)
      setMessages((prev) => [...prev, userMsg, botMsg])
      send({ type: 'chat', message: trimmed })
    },
    [isStreaming, activeCharacter, send],
  )

  const clearChat = useCallback(() => {
    if (rafId.current !== null) { cancelAnimationFrame(rafId.current); rafId.current = null }
    tokenBuffer.current = ''
    setMessages([])
    setIsStreaming(false)
    streamingId.current = null
    send({ type: 'set_character', character: activeCharacter })
  }, [activeCharacter, send])

  return { messages, isStreaming, activeCharacter, setCharacter, sendMessage, clearChat }
}
