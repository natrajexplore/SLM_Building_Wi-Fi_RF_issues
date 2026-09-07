"""FastAPI dependency providers. Tests override these via app.dependency_overrides."""
from __future__ import annotations

from functools import lru_cache

from backend.config import Settings, get_settings
from backend.inference import ModelBackend, build_ask_backend, build_backend
from backend.query_store import PostgresQueryStore, QueryStore


def settings_dep() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def _backend_singleton() -> ModelBackend:
    return build_backend(get_settings())


def backend_dep() -> ModelBackend:
    return _backend_singleton()


@lru_cache(maxsize=1)
def _ask_backend_singleton() -> ModelBackend:
    return build_ask_backend(get_settings())


def ask_backend_dep() -> ModelBackend:
    return _ask_backend_singleton()


@lru_cache(maxsize=1)
def _retriever_singleton():
    try:
        from rag.retriever import Retriever

        return Retriever.load(get_settings().rag_index_dir)
    except Exception:
        return None  # retrieval is optional; endpoints degrade to no citations


def retriever_dep():
    return _retriever_singleton()


@lru_cache(maxsize=1)
def _query_store_singleton() -> PostgresQueryStore:
    return PostgresQueryStore()


def query_store_dep() -> QueryStore:
    return _query_store_singleton()
