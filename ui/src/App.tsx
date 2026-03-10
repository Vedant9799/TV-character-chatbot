import { useState } from 'react'
import { DEFAULT_CHARACTER } from './constants/characters'
import LandingPage  from './components/LandingPage'
import ChatView     from './components/ChatView'
import CompareView  from './components/CompareView'

type View = 'landing' | 'chat' | 'compare'

export default function App() {
  const [view,              setView]              = useState<View>('landing')
  const [selectedCharacter, setSelectedCharacter] = useState(DEFAULT_CHARACTER)

  const handleSelectCharacter = (char: string) => {
    setSelectedCharacter(char)
    setView('chat')
  }

  const handleCompare = (char: string) => {
    setSelectedCharacter(char)
    setView('compare')
  }

  const handleBack = () => setView('landing')

  return (
    <div className="min-h-dvh bg-app-bg text-slate-100">
      {view === 'landing' && (
        <LandingPage
          onSelectCharacter={handleSelectCharacter}
          onCompare={handleCompare}
        />
      )}
      {view === 'chat' && (
        <ChatView initialCharacter={selectedCharacter} onBack={handleBack} />
      )}
      {view === 'compare' && (
        <CompareView initialCharacter={selectedCharacter} onBack={handleBack} />
      )}
    </div>
  )
}
