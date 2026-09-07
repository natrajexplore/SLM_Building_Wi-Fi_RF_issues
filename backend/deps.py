"""FastAPI dependency providers. Tests override these via app.dependency_overrides."""
from __future__ import annotations

from functools import lru_cache

from backend.config import Settings, get_settings
from backend.inference import ModelBackend, build_backend
from backend.mongo import MongoQueryStore, QueryStore


def settings_dep() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def _backend_singleton() -> ModelBackend:
    return build_backend(get_settings())


def backend_dep() -> ModelBackend:
    return _backend_singleton()


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
def _mongo_store_singleton() -> MongoQueryStore:
    return MongoQueryStore()


def mongo_store_dep() -> QueryStore:
    return _mongo_store_singleton()
