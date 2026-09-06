import type { RCAResult } from '../types'
import { CitationList } from './CitationList'
import { ConfidenceBadge } from './ConfidenceBadge'
import { EvidenceChain } from './EvidenceChain'
import { Section } from './Section'

export function DiagnosisView({
  result,
  causeName,
}: {
  result: RCAResult
  causeName: (id: string) => string
}) {
  const abstained = result.cause_id === null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {abstained ? (
          <span className="rounded-md bg-slate-200 px-3 py-1 text-lg font-semibold dark:bg-slate-700">
            No cause asserted — data gap
          </span>
        ) : (
          <span className="rounded-md bg-slate-900 px-3 py-1 text-lg font-semibold text-white dark:bg-slate-100 dark:text-slate-900">
            {result.cause_id} · {causeName(result.cause_id!)}
          </span>
        )}
        <ConfidenceBadge value={result.confidence} />
        {result.affected_bands.map((b) => (
          <span key={b} className="rounded bg-sky-100 px-2 py-0.5 text-xs text-sky-800 dark:bg-sky-900 dark:text-sky-200">
            {b}
          </span>
        ))}
      </div>

      <Section title="Evidence chain">
        <EvidenceChain items={result.evidence} />
      </Section>

      {result.ranked_alternatives.length > 0 && (
        <Section title="Also plausible">
          <ul className="space-y-1 text-sm">
            {result.ranked_alternatives.map((a) => (
              <li key={a.cause_id}>
                <span className="font-mono">{a.cause_id}</span> · {causeName(a.cause_id)}{' '}
                <span className="text-slate-400">({a.confidence})</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Remediation intent">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-300">
          {result.remediation.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </Section>

      {result.data_gaps.length > 0 && (
        <Section title="Data gaps (would raise confidence)">
          <div className="flex flex-wrap gap-1.5">
            {result.data_gaps.map((g) => (
              <code key={g} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-slate-800">
                {g}
              </code>
            ))}
          </div>
        </Section>
      )}

      <Section title="Regulatory context (retrieved)">
        <CitationList citations={result.citations} />
      </Section>
    </div>
  )
}
