import type { Confidence } from '../types'

const STYLES: Record<Confidence, string> = {
  high: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  low: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
}

export function ConfidenceBadge({ value }: { value: Confidence }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STYLES[value]}`}>
      {value} confidence
    </span>
  )
}
