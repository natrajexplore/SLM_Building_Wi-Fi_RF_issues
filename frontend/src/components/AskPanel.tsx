import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import type { ChatMessage, ConversationSummary } from '../types'
import { CitationList } from './CitationList'

export function AskPanel() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [conversationsLoading, setConversationsLoading] = useState(false)
  const [conversationsError, setConversationsError] = useState<string | null>(null)

  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loadingThread, setLoadingThread] = useState(false)

  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  const bottomRef = useRef<HTMLDivElement>(null)
  // Replies can take 20-80s here, so a manual Refresh click and the
  // automatic post-send refresh can easily overlap; without this guard
  // whichever network response happens to land last wins, even if it was
  // the older of the two requests -- silently reverting the list to stale
  // data right after a genuinely fresh one arrived.
  const conversationsReqId = useRef(0)

  async function loadConversations() {
    const reqId = ++conversationsReqId.current
    setConversationsLoading(true)
    setConversationsError(null)
    try {
      const res = await api.conversations()
      if (reqId !== conversationsReqId.current) return // superseded by a newer request
      setConversations(res.items)
      if (res.store_error) setConversationsError(res.store_error)
    } catch (e) {
      if (reqId !== conversationsReqId.current) return
      setConversationsError(e instanceof ApiError ? e.message : String(e))
    } finally {
      if (reqId === conversationsReqId.current) setConversationsLoading(false)
    }
  }

  useEffect(() => {
    loadConversations()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  // Same reasoning as conversationsReqId: clicking between conversations
  // while a previous (slow) thread fetch is still in flight must not let
  // that older response overwrite the thread the user actually selected.
  const threadReqId = useRef(0)

  function startNewConversation() {
    threadReqId.current++ // invalidate any in-flight openConversation load
    setActiveId(null)
    setMessages([])
    setSendError(null)
  }

  async function openConversation(id: string) {
    const reqId = ++threadReqId.current
    setActiveId(id)
    setSendError(null)
    setLoadingThread(true)
    try {
      const res = await api.conversation(id)
      if (reqId !== threadReqId.current) return
      setMessages(res.messages)
    } catch (e) {
      if (reqId !== threadReqId.current) return
      setSendError(e instanceof ApiError ? e.message : String(e))
    } finally {
      if (reqId === threadReqId.current) setLoadingThread(false)
    }
  }

  async function send() {
    const text = input.trim()
    if (!text) return
    setSending(true)
    setSendError(null)
    // Optimistic bubble so the conversation feels responsive while the answer streams in.
    const optimisticUser: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content: text,
      citations: [],
      temperature_used: null,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimisticUser])
    setInput('')
    try {
      const res = await api.ask(text, activeId)
      setActiveId(res.conversation_id)
      setMessages((prev) => [
        ...prev,
        {
          id: res.message_id ?? `unsaved-${res.created_at}`,
          role: 'assistant',
          content: res.answer,
          citations: res.citations,
          temperature_used: res.temperature_used,
          created_at: res.created_at,
        },
      ])
      if (!res.stored) {
        setSendError(
          res.store_error
            ? `Answered, but not saved: ${res.store_error}`
            : 'Answered, but not saved.',
        )
      }
      loadConversations() // refresh sidebar: new/updated title, message count
    } catch (e) {
      setMessages((prev) => prev.filter((m) => m.id !== optimisticUser.id))
      setInput(text) // give the message back so it isn't lost
      setSendError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <>
      <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Conversations
          </h2>
          <button
            onClick={loadConversations}
            disabled={conversationsLoading}
            className="text-xs text-slate-400 hover:text-slate-600 disabled:opacity-50 dark:hover:text-slate-300"
          >
            {conversationsLoading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        <button
          onClick={startNewConversation}
          className="mb-3 rounded-md border border-dashed border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          + New conversation
        </button>
        {conversationsError && (
          <p className="mb-2 text-xs text-amber-600 dark:text-amber-400">
            Couldn't load conversations: {conversationsError}
          </p>
        )}
        {conversations.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">
            {conversationsLoading ? 'Loading…' : 'No conversations yet.'}
          </p>
        ) : (
          <ul className="flex-1 space-y-1 overflow-y-auto">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => openConversation(c.id)}
                  className={`w-full rounded-md px-3 py-2 text-left text-xs ${
                    c.id === activeId
                      ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                      : 'hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                >
                  <div className="truncate">{c.title}</div>
                  <div className="mt-0.5 opacity-70">
                    {c.message_count} message{c.message_count === 1 ? '' : 's'} ·{' '}
                    <span className="font-mono">{c.created_at}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <p className="mb-3 text-xs text-slate-500">
          Ask a free-text RF question — answered from the same regulatory corpus the diagnosis
          path cites. Follow-ups keep the conversation's context.
        </p>

        <div className="flex-1 space-y-3 overflow-y-auto">
          {loadingThread ? (
            <p className="py-16 text-center text-sm text-slate-400">Loading…</p>
          ) : messages.length === 0 ? (
            <p className="py-16 text-center text-sm text-slate-400">
              Start a conversation below.
            </p>
          ) : (
            messages.map((m) => (
              <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    m.role === 'user'
                      ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                      : 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200'
                  }`}
                >
                  <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                  {m.role === 'assistant' && m.citations.length > 0 && (
                    <details className="mt-2 text-xs opacity-90">
                      <summary className="cursor-pointer select-none">
                        {m.citations.length} source{m.citations.length === 1 ? '' : 's'}
                      </summary>
                      <div className="mt-2">
                        <CitationList citations={m.citations} />
                      </div>
                    </details>
                  )}
                </div>
              </div>
            ))
          )}
          {sending && (
            <div className="flex justify-start">
              <div className="max-w-[85%] rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-400 dark:bg-slate-800">
                Thinking…
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {sendError && (
          <div className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-300">
            {sendError}
          </div>
        )}

        <div className="mt-3 flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send()
            }}
            placeholder="e.g. what's the LPI EIRP limit for 6 GHz indoor?"
            rows={2}
            className="flex-1 rounded-md border border-slate-200 bg-transparent p-2 text-sm dark:border-slate-700"
          />
          <button
            onClick={send}
            disabled={sending || !input.trim()}
            className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            Send
          </button>
        </div>
        <span className="mt-1 text-xs text-slate-400">Ctrl/Cmd+Enter to send</span>
      </div>
    </>
  )
}
