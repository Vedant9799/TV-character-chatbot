import type { ConnectionStatus } from '../types'
import { CHARACTERS, SHOWS } from '../constants/characters'

interface HeaderProps {
  activeCharacter: string
  onCharacterChange: (char: string) => void
  status: ConnectionStatus
}

const STATUS: Record<ConnectionStatus, { dot: string; label: string }> = {
  connected:    { dot: 'bg-emerald-500',                    label: 'Connected'    },
  connecting:   { dot: 'bg-amber-400 animate-pulse',        label: 'Connecting…'  },
  disconnected: { dot: 'bg-red-500',                        label: 'Disconnected' },
}

export default function Header({ activeCharacter, onCharacterChange, status }: HeaderProps) {
  const { dot, label } = STATUS[status]

  return (
    <header className="flex items-center justify-between gap-4 px-5 py-3.5 bg-app-surface border-b border-app-border shrink-0">

      {/* Brand */}
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="text-2xl select-none">📺</span>
        <h1 className="text-[15px] font-bold tracking-tight text-slate-100 whitespace-nowrap">
          TV Character{' '}
          <span className="text-violet-400">Chatbot</span>
        </h1>
      </div>

      {/* Character selector */}
      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-500 whitespace-nowrap hidden sm:block">
          Character
        </label>
        <select
          value={activeCharacter}
          onChange={(e) => onCharacterChange(e.target.value)}
          className="
            bg-app-surface2 text-slate-100 border border-app-border
            rounded-lg px-2.5 py-1.5 text-sm cursor-pointer
            focus:outline-none focus:border-violet-500
            transition-colors
          "
        >
          {SHOWS.map((show) => (
            <optgroup key={show} label={show}>
              {Object.entries(CHARACTERS)
                .filter(([, meta]) => meta.show === show)
                .map(([name, { emoji, supported }]) => (
                  <option key={name} value={name} disabled={!supported}>
                    {emoji} {name}{!supported ? ' (coming soon)' : ''}
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
      </div>

      {/* Connection status */}
      <div className="flex items-center gap-1.5 shrink-0">
        <span className={`w-2 h-2 rounded-full ${dot}`} />
        <span className="text-xs text-slate-500 hidden sm:block">{label}</span>
      </div>

    </header>
  )
}
