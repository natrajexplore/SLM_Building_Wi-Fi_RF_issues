import type {
  AskResponse,
  ConversationDetailResponse,
  ConversationListResponse,
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

export interface AskStreamDone {
  conversation_id: string | null
  message_id: string | null
  answer: string
  citations: import('./types').Citation[]
  temperature_used: number
  created_at: string
  stored: boolean
  store_error: string | null
}

export interface AskStreamHandlers {
  onChunk: (text: string) => void
  onDone: (final: AskStreamDone) => void
  onError: (message: string) => void
}

function parseSseEvent(raw: string): { event: string; data: unknown } | null {
  let event = 'message'
  let dataLine = ''
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLine += line.slice(5).trim()
  }
  if (!dataLine) return null
  try {
    return { event, data: JSON.parse(dataLine) }
  } catch {
    return null
  }
}

// EventSource can't send a POST body, so this reads the SSE stream by hand:
// buffer decoded text, split on the blank-line frame terminator, and parse
// each `event:`/`data:` pair as it completes.
async function askStream(
  message: string,
  conversationId: string | null,
  handlers: AskStreamHandlers,
): Promise<void> {
  let res: Response
  try {
    res = await fetch('/ask/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    })
  } catch (e) {
    handlers.onError(e instanceof Error ? e.message : String(e))
    return
  }
  if (!res.ok || !res.body) {
    const payload = await res.json().catch(() => null)
    const detail =
      payload && typeof payload.detail === 'string' ? payload.detail : `HTTP ${res.status}`
    handlers.onError(detail)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const parsed = parseSseEvent(raw)
      if (!parsed) continue
      if (parsed.event === 'chunk') handlers.onChunk((parsed.data as { text: string }).text)
      else if (parsed.event === 'done') handlers.onDone(parsed.data as AskStreamDone)
      else if (parsed.event === 'error') handlers.onError((parsed.data as { message: string }).message)
    }
  }
}

export const api = {
  health: () => fetch('/health').then((r) => handle<HealthInfo>(r)),
  taxonomy: () => fetch('/taxonomy').then((r) => handle<{ causes: TaxonomyCause[] }>(r)),
  explain: (snapshot: unknown, diagnosis: RCAResult, temperature: number | null) =>
    post<ExplainResponse>('/explain', { snapshot, diagnosis, temperature }),
  liveFeed: (sinceId: number) =>
    fetch(`/live/feed?since=${sinceId}`, { cache: 'no-store' }).then((r) =>
      handle<LiveFeedResponse>(r),
    ),
  liveDemo: () => post<LiveFeedResponse>('/live/demo', {}),
  // No temperature param — the explanation band is the app's only temperature
  // control (CLAUDE.md hard decision #3); /ask always runs at its default.
  ask: (message: string, conversationId: string | null) =>
    post<AskResponse>('/ask', { message, conversation_id: conversationId }),
  askStream,
  // no-store: the Refresh button re-requests this exact URL on demand, and a
  // browser-cached response would make "Refresh" silently do nothing.
  conversations: (limit = 50) =>
    fetch(`/ask/conversations?limit=${limit}`, { cache: 'no-store' }).then((r) =>
      handle<ConversationListResponse>(r),
    ),
  conversation: (id: string) =>
    fetch(`/ask/conversations/${id}`, { cache: 'no-store' }).then((r) =>
      handle<ConversationDetailResponse>(r),
    ),
  clearConversations: () =>
    fetch('/ask/conversations', { method: 'DELETE' }).then((r) =>
      handle<{ cleared: boolean }>(r),
    ),
}
