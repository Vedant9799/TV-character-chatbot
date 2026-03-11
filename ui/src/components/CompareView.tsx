import { useCallback, useEffect, useState } from 'react'
import type { ConnectionStatus } from '../types'
import { useWebSocket } from '../hooks/useWebSocket'
import { useChat }      from '../hooks/useChat'
import { CHARACTERS }   from '../constants/characters'
import ChatArea   from './ChatArea'
import InputArea  from './InputArea'

interface CompareViewProps {
  initialCharacter: string
  onBack: () => void
}

// ── Connection status helpers ──────────────────────────────────────────────

const STATUS_DOT: Record<ConnectionStatus, string> = {
  connected:    'bg-emerald-500',
  connecting:   'bg-amber-400 animate-pulse',
  disconnected: 'bg-red-500',
}
const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected:    'Connected',
  connecting:   'Connecting…',
  disconnected: 'Disconnected',
}

// ── Per-panel header ───────────────────────────────────────────────────────

interface PanelHeaderProps {
  label:     string          // "A" | "B"
  modelName: string          // fetched from /health
  character: string
  onCharacterChange: (c: string) => void
  status: ConnectionStatus
}

function PanelHeader({
  label, modelName, character, onCharacterChange, status,
}: PanelHeaderProps) {
  const meta   = CHARACTERS[character]
  const color  = meta?.color ?? '#7c3aed'
  const imgSrc = meta?.image ?? `/portraits/${character.toLowerCase()}.jpg`
  const [imgOk, setImgOk] = useState(true)

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-app-surface border-b border-app-border shrink-0">

      {/* Label badge: "A" or "B" */}
      <span className="font-pixel text-[8px] px-1.5 py-0.5 rounded bg-app-surface2 border border-app-border text-slate-500 shrink-0">
        {label}
      </span>

      {/* Character avatar */}
      <div
        className="w-7 h-7 rounded-lg overflow-hidden shrink-0 flex items-center justify-center bg-app-surface2 text-base select-none"
        style={{ boxShadow: `0 0 0 1.5px ${color}55` }}
      >
        {imgOk ? (
          <img
            src={imgSrc}
            alt={character}
            onError={() => setImgOk(false)}
            className="w-full h-full object-cover object-top"
          />
        ) : (
          <span>{meta?.emoji ?? '🎬'}</span>
        )}
      </div>

      {/* Character name + model name */}
      <div className="flex-1 min-w-0">
        <p className="font-pixel text-[8px] leading-tight truncate" style={{ color }}>
          {character}
        </p>
        <p className="text-[9px] text-slate-600 truncate" title={modelName}>
          {modelName}
        </p>
      </div>

      {/* Character switcher */}
      <select
        value={character}
        onChange={(e) => onCharacterChange(e.target.value)}
        className="
          bg-app-surface2 text-slate-400 border border-app-border
          rounded-lg px-2 py-1 text-xs cursor-pointer shrink-0
          focus:outline-none focus:border-violet-600 transition-colors
        "
      >
        {Object.entries(CHARACTERS).map(([name, { emoji }]) => (
          <option key={name} value={name}>{emoji} {name}</option>
        ))}
      </select>

      {/* Connection status dot */}
      <div
        className="flex items-center gap-1 shrink-0"
        title={STATUS_LABEL[status]}
      >
        <span className={`w-2 h-2 rounded-full ${STATUS_DOT[status]}`} />
        <span className="text-[10px] text-slate-600 hidden lg:block">
          {STATUS_LABEL[status]}
        </span>
      </div>

    </div>
  )
}

// ── Main compare view ──────────────────────────────────────────────────────

