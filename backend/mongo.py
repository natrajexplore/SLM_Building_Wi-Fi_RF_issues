"""Persistence for the frontend's "Submit / Ask" tab.

`QueryStore` is the seam, mirroring `ModelBackend` in inference.py:
`MongoQueryStore` is the real implementation, tests substitute an in-memory
fake via `app.dependency_overrides[deps.mongo_store_dep]` the same way they
substitute `StubBackend` for `ModelBackend`.

A MongoDB outage must degrade one `/ask` request (the response still carries
the answer, just with `stored: false`), not crash the whole backend or the
request — so `MongoQueryStore.save` raises `QueryStoreError` rather than
letting a raw pymongo exception escape, and the router decides how to
degrade. The connection is lazy and retried on every call while unavailable
(never cached as "permanently down"), so MongoDB coming up after the backend
started just works on the next request.
"""
from __future__ import annotations

import os
from typing import Protocol


MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "rf_slm")


class QueryStoreError(RuntimeError):
    """MongoDB is unreachable or the write failed. Callers must degrade, not 500."""


class QueryStore(Protocol):
    def save(self, query: str, answer: str, citations: list[dict],
              temperature_used: float, created_at: str) -> str:
        """Persist one Q&A record; returns its id. Raises QueryStoreError on failure."""
        ...

    def ping(self) -> bool:
        """True if the store is reachable right now, without writing anything."""
        ...


class MongoQueryStore:
    name = "mongo"

    def __init__(self, uri: str = MONGO_URI, db: str = MONGO_DB) -> None:
        self.uri = uri
        self.db = db
        self._client = None

    def _collection(self):
        if self._client is None:
            try:
                from pymongo import MongoClient
                client = MongoClient(self.uri, serverSelectionTimeoutMS=2000)
                client.admin.command("ping")
            except Exception as exc:
                raise QueryStoreError(f"MongoDB unavailable at {self.uri}: {exc}") from exc
            self._client = client
        return self._client[self.db]["queries"]

    def save(self, query: str, answer: str, citations: list[dict],
              temperature_used: float, created_at: str) -> str:
        doc = {
            "query": query, "answer": answer, "citations": citations,
            "temperature_used": temperature_used, "created_at": created_at,
        }
        try:
            result = self._collection().insert_one(doc)
        except QueryStoreError:
            raise
        except Exception as exc:
            raise QueryStoreError(f"MongoDB write failed: {exc}") from exc
        return str(result.inserted_id)

    def ping(self) -> bool:
        try:
            self._collection()
            return True
        except QueryStoreError:
            return False
