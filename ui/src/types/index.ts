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
  /** Short one-liner shown on the landing page card. */
  description?: string
  /** Hex accent colour used for the hover glow on the landing card. */
  color?: string
  /** True only for characters that have ChromaDB scenes + profiles built. */
  supported?: boolean
  /**
   * Optional portrait path relative to /public (e.g. "/characters/sheldon.webp").
   * When present the landing card renders the image; when absent it falls
   * back to a styled colour-gradient avatar with the emoji.
   */
  image?: string
}

// Discriminated union of all server → client WebSocket message types
export type WSServerMessage =
  | { type: 'token'; content: string }
  | { type: 'done' }
  | { type: 'character_set'; character: string }
  | { type: 'error'; content: string }
