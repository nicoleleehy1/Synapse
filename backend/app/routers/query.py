"""Natural language query endpoint."""

from fastapi import APIRouter, Depends

from app.dependencies import get_retriever
from app.models import QueryRequest, QueryResponse
from app.ratelimit import limit_queries
from app.services.retriever import Retriever

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=QueryResponse, dependencies=[Depends(limit_queries)])
async def query(request: QueryRequest, retriever: Retriever = Depends(get_retriever)):
    return await retriever.query(request)
