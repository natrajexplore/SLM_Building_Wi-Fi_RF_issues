import type { ExplainResponse, HealthInfo, RCAResult, TaxonomyCause } from './types'

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
}
