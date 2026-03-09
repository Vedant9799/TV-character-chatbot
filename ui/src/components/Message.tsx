import type { Message as MessageType } from '../types'
import { CHARACTERS } from '../constants/characters'

interface MessageProps {
  message: MessageType
}

export default function Message({ message }: MessageProps) {
  const { role, content, streaming, character } = message

  if (role === 'system') {
    return (
      <div className="text-center text-xs text-gray-400 py-1 select-none animate-fadeIn">
        {content}
      </div>
    )
  }

  const isUser = role === 'user'
  const meta   = CHARACTERS[character ?? '']
  const initial = isUser ? 'Y' : (meta?.fullName ?? character ?? 'U').charAt(0)
  const color   = isUser ? 'bg-rose-400' : (meta?.color ?? 'bg-gray-400')

  return (
    <div
      className={`
        flex gap-2.5 animate-slideUp
        ${isUser ? 'self-end flex-row-reverse max-w-[75%]' : 'self-start max-w-[78%]'}
      `}
    >
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full ${color} flex items-center justify-center text-white text-xs font-bold shrink-0 self-end select-none`}>
        {initial}
      </div>

      {/* Bubble */}
      <div className={`flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`
            px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed break-words
            ${isUser
              ? 'bg-rose-500 text-white rounded-br-sm'
              : 'bg-white/90 text-gray-800 rounded-bl-sm border border-gray-200 shadow-sm'
            }
          `}
        >
          {content || (streaming ? '' : <span className="text-gray-400 italic">…</span>)}

          {streaming && (
            <span className="inline-block w-[2px] h-[1.1em] bg-rose-400 ml-0.5 align-middle animate-blink" />
          )}
        </div>
      </div>
    </div>
  )
}
