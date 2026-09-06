import { useState } from 'react'
import type { Citation } from '../types'

function CitationRow({ c }: { c: Citation }) {
  const [open, setOpen] = useState(false)
  const unverified = c.review_status !== 'verified'
  return (
    <li className="rounded-md border border-slate-200 dark:border-slate-700">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start justify-between gap-2 p-3 text-left"
      >
        <span>
          <span className="text-sm font-medium">
            {c.title}
            {c.heading ? <span className="text-slate-400"> § {c.heading}</span> : null}
          </span>
          <span className="mt-0.5 block text-xs text-slate-500">{c.sources.join('; ')}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {unverified && (
            <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-700 dark:bg-rose-900 dark:text-rose-200">
              UNVERIFIED
            </span>
          )}
          <span className="font-mono text-xs text-slate-400">{c.score.toFixed(2)}</span>
        </span>
      </button>
      {open && (
        <p className="whitespace-pre-wrap border-t border-slate-200 p-3 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300">
          {c.text}
        </p>
      )}
    </li>
  )
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) {
    return <p className="text-sm text-slate-500">No regulatory context retrieved for this snapshot.</p>
  }
  return (
    <ul className="space-y-2">
      {citations.map((c, i) => (
        <CitationRow key={i} c={c} />
      ))}
    </ul>
  )
}
