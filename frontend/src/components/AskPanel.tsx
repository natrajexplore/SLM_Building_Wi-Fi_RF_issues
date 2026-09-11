import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import type { ChatMessage, ConversationSummary } from '../types'
import { CitationList } from './CitationList'
import { BrainIcon, PlusIcon, RefreshIcon, SendIcon, SparkleIcon, TrashIcon } from './Icons'

// Animated stand-in for a static "Thinking…" label — a pulsing brain with an
// expanding ring plus staggered bouncing dots, so waiting on the model (which
// can take 20-80s+ on this CPU-only backend) feels alive rather than frozen.
function ThinkingIndicator() {
  return (
    <span className="flex items-center gap-2 text-slate-400">
      <span className="relative flex h-5 w-5 shrink-0 items-center justify-center">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-40" />
        <BrainIcon className="relative h-4 w-4 animate-pulse text-violet-500" />
      </span>
      <span className="flex items-center gap-0.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </span>
    </span>
  )
}

export function AskPanel() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [conversationsLoading, setConversationsLoading] = useState(false)
  const [conversationsError, setConversationsError] = useState<string | null>(null)
  const [clearing, setClearing] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loadingThread, setLoadingThread] = useState(false)

  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  // Id of the assistant bubble currently receiving stream chunks, so the
  // message list can show a "Thinking…" placeholder until the first token
  // arrives. Read during render, so a ref (not state) is enough.
  const pendingAssistantIdRef = useRef<string | null>(null)

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

  // Identifies the thread currently shown in the right-hand panel. send()
  // and openConversation() both take 20-80s to resolve on this deployment,
  // so a stale one finishing *after* the user has since clicked "New
  // conversation" or opened a different thread must not be allowed to leak
  // its answer into whatever is on screen now — every async continuation
  // that would touch activeId/messages/sending checks this first.
  const sessionRef = useRef(0)

  function startNewConversation() {
    sessionRef.current++
    setActiveId(null)
    setMessages([])
    setSendError(null)
    setInput('')
    setSending(false) // a still-running send from the old thread no longer blocks this one
  }

  async function openConversation(id: string) {
    const session = ++sessionRef.current
    setActiveId(id)
    setSendError(null)
    setInput('')
    setSending(false)
    setLoadingThread(true)
    try {
      const res = await api.conversation(id)
      if (session !== sessionRef.current) return // superseded before this resolved
      setMessages(res.messages)
    } catch (e) {
      if (session !== sessionRef.current) return
      setSendError(e instanceof ApiError ? e.message : String(e))
    } finally {
      if (session === sessionRef.current) setLoadingThread(false)
    }
  }

  function refreshAndReset() {
    startNewConversation()
    loadConversations()
  }

  async function clearAllConversations() {
    if (conversations.length === 0) return
    const ok = window.confirm(
      `Delete all ${conversations.length} saved conversation${
        conversations.length === 1 ? '' : 's'
      }? This cannot be undone.`,
    )
    if (!ok) return
    setClearing(true)
    setClearError(null)
    try {
      await api.clearConversations()
      startNewConversation()
      setConversations([])
    } catch (e) {
      setClearError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setClearing(false)
    }
  }

  async function send() {
    const text = input.trim()
    if (!text) return
    const session = sessionRef.current // send() continues the current session, doesn't start one
    setSending(true)
    setSendError(null)
    // Optimistic user bubble, plus an empty assistant bubble that fills in
    // as the answer streams — so the conversation feels responsive
    // immediately instead of sitting on a spinner for the full 20-80s+ reply.
    const optimisticUser: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content: text,
      citations: [],
      temperature_used: null,
      created_at: new Date().toISOString(),
    }
    const pendingAssistantId = `pending-assistant-${Date.now()}`
    pendingAssistantIdRef.current = pendingAssistantId
    const pendingAssistant: ChatMessage = {
      id: pendingAssistantId,
      role: 'assistant',
      content: '',
      citations: [],
      temperature_used: null,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimisticUser, pendingAssistant])
    setInput('')

    let streamed = ''
    await api.askStream(text, activeId, {
      onChunk: (piece) => {
        if (session !== sessionRef.current) return
        streamed += piece
        setMessages((prev) =>
          prev.map((m) => (m.id === pendingAssistantId ? { ...m, content: streamed } : m)),
        )
      },
      onDone: (final) => {
        pendingAssistantIdRef.current = null
        // The reply is safely saved server-side either way; if the user has
        // since moved on to a new/different conversation, just don't show it
        // here — loadConversations() below still surfaces it in the sidebar.
        if (session === sessionRef.current) {
          setActiveId(final.conversation_id)
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingAssistantId
                ? {
                    id: final.message_id ?? pendingAssistantId,
                    role: 'assistant',
                    content: final.answer,
                    citations: final.citations,
                    temperature_used: final.temperature_used,
                    created_at: final.created_at,
                  }
                : m,
            ),
          )
          if (!final.stored) {
            setSendError(
              final.store_error
                ? `Answered, but not saved: ${final.store_error}`
                : 'Answered, but not saved.',
            )
          }
        }
        loadConversations() // refresh sidebar: new/updated title, message count
        if (session === sessionRef.current) setSending(false)
      },
      onError: (message) => {
        pendingAssistantIdRef.current = null
        if (session === sessionRef.current) {
          setMessages((prev) =>
            prev.filter((m) => m.id !== optimisticUser.id && m.id !== pendingAssistantId),
          )
          setInput(text) // give the message back so it isn't lost
          setSendError(message)
          setSending(false)
        }
      },
    })
  }

  return (
    <>
      <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Conversations
          </h2>
          <div className="flex items-center gap-3">
            <button
              onClick={refreshAndReset}
              disabled={conversationsLoading}
              className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-700 disabled:opacity-50 dark:text-sky-400 dark:hover:text-sky-300"
            >
              <RefreshIcon className={`h-3.5 w-3.5 ${conversationsLoading ? 'animate-spin' : ''}`} />
              {conversationsLoading ? 'Refreshing…' : 'Refresh'}
            </button>
            <button
              onClick={clearAllConversations}
              disabled={clearing || conversations.length === 0}
              className="flex items-center gap-1 text-xs text-rose-500 hover:text-rose-700 disabled:opacity-50 dark:text-rose-400 dark:hover:text-rose-300"
            >
              <TrashIcon className="h-3.5 w-3.5" />
              {clearing ? 'Clearing…' : 'Clear all'}
            </button>
          </div>
        </div>
        <button
          onClick={startNewConversation}
          className="mb-3 flex items-center justify-center gap-1.5 rounded-md border border-dashed border-violet-300 px-3 py-1.5 text-sm font-medium text-violet-600 hover:bg-violet-50 dark:border-violet-700 dark:text-violet-300 dark:hover:bg-violet-950/40"
        >
          <PlusIcon className="h-4 w-4" />
          New conversation
        </button>
        {conversationsError && (
          <p className="mb-2 text-xs text-amber-600 dark:text-amber-400">
            Couldn't load conversations: {conversationsError}
          </p>
        )}
        {clearError && (
          <p className="mb-2 text-xs text-rose-600 dark:text-rose-400">
            Couldn't clear conversations: {clearError}
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
                      ? 'bg-gradient-to-r from-sky-600 to-violet-600 text-white shadow-sm'
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
            messages.map((m) => {
              const isPendingAndEmpty = m.id === pendingAssistantIdRef.current && !m.content
              return (
              <div
                key={m.id}
                className={`flex items-end gap-2 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {m.role === 'assistant' && (
                  <span
                    className={`mb-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white ${
                      isPendingAndEmpty
                        ? 'bg-gradient-to-br from-violet-500 to-fuchsia-500'
                        : 'bg-gradient-to-br from-cyan-500 to-violet-500'
                    }`}
                  >
                    {isPendingAndEmpty ? (
                      <BrainIcon className="h-3.5 w-3.5 animate-pulse" />
                    ) : (
                      <SparkleIcon className="h-3.5 w-3.5" />
                    )}
                  </span>
                )}
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    m.role === 'user'
                      ? 'bg-gradient-to-br from-sky-600 to-violet-600 text-white shadow-sm'
                      : 'border border-cyan-100 bg-cyan-50/70 text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
                  }`}
                >
                  <p className="whitespace-pre-wrap leading-relaxed">
                    {m.content || (isPendingAndEmpty ? <ThinkingIndicator /> : '')}
                  </p>
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
              )
            })
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
            className="flex-1 rounded-md border border-slate-200 bg-transparent p-2 text-sm focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-400 dark:border-slate-700"
          />
          <button
            onClick={send}
            disabled={sending || !input.trim()}
            className="flex items-center gap-1.5 rounded-md bg-gradient-to-r from-sky-600 to-violet-600 px-3 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-50"
          >
            <SendIcon className="h-4 w-4" />
            Send
          </button>
        </div>
        <span className="mt-1 text-xs text-slate-400">Ctrl/Cmd+Enter to send</span>
      </div>
    </>
  )
}
