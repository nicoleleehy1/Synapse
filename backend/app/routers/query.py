"""Question answering: a GraphRAG agent, streamed or as a single response."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.dependencies import get_agent
from app.models import AgentQueryResponse, QueryRequest
from app.ratelimit import limit_queries
from app.services.agent import GraphRAGAgent

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=AgentQueryResponse, dependencies=[Depends(limit_queries)])
async def query(request: QueryRequest, agent: GraphRAGAgent = Depends(get_agent)):
    result = await agent.answer(request.query, request.document_id)
    if result["type"] == "error":
        return AgentQueryResponse(
            answer=result["message"], sources=[], graph_context={"nodes": [], "edges": []}
        )
    return AgentQueryResponse(
        answer=result["answer"],
        sources=result["sources"],
        graph_context=result["graph"],
        highlight_ids=result["highlight_ids"],
        steps=result["steps"],
        latency_ms=result["latency_ms"],
    )


@router.post("/stream", dependencies=[Depends(limit_queries)])
async def query_stream(request: QueryRequest, http: Request, agent: GraphRAGAgent = Depends(get_agent)):
    """Server-Sent Events: `step`, `step_result`, `text`, `text_reset`, then `done` or `error`."""

    async def events():
        async for event in agent.run(request.query, request.document_id):
            if await http.is_disconnected():
                return
            yield {"event": event["type"], "data": json.dumps(event, default=str)}

    return EventSourceResponse(events(), headers={"X-Accel-Buffering": "no"})
