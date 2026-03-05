import { CHARACTERS } from '../constants/characters'

interface CharacterBannerProps {
  character: string
}

export default function CharacterBanner({ character }: CharacterBannerProps) {
  const meta = CHARACTERS[character]

  return (
    <div className="flex items-center gap-3 px-5 py-2.5 bg-app-surface/60 border-b border-app-border/60 shrink-0">
      <span className="text-xl select-none">{meta?.emoji ?? '🎬'}</span>
      <div className="flex items-baseline gap-2 min-w-0">
        <span className="text-sm font-semibold text-slate-100 truncate">{character}</span>
        <span className="text-xs text-slate-500 whitespace-nowrap">· {meta?.show}</span>
      </div>
    </div>
  )
}
