import { useMemo, useState } from 'react'
import type { Band, TaxonomyCause } from '../types'
import { BookIcon } from './Icons'

const BAND_ORDER: Band[] = ['2.4GHz', '5GHz', '6GHz']

// Each band gets its own color identity throughout the panel (filter tabs,
// section headers, selected-item highlight, band chips) so 2.4/5/6 GHz are
// visually distinguishable at a glance, not just by their text label.
const BAND_STYLE: Record<Band, { dot: string; text: string; activeBg: string; chip: string }> = {
  '2.4GHz': {
    dot: 'bg-emerald-500',
    text: 'text-emerald-600 dark:text-emerald-400',
    activeBg: 'bg-gradient-to-r from-emerald-500 to-teal-500',
    chip: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200',
  },
  '5GHz': {
    dot: 'bg-sky-500',
    text: 'text-sky-600 dark:text-sky-400',
    activeBg: 'bg-gradient-to-r from-sky-500 to-blue-500',
    chip: 'bg-sky-100 text-sky-700 dark:bg-sky-900 dark:text-sky-200',
  },
  '6GHz': {
    dot: 'bg-violet-500',
    text: 'text-violet-600 dark:text-violet-400',
    activeBg: 'bg-gradient-to-r from-violet-500 to-fuchsia-500',
    chip: 'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-200',
  },
}
const ALL_BANDS_ACTIVE_BG = 'bg-gradient-to-r from-sky-600 to-violet-600'

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
        <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-slate-500">
          <BookIcon className="h-4 w-4 text-violet-500" />
          Wireless Topics
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          What this system can diagnose, browsable by band — the same taxonomy the diagnosis
          and live-test paths assert causes from.
        </p>

        <div className="mb-3 flex flex-wrap gap-1">
          {(['all', ...BAND_ORDER] as const).map((b) => {
            const active = filterBand === b
            const style = b === 'all' ? undefined : BAND_STYLE[b]
            return (
              <button
                key={b}
                onClick={() => setFilterBand(b)}
                className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium ${
                  active
                    ? `${b === 'all' ? ALL_BANDS_ACTIVE_BG : style!.activeBg} text-white shadow-sm`
                    : `${style?.text ?? 'text-slate-500'} hover:bg-slate-100 dark:hover:bg-slate-800`
                }`}
              >
                {style && <span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-white' : style.dot}`} />}
                {b === 'all' ? 'All bands' : b}
              </button>
            )
          })}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto">
          {bandsToShow.map((band) => {
            const items = grouped.get(band) ?? []
            if (items.length === 0) return null
            return (
              <div key={band}>
                <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold">
                  <span className={`h-2 w-2 rounded-full ${BAND_STYLE[band].dot}`} />
                  <span className={BAND_STYLE[band].text}>{band}</span>
                </h3>
                <ul className="space-y-1">
                  {items.map((c) => (
                    <li key={c.id}>
                      <button
                        onClick={() => setSelectedId(c.id)}
                        className={`w-full rounded-md px-3 py-2 text-left text-xs ${
                          c.id === selectedId
                            ? `${BAND_STYLE[band].activeBg} text-white shadow-sm`
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
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-xs text-slate-400">{selected.id}</span>
                {selected.bands.map((b) => (
                  <span
                    key={b}
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${BAND_STYLE[b]?.chip ?? ''}`}
                  >
                    {b}
                  </span>
                ))}
              </div>
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
