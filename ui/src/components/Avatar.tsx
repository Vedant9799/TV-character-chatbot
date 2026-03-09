interface AvatarProps {
  name: string
  size?: number       // px, default 32
  className?: string  // additional wrapper classes (e.g. ring, shadow)
}

/**
 * Renders a cartoon caricature avatar using DiceBear's "adventurer" style.
 * Each character gets a unique but deterministic look based on their name.
 */
export default function Avatar({ name, size = 32, className = '' }: AvatarProps) {
  const seed = encodeURIComponent(name)
  const src = `https://api.dicebear.com/7.x/adventurer/svg?seed=${seed}&backgroundColor=b6e3f4,c0aede,d1d4f9,ffd5dc,ffdfbf`

  return (
    <img
      src={src}
      alt={name}
      width={size}
      height={size}
      className={`rounded-full shrink-0 ${className}`}
      loading="lazy"
    />
  )
}
