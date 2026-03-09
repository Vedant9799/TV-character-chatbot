import type { ConnectionStatus } from '../types'
import { CHARACTERS } from '../constants/characters'

interface HeaderProps {
  activeCharacter: string
  status: ConnectionStatus
}

export default function Header({ activeCharacter, status }: HeaderProps) {
  const meta = CHARACTERS[activeCharacter]

  return (
    <header className="flex items-center gap-3 px-6 py-3 bg-white/70 backdrop-blur-sm border-b border-gray-200 shrink-0">
      <div className={`w-10 h-10 rounded-full ${meta?.color ?? 'bg-gray-400'} flex items-center justify-center text-white text-sm font-bold shrink-0`}>
        {(meta?.fullName ?? activeCharacter).charAt(0)}
      </div>
      <div className="min-w-0">
        <h2 className="text-sm font-bold text-gray-900 truncate">{meta?.fullName ?? activeCharacter}</h2>
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${
            status === 'connected' ? 'bg-emerald-500' :
            status === 'connecting' ? 'bg-amber-400 animate-pulse' : 'bg-red-500'
          }`} />
          <span className="text-[11px] text-gray-400">{meta?.role}</span>
        </div>
      </div>
    </header>
  )
}
