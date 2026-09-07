import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from './api'
import { AskPanel } from './components/AskPanel'
import { DiagnosisView } from './components/DiagnosisView'
import { ExplanationPanel } from './components/ExplanationPanel'
import { LiveTestPanel } from './components/LiveTestPanel'
import { SnapshotInput } from './components/SnapshotInput'
import type { HealthInfo, RCAResult, TaxonomyCause } from './types'

type Mode = 'snapshot' | 'live' | 'ask'

export default function App() {
  const [mode, setMode] = useState<Mode>('ask')
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [causes, setCauses] = useState<TaxonomyCause[]>([])
  const [snapshot, setSnapshot] = useState<unknown>(null)
  const [result, setResult] = useState<RCAResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    api.taxonomy().then((t) => setCauses(t.causes)).catch(() => {})
  }, [])

  const causeName = useMemo(() => {
    const m = new Map(causes.map((c) => [c.id, c.name]))
    return (id: string) => m.get(id) ?? id
  }, [causes])

  async function diagnose(snap: unknown, retrieve: boolean) {
    setLoading(true)
    setError(null)
    setResult(null)
    setSnapshot(snap)
    try {
      setResult(await api.diagnose(snap, retrieve))
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="border-b border-slate-200 px-6 py-3 dark:border-slate-800">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <h1 className="text-lg font-semibold">RF Root-Cause SLM</h1>
          <HealthPill health={health} />
        </div>
      </header>

      <nav className="border-b border-slate-200 px-6 dark:border-slate-800">
        <div className="mx-auto flex max-w-6xl gap-1 py-2">
          {(
            [
              ['ask', 'Submit / Ask'],
              ['live', '2.4GHz Live Test'],
              ['snapshot', 'Snapshot'],
            ] as const
          ).map(([m, label]) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                mode === m
                  ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      <main className="mx-auto grid max-w-6xl gap-6 p-6 lg:grid-cols-2">
        {mode === 'snapshot' ? (
          <>
            <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <SnapshotInput onDiagnose={diagnose} loading={loading} />
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              {error && (
                <div className="rounded-md bg-rose-50 p-4 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-300">
                  <p className="font-medium">Diagnosis rejected</p>
                  <p className="mt-1">{error}</p>
                  <p className="mt-2 text-xs text-rose-500">
                    A 422 means the model's output failed the taxonomy contract (invented cause,
                    ungrounded evidence, or an unsupported assertion). This is the guard working,
                    not a UI bug.
                  </p>
                </div>
              )}
              {!error && !result && (
                <p className="py-16 text-center text-sm text-slate-400">
                  Submit a snapshot to see the diagnosis.
                </p>
              )}
              {result && (
                <div className="space-y-8">
                  <DiagnosisView result={result} causeName={causeName} />
                  <div className="border-t border-slate-200 pt-6 dark:border-slate-800">
                    <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Explanation
                    </h3>
                    <ExplanationPanel snapshot={snapshot} diagnosis={result} />
                  </div>
                </div>
              )}
            </div>
          </>
        ) : mode === 'live' ? (
          <LiveTestPanel causeName={causeName} />
        ) : (
          <AskPanel />
        )}
      </main>
    </div>
  )
}

function HealthPill({ health }: { health: HealthInfo | null }) {
  if (!health) {
    return <span className="text-xs text-rose-500">backend unreachable</span>
  }
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500">
      <span
        className={health.backend_ready ? '' : 'text-amber-600'}
        title={health.backend_error ?? undefined}
      >
        {health.model_backend}
        {!health.backend_ready && ' (not ready)'}
      </span>
      <span>·</span>
      <span>diagnose T={health.diagnose_temperature}</span>
      <span>·</span>
      <span>
        explain T {health.explain_temperature_band[0]}–{health.explain_temperature_band[1]}
      </span>
      {health.rag_index && (
        <>
          <span>·</span>
          <span title={JSON.stringify(health.rag_index.review_status)}>
            RAG {health.rag_index.chunks} chunks
          </span>
        </>
      )}
      <span>·</span>
      <span className={health.query_store_connected ? '' : 'text-amber-600'}>
        queries {health.query_store_connected ? 'saving' : 'not saving'}
      </span>
    </div>
  )
}
