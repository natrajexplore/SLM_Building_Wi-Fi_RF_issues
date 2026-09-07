import { useMemo, useState } from 'react'
import type { Band, TaxonomyCause } from '../types'

const BAND_ORDER: Band[] = ['2.4GHz', '5GHz', '6GHz']

const SEVERITY_STYLE: Record<string, string> = {
  high: 'bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-200',
  medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200',
  low: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
}

export function WirelessTopicsPanel({ causes }: { causes: TaxonomyCause[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filterBand, setFilterBand] = useState<Band | 'all'>('all')

  const grouped = useMemo(() => {
    const byBand = new Map<Band, TaxonomyCause[]>()
    for (const band of BAND_ORDER) byBand.set(band, [])
    for (const c of causes) {
      for (const band of c.bands) {
        if (!byBand.has(band)) byBand.set(band, [])
        byBand.get(band)!.push(c)
      }
    }
    return byBand
  }, [causes])

  const causeName = useMemo(() => {
    const m = new Map(causes.map((c) => [c.id, c.name]))
    return (id: string) => m.get(id) ?? id
  }, [causes])

  const selected = causes.find((c) => c.id === selectedId) ?? null
  const bandsToShow = filterBand === 'all' ? BAND_ORDER : [filterBand]

  return (
    <>
      <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Wireless Topics
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          What this system can diagnose, browsable by band — the same taxonomy the diagnosis
          and live-test paths assert causes from.
        </p>

        <div className="mb-3 flex flex-wrap gap-1">
          {(['all', ...BAND_ORDER] as const).map((b) => (
            <button
              key={b}
              onClick={() => setFilterBand(b)}
              className={`rounded-md px-2 py-1 text-xs font-medium ${
                filterBand === b
                  ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
            >
              {b === 'all' ? 'All bands' : b}
            </button>
          ))}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto">
          {bandsToShow.map((band) => {
            const items = grouped.get(band) ?? []
            if (items.length === 0) return null
            return (
              <div key={band}>
                <h3 className="mb-1 text-xs font-semibold text-slate-400">{band}</h3>
                <ul className="space-y-1">
                  {items.map((c) => (
                    <li key={c.id}>
                      <button
                        onClick={() => setSelectedId(c.id)}
                        className={`w-full rounded-md px-3 py-2 text-left text-xs ${
                          c.id === selectedId
                            ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                            : 'hover:bg-slate-100 dark:hover:bg-slate-800'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate">{c.name}</span>
                          {c.severity_default && (
                            <span
                              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                                c.id === selectedId
                                  ? 'bg-black/10 dark:bg-white/20'
                                  : SEVERITY_STYLE[c.severity_default] ?? ''
                              }`}
                            >
                              {c.severity_default}
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 font-mono opacity-70">{c.id}</div>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        {!selected ? (
          <p className="py-16 text-center text-sm text-slate-400">
            Pick a topic to see what it means and how it's diagnosed.
          </p>
        ) : (
          <div className="space-y-6">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-semibold">{selected.name}</h3>
                {selected.severity_default && (
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      SEVERITY_STYLE[selected.severity_default] ?? ''
                    }`}
                  >
                    {selected.severity_default} severity
                  </span>
                )}
              </div>
              <p className="mt-0.5 font-mono text-xs text-slate-400">
                {selected.id} · {selected.bands.join(', ')}
              </p>
            </div>

            {selected.description && (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-200">
                {selected.description}
              </p>
            )}

            {selected.discriminators && (
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  How it's told apart from similar issues
                </h4>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                  {selected.discriminators}
                </p>
              </div>
            )}

            {selected.remediation_intent.length > 0 && (
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Remediation intent
                </h4>
                <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-300">
                  {selected.remediation_intent.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {selected.confusable_with.length > 0 && (
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Often confused with
                </h4>
                <ul className="space-y-1">
                  {selected.confusable_with.map((cid) => (
                    <li key={cid}>
                      <button
                        onClick={() => setSelectedId(cid)}
                        className="text-sm text-slate-700 underline decoration-slate-300 hover:decoration-slate-600 dark:text-slate-300 dark:decoration-slate-600 dark:hover:decoration-slate-300"
                      >
                        {causeName(cid)}
                      </button>
                      <span className="ml-1 font-mono text-xs text-slate-400">{cid}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}
