import { useState } from 'react'
import { ApiError, api } from '../api'
import type { AskResponse } from '../types'
import { CitationList } from './CitationList'

const MAX_HISTORY = 50

export function AskPanel() {
  const [query, setQuery] = useState('')
  const [history, setHistory] = useState<AskResponse[]>([]) // this session only
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function keyOf(a: AskResponse, i: number): string {
    return a.id ?? `unsaved-${a.created_at}-${i}`
  }

  async function submit() {
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.ask(q)
      setHistory((prev) => [res, ...prev].slice(0, MAX_HISTORY))
      setSelectedId(keyOf(res, 0)) // becomes index 0 after the prepend above
      setQuery('')
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setLoading(false)
    }
  }

  const selected = history.find((a, i) => keyOf(a, i) === selectedId) ?? history[0] ?? null

  return (
    <>
      <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Submit / Ask
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          Ask a free-text RF question — it's answered from the same regulatory corpus the
          diagnosis path cites, and saved for later review.
        </p>

        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
          }}
          placeholder="e.g. what's the LPI EIRP limit for 6 GHz indoor?"
          rows={4}
          className="w-full rounded-md border border-slate-200 bg-transparent p-2 text-sm dark:border-slate-700"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-xs text-slate-400">Ctrl/Cmd+Enter to submit</span>
          <button
            onClick={submit}
            disabled={loading || !query.trim()}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {loading ? 'Asking…' : 'Submit'}
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-300">
            {error}
          </div>
        )}

        <h3 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500">
          This session
        </h3>
        {history.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">Nothing submitted yet.</p>
        ) : (
          <ul className="flex-1 space-y-1 overflow-y-auto">
            {history.map((a, i) => {
              const key = keyOf(a, i)
              return (
                <li key={key}>
                  <button
                    onClick={() => setSelectedId(key)}
                    className={`w-full rounded-md px-3 py-2 text-left text-xs ${
                      key === selectedId
                        ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                        : 'hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate">{a.query}</span>
                      {!a.stored && (
                        <span
                          className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-900 dark:text-amber-200"
                          title={a.store_error ?? undefined}
                        >
                          not saved
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 font-mono opacity-70">{a.created_at}</div>
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
            Submit a question to see the answer.
          </p>
        ) : (
          <div className="space-y-6">
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Question
              </h3>
              <p className="text-sm text-slate-800 dark:text-slate-200">{selected.query}</p>
            </div>
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Answer
              </h3>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-200">
                {selected.answer}
              </p>
              <p className="mt-2 text-xs text-slate-400">
                generated at temperature {selected.temperature_used.toFixed(2)}
                {selected.stored ? ' · saved' : ' · not saved'}
              </p>
              {!selected.stored && selected.store_error && (
                <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                  {selected.store_error}
                </p>
              )}
            </div>
            <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Citations
              </h3>
              <CitationList citations={selected.citations} />
            </div>
          </div>
        )}
      </div>
    </>
  )
}
