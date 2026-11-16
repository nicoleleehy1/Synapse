"""Process-wide singletons, created in the app lifespan and injected via FastAPI."""

from __future__ import annotations

from fastapi import Request

from app.services.agent import GraphRAGAgent
from app.services.graph_store import GraphStore
from app.services.pipeline import Pipeline
from app.services.retriever import Retriever


def get_graph_store(request: Request) -> GraphStore:
    return request.app.state.graph_store


def get_pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline


def get_retriever(request: Request) -> Retriever:
    return request.app.state.retriever


def get_agent(request: Request) -> GraphRAGAgent:
    return request.app.state.agent
