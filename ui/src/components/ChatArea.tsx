import { useEffect, useRef, useState } from 'react'
import type { Message as MessageType } from '../types'
import { CHARACTERS } from '../constants/characters'
import Message from './Message'

interface ChatAreaProps {
  messages: MessageType[]
  activeCharacter: string
  onSend?: (text: string) => void
}

const STARTER_PROMPTS: Record<string, string[]> = {
  Sheldon: ['Explain string theory simply.', "What's wrong with the way most people think?", 'Rate my IQ.'],
  Michael: ['Give me a motivational speech.', "What's the best prank you've pulled?", 'Why are you the best boss?'],
  Dwight:  ['What are beets good for?', 'How do I become a better employee?', 'Tell me about Schrute Farms.'],
}

function Welcome({ character, onSend }: { character: string; onSend?: (text: string) => void }) {
  const meta   = CHARACTERS[character]
  const color  = meta?.color ?? '#7c3aed'
  const prompts = STARTER_PROMPTS[character] ?? []
  const imgSrc = meta?.image ?? `/characters/${character.toLowerCase()}.webp`
  const [imgOk, setImgOk] = useState(true)

  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-5 text-center px-6 py-12 select-none animate-scaleIn">

      {/* Portrait */}
      <div
        className="w-28 h-28 rounded-2xl overflow-hidden flex items-center justify-center bg-app-surface2 transition-all duration-300"
        style={{
          boxShadow: `0 0 0 2px ${color}55, 0 0 0 4px #070709, 0 0 0 6px ${color}22, 0 0 24px ${color}33`,
        }}
      >
        {imgOk ? (
          <img
            src={imgSrc}
            alt={character}
            onError={() => setImgOk(false)}
            className="w-full h-full object-cover object-top"
          />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center text-6xl"
            style={{
              background: `radial-gradient(circle at 60% 35%, ${color}33, ${color}08 60%, #0e0e12)`,
            }}
          >
            {meta?.emoji ?? '🎬'}
          </div>
        )}
      </div>

      {/* Name + info */}
      <div>
        <h2 className="font-pixel text-[11px] mb-2" style={{ color }}>
          {character}
        </h2>
        <p className="text-xs text-slate-600 max-w-xs leading-relaxed">
          {meta?.show} &middot; {meta?.description ?? 'Start chatting'}
        </p>
      </div>

      {/* Starter chips */}
      {prompts.length > 0 && (
        <div className="flex gap-2 flex-wrap justify-center max-w-sm">
          {prompts.map((q) => (
            <button
              key={q}
              onClick={() => onSend?.(q)}
              disabled={!onSend}
              className="
                px-3 py-1.5 rounded-full text-xs
                bg-app-surface2 border border-app-border text-slate-500
                hover:text-slate-200 hover:border-app-border-hi
                disabled:cursor-default
                transition-colors duration-150
              "
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ChatArea({ messages, activeCharacter, onSend }: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4 flex flex-col gap-3 bg-app-bg">
      {messages.length === 0
        ? <Welcome character={activeCharacter} onSend={onSend} />
        : messages.map((m) => <Message key={m.id} message={m} />)
      }
      <div ref={bottomRef} />
    </div>
  )
}
