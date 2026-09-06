import { useState } from 'react'
import { EXAMPLE_SNAPSHOT } from '../example'

export function SnapshotInput({
  onDiagnose,
  loading,
}: {
  onDiagnose: (snapshot: unknown, retrieve: boolean) => void
  loading: boolean
}) {
  const [text, setText] = useState(JSON.stringify(EXAMPLE_SNAPSHOT, null, 2))
  const [retrieve, setRetrieve] = useState(true)
  const [jsonError, setJsonError] = useState<string | null>(null)

  function submit() {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'invalid JSON')
      return
    }
    setJsonError(null)
    onDiagnose(parsed, retrieve)
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Canonical RF snapshot
        </h2>
        <button
          onClick={() => setText(JSON.stringify(EXAMPLE_SNAPSHOT, null, 2))}
          className="text-xs text-sky-600 hover:underline dark:text-sky-400"
        >
          reset to example
        </button>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        className="min-h-[420px] flex-1 resize-none rounded-md border border-slate-300 bg-white p-3 font-mono text-xs leading-relaxed dark:border-slate-700 dark:bg-slate-900"
      />
      {jsonError && <p className="text-xs text-rose-600">{jsonError}</p>}
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={retrieve} onChange={(e) => setRetrieve(e.target.checked)} />
          retrieve regulatory context
        </label>
        <button
          onClick={submit}
          disabled={loading}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {loading ? 'Diagnosing…' : 'Diagnose'}
        </button>
      </div>
    </div>
  )
}
