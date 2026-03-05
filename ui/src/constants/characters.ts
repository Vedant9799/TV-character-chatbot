import type { CharacterMeta, CharacterShow } from '../types'

export const CHARACTERS: Record<string, CharacterMeta> = {
  // The Big Bang Theory
  Sheldon:    { emoji: '🧪', show: 'The Big Bang Theory' },
  Leonard:    { emoji: '🔭', show: 'The Big Bang Theory' },
  Penny:      { emoji: '🥂', show: 'The Big Bang Theory' },
  Howard:     { emoji: '🚀', show: 'The Big Bang Theory' },
  Raj:        { emoji: '⭐', show: 'The Big Bang Theory' },
  Bernadette: { emoji: '🦠', show: 'The Big Bang Theory' },
  Amy:        { emoji: '🧠', show: 'The Big Bang Theory' },

  // The Office
  Michael:    { emoji: '👔', show: 'The Office' },
  Dwight:     { emoji: '🌱', show: 'The Office' },
  Jim:        { emoji: '😏', show: 'The Office' },
  Pam:        { emoji: '🎨', show: 'The Office' },
  Andy:       { emoji: '🎵', show: 'The Office' },
  Ryan:       { emoji: '💼', show: 'The Office' },
  Kevin:      { emoji: '🍪', show: 'The Office' },
  Angela:     { emoji: '🐱', show: 'The Office' },
}

export const SHOWS: CharacterShow[] = ['The Big Bang Theory', 'The Office']

export const DEFAULT_CHARACTER = 'Sheldon'
