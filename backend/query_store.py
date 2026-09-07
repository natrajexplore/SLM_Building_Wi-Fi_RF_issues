"""Persistence for the frontend's "Submit / Ask" tab.

`QueryStore` is the seam, mirroring `ModelBackend` in inference.py:
`PostgresQueryStore` is the real implementation, tests substitute an
in-memory fake via `app.dependency_overrides[deps.query_store_dep]` the same
way they substitute `StubBackend` for `ModelBackend`.

A PostgreSQL outage must degrade one `/ask` request (the response still
carries the answer, just with `stored: false`), not crash the whole backend
or the request — so `PostgresQueryStore.save` raises `QueryStoreError` rather
than letting a raw psycopg exception escape, and the router decides how to
degrade. The connection is lazy and retried whenever it is missing or closed
(never cached as "permanently down"), so PostgreSQL coming up after the
backend started just works on the next request. The `queries` table is
created on first successful connection — no separate migration step for
local dev.
"""
from __future__ import annotations

import os
from typing import Protocol


POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "postgresql://postgres@localhost:5432/rf_slm")


class QueryStoreError(RuntimeError):
    """PostgreSQL is unreachable or the query failed. Callers must degrade, not 500."""


class QueryStore(Protocol):
    def save(self, query: str, answer: str, citations: list[dict],
              temperature_used: float, created_at: str) -> str:
        """Persist one Q&A record; returns its id. Raises QueryStoreError on failure."""
        ...

    def ping(self) -> bool:
        """True if the store is reachable right now, without writing anything."""
        ...

    def list_recent(self, limit: int) -> list[dict]:
        """Most-recent-first {id, query, answer, citations, temperature_used,
        created_at} records. Raises QueryStoreError on failure."""
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
                    "CREATE TABLE IF NOT EXISTS queries ("
                    "  id BIGSERIAL PRIMARY KEY,"
                    "  query TEXT NOT NULL,"
                    "  answer TEXT NOT NULL,"
                    "  citations JSONB NOT NULL,"
                    "  temperature_used DOUBLE PRECISION NOT NULL,"
                    "  created_at TEXT NOT NULL"
                    ")"
                )
            except Exception as exc:
                raise QueryStoreError(f"PostgreSQL unavailable at {self.dsn}: {exc}") from exc
            self._conn = conn
        return self._conn

    def save(self, query: str, answer: str, citations: list[dict],
              temperature_used: float, created_at: str) -> str:
        from psycopg.types.json import Json

        try:
            conn = self._connection()
            cur = conn.execute(
                "INSERT INTO queries (query, answer, citations, temperature_used, created_at) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (query, answer, Json(citations), temperature_used, created_at),
            )
            row = cur.fetchone()
        except QueryStoreError:
            raise
        except Exception as exc:
            raise QueryStoreError(f"PostgreSQL write failed: {exc}") from exc
        return str(row[0])

    def ping(self) -> bool:
        try:
            self._connection()
            return True
        except QueryStoreError:
            return False

    def list_recent(self, limit: int) -> list[dict]:
        try:
            conn = self._connection()
            cur = conn.execute(
                "SELECT id, query, answer, citations, temperature_used, created_at "
                "FROM queries ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        except QueryStoreError:
            raise
        except Exception as exc:
            raise QueryStoreError(f"PostgreSQL read failed: {exc}") from exc
        return [
            {
                "id": str(r[0]), "query": r[1], "answer": r[2],
                "citations": r[3], "temperature_used": r[4], "created_at": r[5],
            }
            for r in rows
        ]
