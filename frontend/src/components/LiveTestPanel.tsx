import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { LiveSample } from '../types'
import { DiagnosisView } from './DiagnosisView'
import { ExplanationPanel } from './ExplanationPanel'

// How often to poll GET /live/feed. The feed is push-fed by a probe (e.g.
// hardware/esp32_rf_probe with BACKEND_URL -> /live/ingest); this is not a
// realtime stream, just a cheap poll of an in-memory buffer.
const POLL_MS = 3000
const MAX_SAMPLES = 50

interface MiniSnapshot {
  radio?: { channel?: number; band?: string }
}

export function LiveTestPanel({ causeName }: { causeName: (id: string) => string }) {
  const [samples, setSamples] = useState<LiveSample[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [follow, setFollow] = useState(true)
  const [reachable, setReachable] = useState(true)
  const lastIdRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    async function poll() {
      try {
        const feed = await api.liveFeed(lastIdRef.current)
        if (cancelled) return
        setReachable(true)
        if (feed.samples.length > 0) {
          lastIdRef.current = feed.latest_id
          setSamples((prev) => [...feed.samples].reverse().concat(prev).slice(0, MAX_SAMPLES))
        }
      } catch {
        if (!cancelled) setReachable(false)
      } finally {
        if (!cancelled) timer = setTimeout(poll, POLL_MS)
      }
    }
    poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    if (follow && samples.length > 0) {
      setSelectedId(samples[0].id)
    }
  }, [follow, samples])

  const selected = samples.find((s) => s.id === selectedId) ?? null

  return (
    <>
      <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            2.4GHz live feed
          </h2>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={follow}
              onChange={(e) => setFollow(e.target.checked)}
            />
            follow latest
          </label>
        </div>

        {!reachable && (
          <p className="mb-3 text-xs text-rose-500">backend unreachable — retrying…</p>
        )}

        {samples.length === 0 ? (
          <div className="py-16 text-center text-sm text-slate-400">
            <p>No probe samples yet.</p>
            <p className="mx-auto mt-2 max-w-xs text-xs">
              Point a connected <code>hardware/esp32_rf_probe</code> board's{' '}
              <code>BACKEND_URL</code> at <code>/live/ingest</code> (see its README) — samples
              appear here as the board posts them.
            </p>
          </div>
        ) : (
          <ul className="flex-1 space-y-1 overflow-y-auto">
            {samples.map((s) => {
              const radio = (s.snapshot as MiniSnapshot).radio
              return (
                <li key={s.id}>
                  <button
                    onClick={() => {
                      setFollow(false)
                      setSelectedId(s.id)
                    }}
                    className={`w-full rounded-md px-3 py-2 text-left text-xs ${
                      s.id === selectedId
                        ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                        : 'hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span>ch{radio?.channel ?? '?'}</span>
                      <span className="font-mono opacity-70">{s.received_at}</span>
                    </div>
                    <div className="mt-0.5 opacity-80">
                      {s.diagnosis.cause_id ?? 'no cause asserted'} · {s.diagnosis.confidence}
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        {!selected ? (
          <p className="py-16 text-center text-sm text-slate-400">
            Select a sample to see its diagnosis.
          </p>
        ) : (
          <div className="space-y-8">
            <DiagnosisView result={selected.diagnosis} causeName={causeName} />
            <div className="border-t border-slate-200 pt-6 dark:border-slate-800">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Explanation
              </h3>
              <ExplanationPanel snapshot={selected.snapshot} diagnosis={selected.diagnosis} />
            </div>
          </div>
        )}
      </div>
    </>
  )
}
