import { CHARACTERS, SHOWS } from '../constants/characters'
import type { ConnectionStatus } from '../types'

interface SidebarProps {
  activeCharacter: string
  onCharacterChange: (char: string) => void
  status: ConnectionStatus
  activeShow: string
  onShowChange: (show: string) => void
}

export default function Sidebar({
  activeCharacter,
  onCharacterChange,
  status,
  activeShow,
  onShowChange,
}: SidebarProps) {
  const filteredCharacters = Object.entries(CHARACTERS).filter(
    ([, meta]) => meta.show === activeShow,
  )

  return (
    <aside className="w-[264px] shrink-0 bg-white/80 backdrop-blur-sm border-r border-gray-200 flex flex-col h-full">
      {/* Brand */}
      <div className="px-4 pt-5 pb-4">
        <div className="flex items-center gap-2">
          <span className="w-7 h-7 rounded-lg bg-rose-500 flex items-center justify-center text-white text-sm">💬</span>
          <h1 className="text-[15px] font-bold text-rose-500 tracking-tight">SceneChat</h1>
        </div>
      </div>

      {/* Show toggle */}
      <div className="px-4 pb-3">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Select Show</p>
        <div className="flex gap-1">
          {SHOWS.map((show) => {
            const label = show === 'The Big Bang Theory' ? 'TBBT' : 'The Office'
            const isActive = activeShow === show
            return (
              <button
                key={show}
                onClick={() => onShowChange(show)}
                className={`
                  flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors
                  ${isActive
                    ? 'bg-rose-500 text-white shadow-sm'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                  }
                `}
              >
                {label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Character list */}
      <div className="px-4 pb-2">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Select Character</p>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-3 pb-3 space-y-1">
        {filteredCharacters.map(([name, meta]) => {
          const isActive = activeCharacter === name
          return (
            <button
              key={name}
              onClick={() => onCharacterChange(name)}
              className={`
                w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl text-left transition-all
                ${isActive
                  ? 'bg-white shadow-md ring-1 ring-gray-200'
                  : 'hover:bg-white/60'
                }
              `}
            >
              <div className={`w-8 h-8 rounded-full ${meta.color} flex items-center justify-center text-white text-xs font-bold shrink-0`}>
                {meta.fullName.charAt(0)}
              </div>
              <div className="min-w-0">
                <p className={`text-xs font-semibold truncate ${isActive ? 'text-gray-900' : 'text-gray-700'}`}>
                  {meta.fullName}
                </p>
                <p className="text-[10px] text-gray-400 truncate">{meta.role}</p>
              </div>
            </button>
          )
        })}
      </div>

      {/* Guest user footer */}
      <div className="px-4 py-3 border-t border-gray-200 mt-auto">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-400 to-pink-400 flex items-center justify-center text-white text-xs font-bold">
            G
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-gray-700">Guest User</p>
            <div className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${
                status === 'connected' ? 'bg-emerald-500' :
                status === 'connecting' ? 'bg-amber-400 animate-pulse' : 'bg-red-500'
              }`} />
              <p className="text-[10px] text-gray-400">
                {status === 'connected' ? 'Ready to chat' :
                 status === 'connecting' ? 'Connecting…' : 'Disconnected'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </aside>
  )
}
