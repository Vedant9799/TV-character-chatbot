import { useWebSocket } from '../hooks/useWebSocket'
import { useChat } from '../hooks/useChat'
import Header from './Header'
import ChatArea from './ChatArea'
import InputArea from './InputArea'

interface ChatViewProps {
  initialCharacter: string
  onBack: () => void
}

export default function ChatView({ initialCharacter, onBack }: ChatViewProps) {
  // In production (Vercel + Render split deploy) set VITE_BACKEND_URL to the
  // Render service hostname, e.g. "my-chatbot.onrender.com".
  // In local dev this is undefined, so we fall back to the same host (Vite proxy handles it).
  const backendHost = import.meta.env.VITE_BACKEND_URL || location.host
  const wsProto     = location.protocol === 'https:' ? 'wss' : 'ws'
  const wsUrl       = `${wsProto}://${backendHost}/ws`

  const { send, status, onMessageRef } = useWebSocket(wsUrl)
  const {
    messages,
    isStreaming,
    activeCharacter,
    setCharacter,
    sendMessage,
    stopStreaming,
    clearChat,
  } = useChat(send, onMessageRef, status, initialCharacter)

  return (
    <div className="flex flex-col h-dvh max-w-3xl mx-auto">
      <Header
        activeCharacter={activeCharacter}
        onCharacterChange={setCharacter}
        onBack={onBack}
        status={status}
      />

      <ChatArea
        messages={messages}
        activeCharacter={activeCharacter}
        onSend={status === 'connected' && !isStreaming ? sendMessage : undefined}
      />

      <InputArea
        onSend={sendMessage}
        onStop={stopStreaming}
        onClear={clearChat}
        isStreaming={isStreaming}
        disabled={status !== 'connected'}
      />
    </div>
  )
}
