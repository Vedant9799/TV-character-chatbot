import { useState } from 'react'
import type { ConnectionStatus } from '../types'
import { CHARACTERS } from '../constants/characters'

interface HeaderProps {
  activeCharacter: string
  onCharacterChange: (char: string) => void
  onBack: () => void
  status: ConnectionStatus
}

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

export default function Header({ activeCharacter, onCharacterChange, onBack, status }: HeaderProps) {
  const meta  = CHARACTERS[activeCharacter]
  const color = meta?.color ?? '#7c3aed'
  const [imgOk, setImgOk] = useState(true)
  const imgSrc = meta?.image ?? `/characters/${activeCharacter.toLowerCase()}.webp`

  return (
    <header className="flex items-center gap-3 px-4 py-2.5 bg-app-surface border-b border-app-border shrink-0 animate-slideDown">

      {/* ── Back button ─────────────────────────────────────────────────── */}
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

      {/* ── Character avatar + name ──────────────────────────────────────── */}
      <div className="flex items-center gap-2.5 flex-1 min-w-0">
        {/* Portrait thumbnail — image or emoji fallback */}
        <div
          className="w-9 h-9 rounded-xl overflow-hidden shrink-0 flex items-center justify-center bg-app-surface2 text-xl select-none"
          style={{
            boxShadow: `0 0 0 1.5px ${color}55`,
          }}
        >
          {imgOk ? (
            <img
              src={imgSrc}
              alt={activeCharacter}
              onError={() => setImgOk(false)}
              className="w-full h-full object-cover object-top"
            />
          ) : (
            <span>{meta?.emoji ?? '🎬'}</span>
          )}
        </div>

        <div className="min-w-0">
          <p className="font-pixel text-[9px] leading-tight truncate" style={{ color }}>
            {activeCharacter}
          </p>
          <p className="text-[10px] text-slate-600 truncate">{meta?.show}</p>
        </div>
      </div>

      {/* ── Character switcher (flat list — all 4 are supported) ─────────── */}
      <select
        value={activeCharacter}
        onChange={(e) => onCharacterChange(e.target.value)}
        title="Switch character"
        className="
          bg-app-surface2 text-slate-400 border border-app-border
          rounded-lg px-2 py-1 text-xs cursor-pointer shrink-0
          focus:outline-none focus:border-violet-600
          transition-colors
        "
      >
        {Object.entries(CHARACTERS).map(([name, { emoji }]) => (
          <option key={name} value={name}>{emoji} {name}</option>
        ))}
      </select>

      {/* ── Connection status ────────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5 shrink-0" title={STATUS_LABEL[status]}>
        <span className={`w-2 h-2 rounded-full ${STATUS_DOT[status]}`} />
        <span className="text-[10px] text-slate-600 hidden sm:block">
          {STATUS_LABEL[status]}
        </span>
      </div>

    </header>
  )
}
