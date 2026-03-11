import { useState } from 'react'
import { CHARACTERS } from '../constants/characters'
import type { CharacterMeta } from '../types'

interface LandingPageProps {
  onSelectCharacter: (char: string) => void
}

// ── Character portrait ────────────────────────────────────────────────────────
function Portrait({
  name,
  meta,
  hovered,
}: {
  name: string
  meta: CharacterMeta
  hovered: boolean
}) {
  const [imgOk, setImgOk] = useState(true)
  const { emoji, color = '#7c3aed', image } = meta
  const src = image ?? `/characters/${name.toLowerCase()}.webp`

  return (
    <div
      className="relative w-full aspect-square rounded-2xl overflow-hidden transition-transform duration-300"
      style={{
        transform: hovered ? 'scale(1.04)' : 'scale(1)',
        boxShadow: hovered
          ? `0 0 0 2px ${color}, 0 0 0 4px #070709, 0 0 0 6px ${color}55, 0 0 32px ${color}44`
          : `0 0 0 2px ${color}44, 0 0 0 4px #070709, 0 0 0 6px ${color}22`,
      }}
    >
      {imgOk ? (
        <img
          src={src}
          alt={name}
          onError={() => setImgOk(false)}
          className="w-full h-full object-cover object-top"
          style={{ imageRendering: 'auto' }}
        />
      ) : (
        <div
          className="w-full h-full flex items-center justify-center text-[5.5rem] select-none"
          style={{
            background: `radial-gradient(circle at 60% 35%, ${color}33, ${color}0a 60%, #0e0e12)`,
          }}
        >
          {emoji}
        </div>
      )}

      {/* Bottom gradient for text legibility */}
      <div
        className="absolute inset-x-0 bottom-0 h-2/5"
        style={{ background: 'linear-gradient(to top, rgba(7,7,9,0.85) 0%, transparent 100%)' }}
      />
    </div>
  )
}

// ── Character card ────────────────────────────────────────────────────────────
function CharacterCard({
  name, meta, onClick,
}: {
  name: string
  meta: CharacterMeta
  onClick: () => void
}) {
  const { color = '#7c3aed', description, show } = meta
  const [hovered, setHovered] = useState(false)
  const showLabel = show === 'The Big Bang Theory' ? 'THE BIG BANG THEORY' : 'THE OFFICE'

  return (
    <div
      className="group flex flex-col gap-3 text-left w-full"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button onClick={onClick} className="w-full focus:outline-none block">
        <Portrait name={name} meta={meta} hovered={hovered} />
      </button>

      {/* Text block — click also goes to chat */}
      <button onClick={onClick} className="px-1 flex flex-col gap-1 text-left w-full focus:outline-none">
        <span
          className="font-pixel text-[10px] leading-tight transition-colors duration-200"
          style={{ color: hovered ? color : '#e2e8f0' }}
        >
          {name}
        </span>

        {description && (
          <p className="text-[11px] text-slate-600 leading-snug">{description}</p>
        )}

        <span
          className="mt-0.5 font-pixel text-[7px] tracking-widest"
          style={{ color: `${color}66` }}
        >
          {showLabel}
        </span>
      </button>
    </div>
  )
}

// ── Landing page ──────────────────────────────────────────────────────────────
export default function LandingPage({ onSelectCharacter }: LandingPageProps) {
  const entries = Object.entries(CHARACTERS)

  return (
    <div className="min-h-dvh dot-grid flex flex-col items-center px-6 py-14 overflow-y-auto scrollbar-thin">

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <div className="text-center mb-16 animate-fadeIn">
        <div className="font-pixel text-[9px] text-violet-500 tracking-widest mb-6 opacity-80 select-none">
          INTERACTIVE&nbsp;&nbsp;ROLEPLAY
        </div>

        <h1 className="text-5xl sm:text-7xl font-extrabold text-white leading-none tracking-tight">
          TV Character
          <span className="gradient-text"> Chatbot</span>
        </h1>
      </div>

      {/* ── Character grid ────────────────────────────────────────────────── */}
      <div className="w-full animate-scaleIn" style={{ maxWidth: '860px' }}>
        <div className="grid grid-cols-3 gap-6 sm:gap-10">
          {entries.map(([name, meta]) => (
            <CharacterCard
              key={name}
              name={name}
              meta={meta}
              onClick={() => onSelectCharacter(name)}
            />
          ))}
        </div>
      </div>

    </div>
  )
}
