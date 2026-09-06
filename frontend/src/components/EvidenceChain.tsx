import type { EvidenceItem } from '../types'

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export function EvidenceChain({ items }: { items: EvidenceItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No evidence cited.</p>
  }
  return (
    <ol className="space-y-3">
      {items.map((e, i) => (
        <li key={i} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
          <div className="flex flex-wrap items-baseline gap-x-2 font-mono text-sm">
            <span className="text-slate-500">{e.field_path}</span>
            <span className="text-slate-400">=</span>
            <span className="font-semibold text-slate-900 dark:text-slate-100">
              {fmt(e.observed_value)}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{e.why_it_matters}</p>
        </li>
      ))}
    </ol>
  )
}
