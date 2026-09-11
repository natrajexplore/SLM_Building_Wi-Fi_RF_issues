import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { AskPanel } from './components/AskPanel'
import { AntennaIcon, BookIcon, ChatIcon, WifiIcon } from './components/Icons'
import { LiveTestPanel } from './components/LiveTestPanel'
import { WirelessTopicsPanel } from './components/WirelessTopicsPanel'
import type { HealthInfo, TaxonomyCause } from './types'

type Mode = 'ask' | 'live' | 'topics'

const TABS = [
  { mode: 'ask' as const, label: 'Submit / Ask', icon: ChatIcon },
  { mode: 'live' as const, label: '2.4GHz Live Test', icon: AntennaIcon },
  { mode: 'topics' as const, label: 'Wireless Topics', icon: BookIcon },
]

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
    <div className="min-h-screen bg-gradient-to-br from-sky-50 via-white to-violet-50 text-slate-900 dark:from-slate-950 dark:via-slate-950 dark:to-indigo-950 dark:text-slate-100">
      <header className="bg-gradient-to-r from-sky-600 via-cyan-600 to-violet-600 px-6 py-4 text-white shadow-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="rounded-lg bg-white/15 p-1.5 backdrop-blur-sm">
              <WifiIcon className="h-5 w-5" />
            </span>
            <h1 className="text-lg font-semibold tracking-tight">Multi use Wi-Fi Tool</h1>
          </div>
          <HealthPill health={health} />
        </div>
      </header>

      <nav className="border-b border-slate-200/70 bg-white/60 px-6 backdrop-blur-sm dark:border-slate-800/70 dark:bg-slate-900/40">
        <div className="mx-auto flex max-w-6xl gap-1.5 py-2">
          {TABS.map(({ mode: m, label, icon: Icon }) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === m
                  ? 'bg-gradient-to-r from-sky-600 to-violet-600 text-white shadow-sm'
                  : 'text-slate-500 hover:bg-slate-900/5 dark:text-slate-400 dark:hover:bg-white/5'
              }`}
            >
              <Icon className="h-4 w-4" />
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
    return (
      <span className="rounded-full bg-rose-500/20 px-2.5 py-1 text-xs font-medium text-rose-50">
        backend unreachable
      </span>
    )
  }
  return (
    <div className="flex items-center gap-2 rounded-full bg-white/15 px-3 py-1.5 text-xs text-sky-50 backdrop-blur-sm">
      <span
        className={health.backend_ready ? '' : 'text-amber-200'}
        title={health.backend_error ?? undefined}
      >
        {health.model_backend}
        {!health.backend_ready && ' (not ready)'}
      </span>
      <span className="opacity-50">·</span>
      <span>diagnose T={health.diagnose_temperature}</span>
      <span className="opacity-50">·</span>
      <span>
        explain T {health.explain_temperature_band[0]}–{health.explain_temperature_band[1]}
      </span>
      {health.rag_index && (
        <>
          <span className="opacity-50">·</span>
          <span title={JSON.stringify(health.rag_index.review_status)}>
            RAG {health.rag_index.chunks} chunks
          </span>
        </>
      )}
      <span className="opacity-50">·</span>
      <span className={health.query_store_connected ? '' : 'text-amber-200'}>
        queries {health.query_store_connected ? 'saving' : 'not saving'}
      </span>
    </div>
  )
}
