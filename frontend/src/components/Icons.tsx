// Small hand-rolled icon set (no icon-library dependency) — 24x24 stroke
// icons in the currentColor convention, so each usage site controls color
// via Tailwind text-* classes.
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function base(props: IconProps) {
  return {
    xmlns: 'http://www.w3.org/2000/svg',
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    ...props,
  }
}

export function WifiIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M2 8.5c5.5-5 14.5-5 20 0" />
      <path d="M5 12.5c4-3.5 10-3.5 14 0" />
      <path d="M8.2 16.3c2.2-1.9 5.4-1.9 7.6 0" />
      <circle cx="12" cy="20" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function ChatIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 5.5h16a1 1 0 0 1 1 1V16a1 1 0 0 1-1 1H9l-4.5 3.8a.5.5 0 0 1-.82-.38V17H4a1 1 0 0 1-1-1V6.5a1 1 0 0 1 1-1Z" />
      <path d="M8 10h8M8 13h5" />
    </svg>
  )
}

export function AntennaIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3v18" />
      <path d="M7 8c-1.6 1.4-1.6 4.6 0 6M17 8c1.6 1.4 1.6 4.6 0 6" />
      <path d="M4 5c-2.8 2.6-2.8 8.4 0 11M20 5c2.8 2.6 2.8 8.4 0 11" />
      <circle cx="12" cy="4" r="1.4" fill="currentColor" stroke="none" />
      <path d="M9 21h6" />
    </svg>
  )
}

export function BookIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 5.5c2.5-1.2 5-1.2 7 .3v13c-2-1.5-4.5-1.5-7-.3v-13Z" />
      <path d="M20 5.5c-2.5-1.2-5-1.2-7 .3v13c2-1.5 4.5-1.5 7-.3v-13Z" />
    </svg>
  )
}

export function SendIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4.5 12 20 4.5 13.5 19l-2-6.5-7-2Z" />
      <path d="M11.5 12.5 20 4.5" />
    </svg>
  )
}

export function PlusIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function RefreshIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M20 11a8 8 0 0 0-14.6-4.6M4 13a8 8 0 0 0 14.6 4.6" />
      <path d="M4.5 4.5v4.5H9M19.5 19.5V15H15" />
    </svg>
  )
}

export function TrashIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 7h14M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m3 0-.8 12.2a1 1 0 0 1-1 .8H8.8a1 1 0 0 1-1-.8L7 7" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  )
}

export function SparkleIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3.5 13.6 9l5.5 1.6-5.5 1.6L12 17.7l-1.6-5.5L4.9 10.6l5.5-1.6L12 3.5Z" />
    </svg>
  )
}

export function BrainIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9.5 4.2a2.6 2.6 0 0 0-2.6 2.6v.3A2.7 2.7 0 0 0 5 9.6v.8a2.7 2.7 0 0 0-1 4.6c-.1.3-.2.6-.2 1a2.6 2.6 0 0 0 3.3 2.5 2.6 2.6 0 0 0 4.9-1.2V6.8a2.6 2.6 0 0 0-2.5-2.6Z" />
      <path d="M14.5 4.2a2.6 2.6 0 0 1 2.6 2.6v.3A2.7 2.7 0 0 1 19 9.6v.8a2.7 2.7 0 0 1 1 4.6c.1.3.2.6.2 1a2.6 2.6 0 0 1-3.3 2.5 2.6 2.6 0 0 1-4.9-1.2V6.8a2.6 2.6 0 0 1 2.5-2.6Z" />
      <path d="M9.5 9.5c.9.5 1.6.5 2.5 0M9.2 13.8c.9.5 1.6.5 2.5 0M14.8 9.5c-.9.5-1.6.5-2.5 0M14.8 13.8c-.9.5-1.6.5-2.5 0" />
    </svg>
  )
}
