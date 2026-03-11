import type { CharacterMeta, CharacterShow } from '../types'

export const CHARACTERS: Record<string, CharacterMeta> = {
  // ── The Big Bang Theory ─────────────────────────────────────────────────
  Sheldon: {
    emoji: '🧪', show: 'The Big Bang Theory', supported: true,
    color: '#3b82f6', description: 'Theoretical physicist · IQ 187',
    image: '/portraits/sheldon.jpg',
  },
  // ── The Office ──────────────────────────────────────────────────────────
  Michael: {
    emoji: '👔', show: 'The Office', supported: true,
    color: '#ef4444', description: 'World\'s best boss (self-proclaimed)',
    image: '/portraits/michael.jpg',
  },
  Dwight: {
    emoji: '🌱', show: 'The Office', supported: true,
    color: '#d97706', description: 'Assistant to the Regional Manager',
    image: '/portraits/dwight.jpg',
  },
}

export const SHOWS: CharacterShow[] = ['The Big Bang Theory', 'The Office']

export const DEFAULT_CHARACTER = 'Sheldon'
