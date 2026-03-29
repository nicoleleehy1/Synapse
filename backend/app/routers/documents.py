"""Document upload and status endpoints."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import settings
from app.dependencies import get_pipeline, get_graph_store, get_vector_store
from app.models import DocumentStatus, UploadResponse
from app.services.pipeline import Pipeline
from app.services.graph_store import GraphStore
from app.services.vector_store import VectorStore

router = APIRouter(prefix="/documents", tags=["documents"])

_executor = ThreadPoolExecutor(max_workers=2)
_statuses: dict[str, DocumentStatus] = {}


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    pipeline: Pipeline = Depends(get_pipeline),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    document_id = str(uuid.uuid4())
    save_path = Path(settings.upload_dir) / f"{document_id}.pdf"

    content = await file.read()
    save_path.write_bytes(content)

    _statuses[document_id] = DocumentStatus(
        document_id=document_id,
        filename=file.filename,
        status="processing",
    )

    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        _executor,
        _run_pipeline,
        pipeline,
        str(save_path),
        document_id,
        file.filename,
    )

    return UploadResponse(
        document_id=document_id,
        filename=file.filename,
        message="Upload accepted. Processing in background.",
    )


@router.get("/", response_model=list[DocumentStatus])
async def list_documents():
    return list(_statuses.values())


@router.get("/{document_id}/status", response_model=DocumentStatus)
async def get_status(document_id: str):
    status = _statuses.get(document_id)
    if not status:
        raise HTTPException(status_code=404, detail="Document not found.")
    return status


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    graph_store: GraphStore = Depends(get_graph_store),
    vector_store: VectorStore = Depends(get_vector_store),
):
    status = _statuses.get(document_id)
    if not status:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Entities stored by filename, chunks stored by UUID
    graph_store.delete_document(document_id=document_id, document_name=status.filename)
    vector_store.delete_document(document_id)

    del _statuses[document_id]
    return {"message": "Deleted."}


def _run_pipeline(pipeline: Pipeline, path: str, document_id: str, filename: str) -> None:
    status = pipeline.process(path, document_id, filename)
    _statuses[document_id] = status
