import ReactMarkdown from 'react-markdown'
import type { Message as MessageType } from '../types'
import { CHARACTERS } from '../constants/characters'

interface MessageProps {
  message: MessageType
}

export default function Message({ message }: MessageProps) {
  const { role, content, streaming, character } = message

  // System / info messages (character switch notices, etc.)
  if (role === 'system') {
    return (
      <div className="text-center text-xs text-slate-600 py-1 select-none animate-fadeIn">
        {content}
      </div>
    )
  }

  const isUser  = role === 'user'
  const emoji   = isUser ? '🧑' : (CHARACTERS[character ?? '']?.emoji ?? '🎬')
  const name    = isUser ? 'You' : character

  return (
    <div
      className={`
        flex gap-2.5 animate-slideUp
        ${isUser ? 'self-end flex-row-reverse max-w-[75%]' : 'self-start max-w-[78%]'}
      `}
    >
      {/* Avatar */}
      <div className="
        w-8 h-8 rounded-full flex items-center justify-center text-base
        bg-app-surface2 border border-app-border shrink-0 self-end select-none
      ">
        {emoji}
      </div>

      {/* Bubble */}
      <div className={`flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`}>
        <span className="text-[11px] text-slate-500 px-1">{name}</span>

        <div
          className={`
            px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed break-words
            ${isUser
              ? 'bg-violet-600 text-white rounded-br-sm'
              : 'bg-app-surface2 text-slate-100 rounded-bl-sm border border-app-border'
            }
          `}
        >
          {isUser ? (
            // User messages: plain text (no markdown needed)
            content || (streaming ? '' : <span className="text-slate-500 italic">…</span>)
          ) : content ? (
            // Bot messages: render markdown with character-appropriate styling
            <ReactMarkdown
              components={{
                p:      ({ children }) => <p className="mb-1.5 last:mb-0">{children}</p>,
                strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
                em:     ({ children }) => <em className="italic text-slate-300">{children}</em>,
                code:   ({ children }) => (
                  <code className="font-mono text-xs bg-black/30 px-1 py-0.5 rounded text-violet-300">
                    {children}
                  </code>
                ),
                ul: ({ children }) => <ul className="list-disc pl-4 my-1 space-y-0.5">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-4 my-1 space-y-0.5">{children}</ol>,
                li: ({ children }) => <li className="leading-relaxed">{children}</li>,
              }}
            >
              {content}
            </ReactMarkdown>
          ) : (
            streaming ? null : <span className="text-slate-500 italic">…</span>
          )}

          {/* Blinking cursor while streaming */}
          {streaming && (
            <span className="inline-block w-[2px] h-[1.1em] bg-violet-400 ml-0.5 align-middle animate-blink" />
          )}
        </div>
      </div>
    </div>
  )
}
