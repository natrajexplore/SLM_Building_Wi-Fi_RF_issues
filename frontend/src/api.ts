import type {
  AskHistoryResponse,
  AskResponse,
  ExplainResponse,
  HealthInfo,
  LiveFeedResponse,
  RCAResult,
  TaxonomyCause,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return handle<T>(res)
}

async function handle<T>(res: Response): Promise<T> {
  const payload = await res.json().catch(() => null)
  if (!res.ok) {
    const detail =
      payload && typeof payload.detail === 'string'
        ? payload.detail
        : payload && Array.isArray(payload.detail)
          ? payload.detail.map((d: { msg?: string }) => d.msg).join('; ')
          : `HTTP ${res.status}`
    throw new ApiError(res.status, detail)
  }
  return payload as T
}

export const api = {
  health: () => fetch('/health').then((r) => handle<HealthInfo>(r)),
  taxonomy: () => fetch('/taxonomy').then((r) => handle<{ causes: TaxonomyCause[] }>(r)),
  diagnose: (snapshot: unknown, retrieve: boolean) =>
    post<RCAResult>('/diagnose', { snapshot, retrieve }),
  explain: (snapshot: unknown, diagnosis: RCAResult, temperature: number | null) =>
    post<ExplainResponse>('/explain', { snapshot, diagnosis, temperature }),
  liveFeed: (sinceId: number) =>
    fetch(`/live/feed?since=${sinceId}`, { cache: 'no-store' }).then((r) =>
      handle<LiveFeedResponse>(r),
    ),
  // No temperature param — the explanation band is the app's only temperature
  // control (CLAUDE.md hard decision #3); /ask always runs at its default.
  ask: (query: string) => post<AskResponse>('/ask', { query }),
  // no-store: the Refresh button re-requests this exact URL on demand, and a
  // browser-cached response would make "Refresh" silently do nothing.
  askHistory: (limit = 50) =>
    fetch(`/ask/history?limit=${limit}`, { cache: 'no-store' }).then((r) =>
      handle<AskHistoryResponse>(r),
    ),
}
