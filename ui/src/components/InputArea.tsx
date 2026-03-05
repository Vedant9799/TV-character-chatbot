import { useRef, type KeyboardEvent } from 'react'

interface InputAreaProps {
  onSend: (text: string) => void
  onClear: () => void
  isStreaming: boolean
  disabled: boolean
}

export default function InputArea({ onSend, onClear, isStreaming, disabled }: InputAreaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

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

  // Auto-grow textarea up to 130 px
  const handleInput = () => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 130)}px`
  }

  const busy = disabled || isStreaming

  return (
    <div className="flex items-end gap-2.5 px-5 py-3.5 bg-app-surface border-t border-app-border shrink-0">

      {/* Clear / reset history */}
      <button
        onClick={onClear}
        title="Clear chat"
        className="
          w-11 h-11 flex items-center justify-center rounded-xl
          border border-app-border text-slate-500
          hover:text-slate-100 hover:border-slate-500
          transition-colors shrink-0 text-lg
        "
      >
        🗑
      </button>

      {/* Message input */}
      <textarea
        ref={textareaRef}
        rows={1}
        placeholder={disabled ? 'Connecting…' : isStreaming ? 'Waiting for reply…' : 'Say something… (Shift+Enter for newline)'}
        disabled={busy}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        className="
          flex-1 bg-app-surface2 text-slate-100 border border-app-border
          rounded-xl px-3.5 py-2.5 text-sm font-sans resize-none outline-none
          max-h-[130px] leading-relaxed placeholder-slate-600
          focus:border-violet-500
          disabled:opacity-40 disabled:cursor-not-allowed
          transition-colors
        "
      />

      {/* Send */}
      <button
        onClick={submit}
        disabled={busy}
        title="Send (Enter)"
        className="
          w-11 h-11 flex items-center justify-center rounded-xl
          bg-violet-600 hover:bg-violet-500
          disabled:opacity-40 disabled:cursor-not-allowed
          text-white text-lg transition-colors shrink-0
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
