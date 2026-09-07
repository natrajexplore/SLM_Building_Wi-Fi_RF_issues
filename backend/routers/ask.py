"""POST /ask — free-text RF chat -> grounded answer, persisted as a conversation.

Unlike /diagnose (a canonical snapshot -> structured cause) and /explain (an
already-decided diagnosis -> prose), /ask takes an open, multi-turn
conversation with no snapshot at all — "what's the LPI EIRP limit for 6 GHz
indoor?", then a follow-up "and for outdoor?". Each message retrieves
regulatory context via the same RAG index (grounded on the latest message
only, not the whole thread), composes an answer at the explanation-band
temperature (open-ended prose, not a low-temperature structured assertion —
CLAUDE.md hard decision #3) with prior turns as context, and persists both
the user message and the assistant's reply via the QueryStore seam
(backend/query_store.py). A storage outage degrades the response
(`stored: false`) rather than failing the request — the point of the
RAG-grounded answer is the endpoint's job, not the storage.

Runs on its own model backend (`ask_backend_dep`, config via
`RF_SLM_ASK_BACKEND`/`RF_SLM_ASK_MODEL`), separate from `/diagnose` and
`/explain`'s `model_backend`: `ReferenceBackend` is a deterministic rule
engine that only ever emits diagnosis JSON, so it is not a valid choice
here even when it is the diagnose/explain backend — see
`inference.build_ask_backend`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.config import Settings
from backend.deps import ask_backend_dep, query_store_dep, retriever_dep, settings_dep
from backend.inference import BackendError, run_ask
from backend.query_store import QueryStore, QueryStoreError
from backend.schemas import (
    AskRequest,
    AskResponse,
    ChatMessage,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummary,
)

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _title_from(message: str) -> str:
    message = " ".join(message.split())  # collapse whitespace/newlines
    return message if len(message) <= 60 else message[:57] + "..."


@router.post("/ask", response_model=AskResponse)
def ask(
    req: AskRequest,
    cfg: Settings = Depends(settings_dep),
    backend=Depends(ask_backend_dep),
    retriever=Depends(retriever_dep),
    store: QueryStore = Depends(query_store_dep),
) -> AskResponse:
    temperature = cfg.clamp_explain_temperature(req.temperature)
    now = _now()

    conversation_id = req.conversation_id
    store_error: str | None = None
    prior: list[dict] = []

    if conversation_id is None:
        try:
            conversation_id = store.create_conversation(_title_from(req.message), now)
        except QueryStoreError as exc:
            store_error = str(exc)
    else:
        try:
            prior = store.get_messages(conversation_id)
        except QueryStoreError as exc:
            # Can't recover this conversation's context; still answer the new
            # message on its own rather than failing the whole request.
            store_error = str(exc)

    # Save the user's message *before* the model call, which can take
    # 20-80s on this deployment's CPU-only backend. Saving it only after
    # generation (as this used to) meant a conversation refreshed mid-reply
    # showed 0 messages -- an empty-looking, newly-created conversation with
    # nothing in it -- which read as the refresh being broken rather than
    # the reply still being generated.
    if conversation_id is not None and store_error is None:
        try:
            store.add_message(conversation_id, "user", req.message, [], None, now)
        except QueryStoreError as exc:
            store_error = str(exc)

    history = [{"role": m["role"], "content": m["content"]} for m in prior]
    history.append({"role": "user", "content": req.message})

    try:
        answer, citations = run_ask(history, temperature, backend, cfg, retriever)
    except BackendError as exc:
        raise HTTPException(503, str(exc))

    message_id = None
    if conversation_id is not None and store_error is None:
        try:
            message_id = store.add_message(
                conversation_id, "assistant", answer,
                [c.model_dump() for c in citations], temperature, now,
            )
        except QueryStoreError as exc:
            store_error = str(exc)

    return AskResponse(
        conversation_id=conversation_id, message_id=message_id,
        answer=answer, citations=citations, temperature_used=temperature,
        created_at=now, stored=message_id is not None, store_error=store_error,
    )


@router.get("/ask/conversations", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    store: QueryStore = Depends(query_store_dep),
) -> ConversationListResponse:
    """Every saved conversation, most recent first — not just this browser's own."""
    try:
        rows = store.list_conversations(limit)
    except QueryStoreError as exc:
        return ConversationListResponse(items=[], store_error=str(exc))
    return ConversationListResponse(items=[ConversationSummary.model_validate(r) for r in rows])


@router.get("/ask/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: str,
    store: QueryStore = Depends(query_store_dep),
) -> ConversationDetailResponse:
    try:
        rows = store.get_messages(conversation_id)
    except QueryStoreError as exc:
        raise HTTPException(503, str(exc))
    return ConversationDetailResponse(
        id=conversation_id, messages=[ChatMessage.model_validate(r) for r in rows]
    )
