export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

export type MessageRole = 'user' | 'bot' | 'system'

export interface Message {
  id: string
  role: MessageRole
  content: string
  streaming: boolean
  character?: string  // set on bot messages
}

export type CharacterShow = 'The Big Bang Theory' | 'The Office'

export interface CharacterMeta {
  emoji: string
  show: CharacterShow
}

// Discriminated union of all server → client WebSocket message types
export type WSServerMessage =
  | { type: 'token'; content: string }
  | { type: 'done' }
  | { type: 'character_set'; character: string }
  | { type: 'error'; content: string }
