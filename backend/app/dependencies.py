"""FastAPI dependency injection — singletons shared across requests."""

from functools import lru_cache

from app.services.graph_store import GraphStore
from app.services.vector_store import VectorStore
from app.services.pipeline import Pipeline
from app.services.retriever import Retriever


@lru_cache(maxsize=1)
def _graph_store() -> GraphStore:
    gs = GraphStore()
    gs.connect()
    return gs


@lru_cache(maxsize=1)
def _vector_store() -> VectorStore:
    return VectorStore()


def get_graph_store() -> GraphStore:
    return _graph_store()


def get_vector_store() -> VectorStore:
    return _vector_store()


def get_pipeline() -> Pipeline:
    return Pipeline(graph_store=_graph_store(), vector_store=_vector_store())


def get_retriever() -> Retriever:
    return Retriever(vector_store=_vector_store(), graph_store=_graph_store())
