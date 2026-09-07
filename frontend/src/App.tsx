import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { AskPanel } from './components/AskPanel'
import { LiveTestPanel } from './components/LiveTestPanel'
import { WirelessTopicsPanel } from './components/WirelessTopicsPanel'
import type { HealthInfo, TaxonomyCause } from './types'

type Mode = 'ask' | 'live' | 'topics'

export default function App() {
  const [mode, setMode] = useState<Mode>('ask')
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [causes, setCauses] = useState<TaxonomyCause[]>([])

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    api.taxonomy().then((t) => setCauses(t.causes)).catch(() => {})
  }, [])

  const causeName = useMemo(() => {
    const m = new Map(causes.map((c) => [c.id, c.name]))
    return (id: string) => m.get(id) ?? id
  }, [causes])

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
              ['topics', 'Wireless Topics'],
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
        {mode === 'live' ? (
          <LiveTestPanel causeName={causeName} />
        ) : mode === 'topics' ? (
          <WirelessTopicsPanel causes={causes} />
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
