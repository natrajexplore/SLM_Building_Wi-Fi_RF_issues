"""Persistence for the frontend's "Submit / Ask" tab.

`QueryStore` is the seam, mirroring `ModelBackend` in inference.py:
`PostgresQueryStore` is the real implementation, tests substitute an
in-memory fake via `app.dependency_overrides[deps.query_store_dep]` the same
way they substitute `StubBackend` for `ModelBackend`.

The tab is a multi-turn chat, not isolated Q&A: a `conversation` holds an
ordered list of `messages` (role "user" | "assistant"). `/ask` appends the
new user message, fetches the conversation's prior messages to build context
for the model, then appends the assistant's reply.

A PostgreSQL outage must degrade one `/ask` request (the response still
carries the answer, just with `stored: false`), not crash the whole backend
or the request — so every `PostgresQueryStore` method raises `QueryStoreError`
rather than letting a raw psycopg exception escape, and the router decides
how to degrade. The connection is lazy and retried whenever it is missing or
closed (never cached as "permanently down"), so PostgreSQL coming up after
the backend started just works on the next request. The `conversations` /
`messages` tables are created on first successful connection — no separate
migration step for local dev.
"""
from __future__ import annotations

import os
from typing import Protocol


POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "postgresql://postgres@localhost:5432/rf_slm")


class QueryStoreError(RuntimeError):
    """PostgreSQL is unreachable or the query failed. Callers must degrade, not 500."""


class QueryStore(Protocol):
    def create_conversation(self, title: str, created_at: str) -> str:
        """Start a new conversation; returns its id. Raises QueryStoreError on failure."""
        ...

    def add_message(self, conversation_id: str, role: str, content: str,
                     citations: list[dict], temperature_used: float | None,
                     created_at: str) -> str:
        """Append one message to a conversation; returns the message id.
        Raises QueryStoreError on failure."""
        ...

    def get_messages(self, conversation_id: str) -> list[dict]:
        """Every message in a conversation, oldest first. Raises QueryStoreError
        on failure (including an unknown conversation_id)."""
        ...

    def list_conversations(self, limit: int) -> list[dict]:
        """Most-recent-first {id, title, created_at, message_count} summaries.
        Raises QueryStoreError on failure."""
        ...

    def ping(self) -> bool:
        """True if the store is reachable right now, without writing anything."""
        ...


class PostgresQueryStore:
    name = "postgres"

    def __init__(self, dsn: str = POSTGRES_DSN) -> None:
        self.dsn = dsn
        self._conn = None

    def _connection(self):
        if self._conn is None or self._conn.closed:
            try:
                import psycopg
                conn = psycopg.connect(self.dsn, connect_timeout=2, autocommit=True)
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS conversations ("
                    "  id BIGSERIAL PRIMARY KEY,"
                    "  title TEXT NOT NULL,"
                    "  created_at TEXT NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS messages ("
                    "  id BIGSERIAL PRIMARY KEY,"
                    "  conversation_id BIGINT NOT NULL"
                    "    REFERENCES conversations(id) ON DELETE CASCADE,"
                    "  role TEXT NOT NULL,"
                    "  content TEXT NOT NULL,"
                    "  citations JSONB NOT NULL DEFAULT '[]',"
                    "  temperature_used DOUBLE PRECISION,"
                    "  created_at TEXT NOT NULL"
                    ")"
                )
            except Exception as exc:
                raise QueryStoreError(f"PostgreSQL unavailable at {self.dsn}: {exc}") from exc
            self._conn = conn
        return self._conn

    def create_conversation(self, title: str, created_at: str) -> str:
        try:
            conn = self._connection()
            cur = conn.execute(
                "INSERT INTO conversations (title, created_at) VALUES (%s, %s) RETURNING id",
                (title, created_at),
            )
            row = cur.fetchone()
        except QueryStoreError:
            raise
        except Exception as exc:
            raise QueryStoreError(f"PostgreSQL write failed: {exc}") from exc
        return str(row[0])

    def add_message(self, conversation_id: str, role: str, content: str,
                     citations: list[dict], temperature_used: float | None,
                     created_at: str) -> str:
        from psycopg.types.json import Json

        try:
            conn = self._connection()
            cur = conn.execute(
                "INSERT INTO messages "
                "  (conversation_id, role, content, citations, temperature_used, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (int(conversation_id), role, content, Json(citations), temperature_used, created_at),
            )
            row = cur.fetchone()
        except QueryStoreError:
            raise
        except Exception as exc:
            raise QueryStoreError(f"PostgreSQL write failed: {exc}") from exc
        return str(row[0])

    def get_messages(self, conversation_id: str) -> list[dict]:
        try:
            conn = self._connection()
            cur = conn.execute(
                "SELECT id, role, content, citations, temperature_used, created_at "
                "FROM messages WHERE conversation_id = %s ORDER BY id ASC",
                (int(conversation_id),),
            )
            rows = cur.fetchall()
        except QueryStoreError:
            raise
        except Exception as exc:
            raise QueryStoreError(f"PostgreSQL read failed: {exc}") from exc
        return [
            {
                "id": str(r[0]), "role": r[1], "content": r[2],
                "citations": r[3], "temperature_used": r[4], "created_at": r[5],
            }
            for r in rows
        ]

    def list_conversations(self, limit: int) -> list[dict]:
        try:
            conn = self._connection()
            cur = conn.execute(
                "SELECT c.id, c.title, c.created_at, COUNT(m.id) "
                "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
                "GROUP BY c.id, c.title, c.created_at "
                "ORDER BY c.id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        except QueryStoreError:
            raise
        except Exception as exc:
            raise QueryStoreError(f"PostgreSQL read failed: {exc}") from exc
        return [
            {"id": str(r[0]), "title": r[1], "created_at": r[2], "message_count": r[3]}
            for r in rows
        ]

    def ping(self) -> bool:
        try:
            self._connection()
            return True
        except QueryStoreError:
            return False
