import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
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

// What hardware/sample_capture.jsonl's 6 lines each demonstrate — kept in
// sync by hand with the comments at the top of that file. RF-24-004 (legacy
// rates) and RF-24-005 (cell overlap) are deliberately absent: an ESP32
// probe cannot populate the fields their required_evidence gates on
// (clients.legacy_client_count, radio.tx_power_dbm), so no demo line can
// make them assertion-eligible — that's the adapter correctly declining to
// claim evidence it doesn't have, not a gap in the demo set.
const DEMO_CASES: { cause: string | null; note: string }[] = [
  { cause: null, note: 'healthy channel — low utilization, low retry, nominal noise floor' },
  { cause: 'RF-24-001', note: '4 neighbours crowding one channel at 87% utilization' },
  { cause: 'RF-24-002', note: 'strong neighbours 3-4 channels away driving retries to 30%' },
  { cause: 'RF-24-003', note: 'elevated noise floor with a dense BLE population nearby' },
  { cause: 'RF-24-006', note: '28 active clients saturating one lightly-shared channel' },
  {
    cause: 'RF-24-001',
    note: 'co-channel congestion AND client density together — deliberately ambiguous, exercises ranked_alternatives',
  },
]

export function LiveTestPanel({ causeName }: { causeName: (id: string) => string }) {
  const [samples, setSamples] = useState<LiveSample[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [follow, setFollow] = useState(true)
  const [reachable, setReachable] = useState(true)
  const [demoLoading, setDemoLoading] = useState(false)
  const [demoError, setDemoError] = useState<string | null>(null)
  const lastIdRef = useRef(0)

  function mergeSamples(newSamples: LiveSample[], latestId: number) {
    if (newSamples.length === 0) return
    lastIdRef.current = latestId
    setSamples((prev) => [...newSamples].reverse().concat(prev).slice(0, MAX_SAMPLES))
  }

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    async function poll() {
      try {
        const feed = await api.liveFeed(lastIdRef.current)
        if (cancelled) return
        setReachable(true)
        mergeSamples(feed.samples, feed.latest_id)
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

  async function loadDemo() {
    setDemoLoading(true)
    setDemoError(null)
    try {
      const feed = await api.liveDemo()
      mergeSamples(feed.samples, feed.latest_id)
    } catch (e) {
      setDemoError(e instanceof ApiError ? e.message : 'could not reach the backend')
    } finally {
      setDemoLoading(false)
    }
  }

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

        <details className="mb-3 rounded-md border border-slate-200 bg-slate-50 text-xs dark:border-slate-800 dark:bg-slate-950">
          <summary className="cursor-pointer select-none px-3 py-2 font-medium text-slate-600 dark:text-slate-300">
            How this tab works, with or without hardware
          </summary>
          <div className="space-y-3 border-t border-slate-200 px-3 py-3 text-slate-600 dark:border-slate-800 dark:text-slate-400">
            <div>
              <p className="font-semibold text-slate-700 dark:text-slate-300">With hardware</p>
              <p className="mt-1">
                Flash a <code>hardware/esp32_rf_probe</code> board (2.4 GHz only, no spectrum
                hardware) and set its <code>config.h</code> <code>BACKEND_URL</code> to{' '}
                <code>http://&lt;this-backend&gt;:8000/live/ingest</code>. Every sample it posts is
                normalized, diagnosed at the same fixed low temperature as{' '}
                <code>/diagnose</code>, and appended below — tagged <code>probe</code>.
              </p>
            </div>
            <div>
              <p className="font-semibold text-slate-700 dark:text-slate-300">Without hardware</p>
              <p className="mt-1">
                Click <span className="font-medium">Load demo samples</span> below. It replays 6
                real recorded probe captures (<code>hardware/sample_capture.jsonl</code>) through
                the identical adapter → diagnose → buffer path a real board would use — tagged{' '}
                <code>demo</code> so they're never mistaken for live hardware. The same file works
                from a terminal too:{' '}
                <code>python hardware/read_probe.py --replay hardware/sample_capture.jsonl --live</code>.
              </p>
            </div>
            <div>
              <p className="font-semibold text-slate-700 dark:text-slate-300">
                Behaviour worth knowing
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                <li>This list polls <code>/live/feed</code> every 3s — not a push stream.</li>
                <li>
                  The buffer is in-memory, single-process, last 200 samples — it resets whenever
                  the backend restarts. Nothing here is persisted.
                </li>
                <li>Diagnosis always runs at the fixed low temperature; there is no live-tab temperature control.</li>
              </ul>
            </div>
            <div>
              <p className="font-semibold text-slate-700 dark:text-slate-300">
                Test cases the demo set covers
              </p>
              <p className="mt-1">
                Each demo line is engineered so only the named cause's evidence requirements are
                met — verified against the taxonomy's predicates, not hand-picked:
              </p>
              <ol className="mt-1 list-decimal space-y-0.5 pl-4">
                {DEMO_CASES.map((c, i) => (
                  <li key={i}>
                    <span className="font-medium text-slate-700 dark:text-slate-300">
                      {c.cause ? causeName(c.cause) : 'No cause asserted (data gap)'}
                    </span>{' '}
                    — {c.note}
                  </li>
                ))}
              </ol>
              <p className="mt-1">
                Legacy-rate and cell-overlap causes (RF-24-004/005) can't be demonstrated from
                ESP32 evidence alone — it has no way to measure per-client legacy rate counts or
                TX power, so those show up as data gaps instead, which is correct behaviour, not a
                missing test case.
              </p>
            </div>
          </div>
        </details>

        <button
          onClick={loadDemo}
          disabled={demoLoading}
          className="mb-3 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {demoLoading ? 'Loading demo samples…' : 'Load demo samples (no hardware needed)'}
        </button>
        {demoError && <p className="mb-3 text-xs text-rose-500">{demoError}</p>}

        {samples.length === 0 ? (
          <div className="py-10 text-center text-sm text-slate-400">
            <p>No probe samples yet.</p>
            <p className="mx-auto mt-2 max-w-xs text-xs">
              Point a connected <code>hardware/esp32_rf_probe</code> board's{' '}
              <code>BACKEND_URL</code> at <code>/live/ingest</code>, or click{' '}
              <span className="font-medium">Load demo samples</span> above.
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
                      <span className="flex items-center gap-1.5">
                        ch{radio?.channel ?? '?'}
                        {s.source === 'demo' && (
                          <span className="rounded bg-amber-200 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-900 dark:text-amber-200">
                            demo
                          </span>
                        )}
                      </span>
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
