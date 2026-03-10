import { useState } from 'react'
import { DEFAULT_CHARACTER } from './constants/characters'
import LandingPage from './components/LandingPage'
import ChatView from './components/ChatView'

type View = 'landing' | 'chat'

export default function App() {
  const [view, setView] = useState<View>('landing')
  const [selectedCharacter, setSelectedCharacter] = useState(DEFAULT_CHARACTER)

  const handleSelectCharacter = (char: string) => {
    setSelectedCharacter(char)
    setView('chat')
  }

  const handleBack = () => {
    setView('landing')
  }

  return (
    <div className="min-h-dvh bg-app-bg text-slate-100">
      {view === 'landing' ? (
        <LandingPage onSelectCharacter={handleSelectCharacter} />
      ) : (
        <ChatView
          initialCharacter={selectedCharacter}
          onBack={handleBack}
        />
      )}
    </div>
  )
}
