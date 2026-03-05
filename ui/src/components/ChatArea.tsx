import { useEffect, useRef } from 'react'
import type { Message as MessageType } from '../types'
import { CHARACTERS } from '../constants/characters'
import Message from './Message'

interface ChatAreaProps {
  messages: MessageType[]
  activeCharacter: string
}

function Welcome({ character }: { character: string }) {
  const meta = CHARACTERS[character]
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-4 text-center px-8 py-16 select-none animate-fadeIn">
      <span className="text-6xl">{meta?.emoji ?? '🎬'}</span>
      <div>
        <h2 className="text-lg font-semibold text-slate-100 mb-1.5">Chat with {character}</h2>
        <p className="text-sm text-slate-500 max-w-xs leading-relaxed">
          {meta?.show} &middot; Start a conversation and get replies in character,
          grounded in real scenes from the show.
        </p>
      </div>
      <div className="mt-2 flex gap-2 flex-wrap justify-center">
        {['What are you up to?', 'Tell me something interesting.', "What's your biggest pet peeve?"].map((q) => (
          <span
            key={q}
            className="px-3 py-1.5 rounded-full bg-app-surface2 border border-app-border text-xs text-slate-400 cursor-default"
          >
            {q}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function ChatArea({ messages, activeCharacter }: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll on every new message or streaming token
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-5 flex flex-col gap-3.5">
      {messages.length === 0
        ? <Welcome character={activeCharacter} />
        : messages.map((m) => <Message key={m.id} message={m} />)
      }
      <div ref={bottomRef} />
    </div>
  )
}
