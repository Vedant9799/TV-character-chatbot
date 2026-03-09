import type { CharacterMeta, CharacterShow } from '../types'

export const CHARACTERS: Record<string, CharacterMeta> = {
  // The Big Bang Theory
  Sheldon:    { show: 'The Big Bang Theory', fullName: 'Sheldon Cooper',         role: 'Theoretical Physicist',   color: 'bg-sky-500'    },
  Leonard:    { show: 'The Big Bang Theory', fullName: 'Leonard Hofstadter',      role: 'Experimental Physicist',  color: 'bg-amber-600'  },
  Penny:      { show: 'The Big Bang Theory', fullName: 'Penny',                   role: 'Aspiring Actress / Rep',  color: 'bg-pink-400'   },
  Howard:     { show: 'The Big Bang Theory', fullName: 'Howard Wolowitz',         role: 'Aerospace Engineer',      color: 'bg-indigo-500' },
  Raj:        { show: 'The Big Bang Theory', fullName: 'Raj Koothrappali',        role: 'Astrophysicist',          color: 'bg-violet-500' },
  Bernadette: { show: 'The Big Bang Theory', fullName: 'Bernadette Rostenkowski', role: 'Microbiologist',          color: 'bg-emerald-500'},
  Amy:        { show: 'The Big Bang Theory', fullName: 'Amy Farrah Fowler',       role: 'Neurobiologist',          color: 'bg-teal-500'   },

  // The Office
  Michael:    { show: 'The Office', fullName: 'Michael Scott',   role: 'Regional Manager',        color: 'bg-blue-500'   },
  Dwight:     { show: 'The Office', fullName: 'Dwight Schrute',  role: 'Asst. Regional Manager',  color: 'bg-yellow-600' },
  Jim:        { show: 'The Office', fullName: 'Jim Halpert',     role: 'Sales Representative',    color: 'bg-cyan-500'   },
  Pam:        { show: 'The Office', fullName: 'Pam Beesly',      role: 'Receptionist',            color: 'bg-rose-400'   },
  Andy:       { show: 'The Office', fullName: 'Andy Bernard',    role: 'Regional Director',       color: 'bg-orange-500' },
  Ryan:       { show: 'The Office', fullName: 'Ryan Howard',     role: 'Temp / Executive',        color: 'bg-slate-500'  },
  Kevin:      { show: 'The Office', fullName: 'Kevin Malone',    role: 'Accountant',              color: 'bg-amber-500'  },
  Angela:     { show: 'The Office', fullName: 'Angela Martin',   role: 'Head of Accounting',      color: 'bg-purple-400' },
}

export const SHOWS: CharacterShow[] = ['The Big Bang Theory', 'The Office']

export const DEFAULT_CHARACTER = 'Sheldon'
