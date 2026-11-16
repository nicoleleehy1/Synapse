"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import documents_router, graph_router, query_router
from app.services.graph_store import GraphStore
from app.services.pipeline import Pipeline
from app.services.retriever import Retriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Allow tests to inject pre-built services.
    if not hasattr(app.state, "graph_store"):
        gs = GraphStore()
        await gs.connect()
        app.state.graph_store = gs
        app.state.pipeline = Pipeline(graph_store=gs)
        app.state.retriever = Retriever(graph_store=gs)
        interrupted = await gs.fail_interrupted_documents()
        if interrupted:
            logger.warning("Marked %d interrupted ingestion job(s) as failed", interrupted)
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY is not set: uploads and questions will fail")
    yield
    await app.state.graph_store.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Synapse API",
        description="Turn PDFs into an explorable, queryable knowledge graph.",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(documents_router)
    app.include_router(graph_router)
    app.include_router(query_router)

    @app.get("/health", tags=["meta"])
    async def health():
        db_ok = await app.state.graph_store.ping()
        body = {"status": "ok" if db_ok else "degraded", "neo4j": db_ok}
        return JSONResponse(body, status_code=200 if db_ok else 503)

    return app


app = create_app()
