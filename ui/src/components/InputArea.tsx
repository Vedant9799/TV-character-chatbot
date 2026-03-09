import { useRef, type KeyboardEvent } from 'react'
import { CHARACTERS } from '../constants/characters'

interface InputAreaProps {
  onSend: (text: string) => void
  onClear: () => void
  isStreaming: boolean
  disabled: boolean
  activeCharacter: string
}

export default function InputArea({ onSend, onClear, isStreaming, disabled, activeCharacter }: InputAreaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const meta = CHARACTERS[activeCharacter]

  const submit = () => {
    const text = textareaRef.current?.value ?? ''
    if (!text.trim() || isStreaming || disabled) return
    onSend(text)
    if (textareaRef.current) {
      textareaRef.current.value = ''
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const handleInput = () => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 130)}px`
  }

  const busy = disabled || isStreaming
  const placeholder = disabled
    ? 'Connecting…'
    : isStreaming
      ? 'Waiting for reply…'
      : `Message ${meta?.fullName ?? activeCharacter}...`

  return (
    <div className="flex items-end gap-2.5 px-6 py-3 shrink-0">
      {/* Clear */}
      <button
        onClick={onClear}
        title="Clear chat"
        className="
          w-10 h-10 flex items-center justify-center rounded-full
          border border-gray-200 text-gray-400 bg-white/70
          hover:text-gray-600 hover:border-gray-300
          transition-colors shrink-0 text-sm
        "
      >
        🗑
      </button>

      {/* Input */}
      <textarea
        ref={textareaRef}
        rows={1}
        placeholder={placeholder}
        disabled={busy}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        className="
          flex-1 bg-white/80 text-gray-800 border border-gray-200
          rounded-full px-4 py-2.5 text-sm font-sans resize-none outline-none
          max-h-[130px] leading-relaxed placeholder-gray-400
          focus:border-rose-400 focus:ring-1 focus:ring-rose-200
          disabled:opacity-40 disabled:cursor-not-allowed
          transition-colors shadow-sm
        "
      />

      {/* Send */}
      <button
        onClick={submit}
        disabled={busy}
        title="Send (Enter)"
        className="
          w-10 h-10 flex items-center justify-center rounded-full
          bg-rose-400 hover:bg-rose-500
          disabled:opacity-40 disabled:cursor-not-allowed
          text-white text-sm transition-colors shrink-0 shadow-sm
        "
      >
        {isStreaming ? (
          <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
        ) : (
          '➤'
        )}
      </button>
    </div>
  )
}
