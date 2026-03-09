import { useState } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useChat } from './hooks/useChat'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import ChatArea from './components/ChatArea'
import InputArea from './components/InputArea'
import { CHARACTERS } from './constants/characters'

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
    clearChat,
  } = useChat(send, lastMessage, status)

  const [activeShow, setActiveShow] = useState(
    CHARACTERS[activeCharacter]?.show ?? 'The Big Bang Theory',
  )

  const handleShowChange = (show: string) => {
    setActiveShow(show)
    // Select first character in the new show
    const first = Object.entries(CHARACTERS).find(([, m]) => m.show === show)
    if (first) setCharacter(first[0])
  }

  return (
    <div className="flex h-dvh bg-gradient-to-br from-rose-50 via-white to-violet-100">
      <Sidebar
        activeCharacter={activeCharacter}
        onCharacterChange={setCharacter}
        status={status}
        activeShow={activeShow}
        onShowChange={handleShowChange}
      />

      <main className="flex-1 flex flex-col min-w-0">
        <Header activeCharacter={activeCharacter} status={status} />

        <ChatArea messages={messages} activeCharacter={activeCharacter} />

        <InputArea
          onSend={sendMessage}
          onClear={clearChat}
          isStreaming={isStreaming}
          disabled={status !== 'connected'}
          activeCharacter={activeCharacter}
        />

        <p className="text-center text-[10px] text-gray-400 py-1.5">
          Powered by RAG Engine &bull; SceneChat
        </p>
      </main>
    </div>
  )
}
