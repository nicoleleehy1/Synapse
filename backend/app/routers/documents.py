"""Document upload, status, live progress (SSE) and deletion."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.dependencies import get_graph_store, get_pipeline
from app.models import DocumentStatus, UploadResponse
from app.ratelimit import limit_uploads
from app.services.events import broker
from app.services.graph_store import GraphStore
from app.services.pipeline import Pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

_PDF_MAGIC = b"%PDF-"
_TERMINAL = {"complete", "error"}
# Strong references so background tasks aren't garbage-collected mid-run.
_tasks: set[asyncio.Task] = set()


@router.post("/upload", response_model=UploadResponse, dependencies=[Depends(limit_uploads)])
async def upload_pdf(
    file: UploadFile = File(...),
    pipeline: Pipeline = Depends(get_pipeline),
    graph_store: GraphStore = Depends(get_graph_store),
):
    filename = Path(file.filename or "document.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Stream to a temp file, enforcing the size limit without buffering it all in memory.
    upload_dir = Path(settings.upload_dir)
    await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(dir=upload_dir, suffix=".pdf", delete=False)
    size = 0
    try:
        with tmp:
            first = True
            while chunk := await file.read(1 << 20):
                if first and not chunk.startswith(_PDF_MAGIC):
                    raise HTTPException(status_code=400, detail="That file isn't a valid PDF.")
                first = False
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail=f"PDF exceeds the {settings.max_upload_mb} MB limit."
                    )
                tmp.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    except BaseException:
        await asyncio.to_thread(Path(tmp.name).unlink, missing_ok=True)
        raise

    status = DocumentStatus(document_id=str(uuid.uuid4()), filename=filename, status="queued")
    await graph_store.save_document(status)

    async def run() -> None:
        try:
            await pipeline.process(tmp.name, status)
        finally:
            # Don't retain user documents.
            await asyncio.to_thread(Path(tmp.name).unlink, missing_ok=True)

    task = asyncio.create_task(run(), name=f"ingest:{status.document_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    return UploadResponse(
        document_id=status.document_id,
        filename=filename,
        message="Upload accepted. Processing in background.",
    )


@router.get("/", response_model=list[DocumentStatus])
async def list_documents(graph_store: GraphStore = Depends(get_graph_store)):
    return await graph_store.list_documents()


@router.get("/{document_id}/status", response_model=DocumentStatus)
async def get_status(document_id: str, graph_store: GraphStore = Depends(get_graph_store)):
    status = await graph_store.get_document(document_id)
    if not status:
        raise HTTPException(status_code=404, detail="Document not found.")
    return status


@router.get("/{document_id}/events")
async def stream_status(
    document_id: str, request: Request, graph_store: GraphStore = Depends(get_graph_store)
):
    """Server-Sent Events stream of pipeline progress, ending when the job finishes."""
    queue = broker.subscribe(document_id)  # subscribe before the snapshot: no missed updates
    snapshot = await graph_store.get_document(document_id)
    if not snapshot:
        broker.unsubscribe(document_id, queue)
        raise HTTPException(status_code=404, detail="Document not found.")

    async def events():
        try:
            yield {"event": "status", "data": snapshot.model_dump_json()}
            if snapshot.status in _TERMINAL:
                return
            while not await request.is_disconnected():
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield {"event": "ping", "data": json.dumps({})}
                    continue
                yield {"event": "status", "data": update.model_dump_json()}
                if update.status in _TERMINAL:
                    return
        finally:
            broker.unsubscribe(document_id, queue)

    return EventSourceResponse(events(), headers={"X-Accel-Buffering": "no"})


@router.delete("/{document_id}")
async def delete_document(document_id: str, graph_store: GraphStore = Depends(get_graph_store)):
    if not await graph_store.get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    await graph_store.delete_document(document_id)
    return {"message": "Deleted."}
