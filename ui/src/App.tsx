import { useWebSocket } from './hooks/useWebSocket'
import { useChat } from './hooks/useChat'
import Header from './components/Header'
import CharacterBanner from './components/CharacterBanner'
import ChatArea from './components/ChatArea'
import InputArea from './components/InputArea'

export default function App() {
  // Resolve WebSocket URL — in dev, Vite proxies /ws → localhost:8000
  const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`

  const { send, status, lastMessage } = useWebSocket(wsUrl)
  const {
    messages,
    isStreaming,
    activeCharacter,
    setCharacter,
    sendMessage,
    stopStreaming,
    clearChat,
  } = useChat(send, lastMessage, status)

  return (
    <div className="flex flex-col h-dvh max-w-3xl mx-auto bg-app-bg text-slate-100">
      <Header
        activeCharacter={activeCharacter}
        onCharacterChange={setCharacter}
        status={status}
      />

      <CharacterBanner character={activeCharacter} />

      <ChatArea
        messages={messages}
        activeCharacter={activeCharacter}
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
