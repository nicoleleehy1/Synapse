"""Natural language query endpoint."""

from fastapi import APIRouter, Depends

from app.dependencies import get_retriever
from app.models import QueryRequest, QueryResponse
from app.services.retriever import Retriever

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    retriever: Retriever = Depends(get_retriever),
):
    return retriever.query(request)
