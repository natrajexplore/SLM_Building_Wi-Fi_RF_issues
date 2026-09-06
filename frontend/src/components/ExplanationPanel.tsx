import { useState } from 'react'
import { ApiError, api } from '../api'
import type { RCAResult } from '../types'

// The ONLY temperature control in the app. Range fixed to the explanation
// band [0.7, 0.9] — the diagnosis path has no equivalent and must not get one.
const T_MIN = 0.7
const T_MAX = 0.9
const T_STEP = 0.05

export function ExplanationPanel({
  snapshot,
  diagnosis,
}: {
  snapshot: unknown
  diagnosis: RCAResult
}) {
  const [temperature, setTemperature] = useState(0.8)
  const [text, setText] = useState<string | null>(null)
  const [used, setUsed] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setLoading(true)
    setError(null)
    try {
      const res = await api.explain(snapshot, diagnosis, temperature)
      setText(res.explanation)
      setUsed(res.temperature_used)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-3 text-sm">
          <span className="text-slate-500">Explanation temperature</span>
          <input
            type="range"
            min={T_MIN}
            max={T_MAX}
            step={T_STEP}
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
            className="w-40"
          />
          <span className="w-10 font-mono">{temperature.toFixed(2)}</span>
        </label>
        <button
          onClick={run}
          disabled={loading}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {loading ? 'Explaining…' : text ? 'Re-explain' : 'Explain this'}
        </button>
      </div>

      <p className="text-xs text-slate-400">
        Diagnosis runs at a fixed low temperature; only this readability step is adjustable.
      </p>

      {error && (
        <div className="rounded-md bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-300">
          {error}
        </div>
      )}
      {text && (
        <div className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-200">
            {text}
          </p>
          {used !== null && (
            <p className="mt-2 text-xs text-slate-400">
              generated at temperature {used.toFixed(2)}
              {used !== temperature && ' (clamped to the explanation band)'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
