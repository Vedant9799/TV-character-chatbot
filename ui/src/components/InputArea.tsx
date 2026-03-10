import { useRef, type KeyboardEvent } from 'react'

interface InputAreaProps {
  onSend: (text: string) => void
  onStop: () => void
  onClear: () => void
  isStreaming: boolean
  disabled: boolean
}

export default function InputArea({ onSend, onStop, onClear, isStreaming, disabled }: InputAreaProps) {
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

  const placeholder = disabled
    ? 'Connecting…'
    : isStreaming
      ? 'Generating…'
      : 'Message… (Shift+Enter for newline)'

  return (
    <div className="input-frosted border-t border-app-border shrink-0 px-4 py-3">
      <div className="flex items-end gap-2.5">

        {/* Clear / reset history */}
        <button
          onClick={onClear}
          title="Clear chat"
          className="
            w-9 h-9 flex items-center justify-center rounded-xl
            text-slate-600 hover:text-slate-400
            border border-transparent hover:border-app-border
            transition-colors shrink-0 text-base
          "
        >
          🗑
        </button>

        {/* Message input */}
        <textarea
          ref={textareaRef}
          rows={1}
          placeholder={placeholder}
          disabled={busy}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          className="
            flex-1 bg-app-surface2 text-slate-100 border border-app-border-hi
            rounded-xl px-3.5 py-2.5 text-sm font-sans resize-none outline-none
            max-h-[130px] leading-relaxed placeholder-slate-700
            focus:border-violet-600/60 focus:ring-1 focus:ring-violet-600/20
            disabled:opacity-30 disabled:cursor-not-allowed
            transition-all duration-150
          "
        />

        {/* Stop (visible while streaming) / Send button */}
        {isStreaming ? (
          <button
            onClick={onStop}
            title="Stop generating"
            className="
              w-9 h-9 flex items-center justify-center rounded-xl
              bg-red-700 hover:bg-red-600
              text-white text-sm font-bold transition-colors shrink-0
              border border-red-600/40
            "
          >
            ■
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={busy}
            title="Send (Enter)"
            className="
              w-9 h-9 flex items-center justify-center rounded-xl
              bg-violet-700 hover:bg-violet-600
              disabled:opacity-30 disabled:cursor-not-allowed
              text-white text-base transition-colors shrink-0
              border border-violet-500/30
            "
          >
            ↑
          </button>
        )}

      </div>

      {/* Keyboard hint */}
      {!disabled && !isStreaming && (
        <p className="text-[10px] text-slate-700 text-center mt-2 select-none">
          Enter to send &nbsp;·&nbsp; Shift+Enter for newline
        </p>
      )}
    </div>
  )
}
