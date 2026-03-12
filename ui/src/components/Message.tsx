import type { Message as MessageType } from '../types'
import { CHARACTERS } from '../constants/characters'

interface MessageProps {
  message: MessageType
}

// WhatsApp-style three-dot typing indicator
function TypingDots({ color }: { color: string }) {
  return (
    <span className="flex items-center gap-[5px] px-0.5 py-0.5">
      {[0, 0.2, 0.4].map((delay, i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full animate-typingDot"
          style={{ backgroundColor: color, animationDelay: `${delay}s` }}
        />
      ))}
    </span>
  )
}

export default function Message({ message }: MessageProps) {
  const { role, content, streaming, character } = message

  // ── System / info notices ────────────────────────────────────────────────
  if (role === 'system') {
    return (
      <div className="text-center text-[10px] text-slate-700 py-1.5 select-none animate-fadeIn font-pixel">
        {content}
      </div>
    )
  }

  const isUser = role === 'user'
  const meta   = CHARACTERS[character ?? '']
  const emoji  = isUser ? '🧑' : (meta?.emoji ?? '🎬')
  const color  = meta?.color ?? '#7c3aed'
  const name   = isUser ? 'You' : character

  return (
    <div
      className={[
        'flex gap-2.5 animate-slideUp',
        isUser
          ? 'self-end flex-row-reverse max-w-[78%]'
          : 'self-start max-w-[82%]',
      ].join(' ')}
    >
      {/* ── Avatar ────────────────────────────────────────────────────────── */}
      <div
        className={[
          'w-8 h-8 rounded-xl flex items-center justify-center text-base',
          'bg-app-surface2 shrink-0 self-end select-none',
          isUser ? 'border border-app-border' : 'pixel-ring',
        ].join(' ')}
        style={
          !isUser
            ? ({ '--ring-color': color } as React.CSSProperties)
            : {}
        }
      >
        {emoji}
      </div>

      {/* ── Bubble ────────────────────────────────────────────────────────── */}
      <div className={`flex flex-col gap-1 min-w-0 ${isUser ? 'items-end' : 'items-start'}`}>
        <span className="text-[10px] text-slate-600 px-1">{name}</span>

        <div
          className={[
            'px-3.5 py-2.5 text-sm leading-relaxed break-words rounded-2xl',
            isUser
              ? 'bg-violet-700/80 text-white rounded-br-[4px] border border-violet-600/40'
              : 'bg-app-surface2 text-slate-200 rounded-bl-[4px] border border-app-border',
          ].join(' ')}
          style={
            !isUser && !streaming
              ? { borderColor: `${color}22` }
              : {}
          }
        >
          {isUser ? (
            content || (streaming ? '' : <span className="italic text-slate-400">…</span>)
          ) : content ? (
            <>
              {content.split('\n').map((line, i) => (
                <p key={i} className="mb-1.5 last:mb-0">{line}</p>
              ))}
              {/* Blinking cursor while tokens are still arriving */}
              {streaming && (
                <span
                  className="inline-block w-[2px] h-[1em] ml-0.5 align-middle animate-blink rounded-full"
                  style={{ backgroundColor: color }}
                />
              )}
            </>
          ) : streaming ? (
            // No tokens yet — show the WhatsApp-style typing indicator
            <TypingDots color={color} />
          ) : (
            <span className="italic text-slate-500">…</span>
          )}
        </div>
      </div>
    </div>
  )
}