export default function CompareView({ initialCharacter, onBack }: CompareViewProps) {

  // Resolve backend hosts from env vars or fall back to localhost defaults
  const isHttps   = location.protocol === 'https:'
  const wsProto   = isHttps ? 'wss' : 'ws'
  const httpProto = isHttps ? 'https' : 'http'
  const leftHost  = (import.meta.env.VITE_COMPARE_A as string | undefined) ?? 'localhost:8001'
  const rightHost = (import.meta.env.VITE_COMPARE_B as string | undefined) ?? 'localhost:8002'
  const leftWs    = `${wsProto}://${leftHost}/ws`
  const rightWs   = `${wsProto}://${rightHost}/ws`

  // Model name labels — fetched from each server's /health endpoint
  const [leftModel,  setLeftModel]  = useState('…')
  const [rightModel, setRightModel] = useState('…')

  useEffect(() => {
    const fetchModel = async (host: string, setter: (s: string) => void) => {
      try {
        const res  = await fetch(`${httpProto}://${host}/health`)
        const data = await res.json() as { status: string; model?: string }
        setter(data.model ?? host)
      } catch {
        setter(host)   // fall back to showing the host:port
      }
    }
    fetchModel(leftHost,  setLeftModel)
    fetchModel(rightHost, setRightModel)
  }, [leftHost, rightHost, httpProto])

  // ── Two independent WebSocket + chat pairs ─────────────────────────────

  const wsLeft  = useWebSocket(leftWs)
  const wsRight = useWebSocket(rightWs)

  const {
    messages: msgsLeft,  isStreaming: streamLeft,
    activeCharacter: charLeft,   setCharacter: setCharLeft,
    sendMessage: sendLeft,       stopStreaming: stopLeft,  clearChat: clearLeft,
  } = useChat(wsLeft.send,  wsLeft.onMessageRef,  wsLeft.status,  initialCharacter)

  const {
    messages: msgsRight, isStreaming: streamRight,
    activeCharacter: charRight,  setCharacter: setCharRight,
    sendMessage: sendRight,      stopStreaming: stopRight, clearChat: clearRight,
  } = useChat(wsRight.send, wsRight.onMessageRef, wsRight.status, initialCharacter)

  const isStreaming  = streamLeft  || streamRight
  const anyConnected = wsLeft.status === 'connected' || wsRight.status === 'connected'

  // Shared actions — fan out to both panels
  const sendBoth  = useCallback((t: string) => { sendLeft(t);  sendRight(t)  }, [sendLeft,  sendRight])
  const stopBoth  = useCallback(()           => { stopLeft();   stopRight()   }, [stopLeft,  stopRight])
  const clearBoth = useCallback(()           => { clearLeft();  clearRight()  }, [clearLeft, clearRight])

  return (
    <div className="flex flex-col h-dvh bg-app-bg">

      {/* ── Top bar ───────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-app-surface border-b border-app-border shrink-0 animate-slideDown">
        <button
          onClick={onBack}
          title="Back to character select"
          className="
            w-8 h-8 flex items-center justify-center rounded-lg text-lg
            text-slate-600 hover:text-slate-200 hover:bg-app-surface2
            transition-colors shrink-0
          "
        >
          ←
        </button>

        <div className="flex items-center gap-2 flex-1">
          <span className="text-base">⚔</span>
          <span className="font-pixel text-[9px] text-slate-300 tracking-wide">
            COMPARE MODELS
          </span>
        </div>

        <span className="text-[10px] text-slate-700 hidden sm:block select-none">
          Each message is sent to both backends simultaneously
        </span>
      </div>

      {/* ── Two-panel area ────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden divide-x divide-app-border">

        {/* ── Left panel (Model A) ─────────────────────────────────────────── */}
        <div className="flex flex-col flex-1 min-w-0">
          <PanelHeader
            label="A"
            modelName={leftModel}
            character={charLeft}
            onCharacterChange={setCharLeft}
            status={wsLeft.status}
          />
          <ChatArea
            messages={msgsLeft}
            activeCharacter={charLeft}
            onSend={wsLeft.status === 'connected' && !streamLeft ? sendLeft : undefined}
          />
        </div>

        {/* ── Right panel (Model B) ────────────────────────────────────────── */}
        <div className="flex flex-col flex-1 min-w-0">
          <PanelHeader
            label="B"
            modelName={rightModel}
            character={charRight}
            onCharacterChange={setCharRight}
            status={wsRight.status}
          />
          <ChatArea
            messages={msgsRight}
            activeCharacter={charRight}
            onSend={wsRight.status === 'connected' && !streamRight ? sendRight : undefined}
          />
        </div>

      </div>

      {/* ── Shared input bar ──────────────────────────────────────────────── */}
      <InputArea
        onSend={sendBoth}
        onStop={stopBoth}
        onClear={clearBoth}
        isStreaming={isStreaming}
        disabled={!anyConnected}
      />

    </div>
  )
}
