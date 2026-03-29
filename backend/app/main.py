"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import documents_router, graph_router, query_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

app = FastAPI(
    title="PDF Knowledge Graph API",
    description="Extract knowledge graphs from PDF documents.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(graph_router)
app.include_router(query_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
