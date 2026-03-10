import { useState } from 'react'
import { CHARACTERS } from '../constants/characters'
import type { CharacterMeta } from '../types'

interface LandingPageProps {
  onSelectCharacter: (char: string) => void
}

// ── Character portrait ───────────────────────────────────────────────────────
// Tries to load /characters/<name>.webp (or .jpg/.png).
// Falls back to a colour-gradient avatar with the character emoji.
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
        // Pixel-art stepped ring: two box-shadow layers create a "notched" border
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
        // Styled fallback: gradient bg + large emoji
        <div
          className="w-full h-full flex items-center justify-center text-[5.5rem] select-none"
          style={{
            background: `radial-gradient(circle at 60% 35%, ${color}33, ${color}0a 60%, #0e0e12)`,
          }}
        >
          {emoji}
        </div>
      )}

      {/* Bottom gradient overlay for text legibility */}
      <div
        className="absolute inset-x-0 bottom-0 h-2/5"
        style={{
          background: 'linear-gradient(to top, rgba(7,7,9,0.85) 0%, transparent 100%)',
        }}
      />
    </div>
  )
}

// ── Character card ───────────────────────────────────────────────────────────
function CharacterCard({
  name,
  meta,
  onClick,
}: {
  name: string
  meta: CharacterMeta
  onClick: () => void
}) {
  const { color = '#7c3aed', description, show } = meta
  const [hovered, setHovered] = useState(false)

  // Show label: abbreviate for space
  const showLabel = show === 'The Big Bang Theory' ? 'THE BIG BANG THEORY' : 'THE OFFICE'

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="group flex flex-col gap-3 text-left w-full focus:outline-none"
    >
      <Portrait name={name} meta={meta} hovered={hovered} />

      {/* Text block below the portrait */}
      <div className="px-1 flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className="font-pixel text-[10px] leading-tight transition-colors duration-200"
            style={{ color: hovered ? color : '#e2e8f0' }}
          >
            {name}
          </span>
        </div>

        {description && (
          <p className="text-[11px] text-slate-600 leading-snug">{description}</p>
        )}

        <span
          className="mt-0.5 font-pixel text-[7px] tracking-widest"
          style={{ color: `${color}66` }}
        >
          {showLabel}
        </span>
      </div>
    </button>
  )
}

// ── Landing page ─────────────────────────────────────────────────────────────
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
          <br />
          <span className="gradient-text">Chatbot</span>
        </h1>

        <p className="mt-6 text-sm text-slate-500 max-w-xs mx-auto leading-relaxed">
          Chat with your favourite TV characters. Replies grounded in real
          dialogue via RAG.
        </p>
      </div>

      {/* ── Character grid — 2 × 2 ──────────────────────────────────────── */}
      <div
        className="w-full animate-scaleIn"
        style={{ maxWidth: '680px' }}
      >
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5 sm:gap-6">
          {entries.map(([name, meta]) => (
            <CharacterCard
              key={name}
              name={name}
              meta={meta}
              onClick={() => onSelectCharacter(name)}
            />
          ))}
        </div>

        {/* Drop-in hint */}
        <p className="mt-10 text-center font-pixel text-[7px] text-slate-800 leading-relaxed select-none">
          DROP PORTRAITS INTO&nbsp;
          <span className="text-slate-600">ui/public/characters/</span>
          &nbsp;TO REPLACE EMOJI
        </p>
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="mt-12 font-pixel text-[7px] text-slate-800 text-center select-none">
        TBBT &nbsp;·&nbsp; THE OFFICE &nbsp;·&nbsp; LOCAL LLM &nbsp;·&nbsp; RAG
      </div>
    </div>
  )
}
