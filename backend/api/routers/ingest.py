"""
Ingest router — /ingest/*

Endpoints:
  POST /ingest/document        Upload a single KB document (multipart)
  GET  /ingest/status/{id}     Poll background ingest task status
  POST /ingest/bulk            Seed KB from the kb/ directory (admin-gated)
"""

import logging
import threading
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from api.schemas.ingest_schemas import BulkIngestResponse, IngestTaskStatus
from config.settings import settings
from tools.ingest_tool import IngestResult, bulk_ingest_kb_directory, ingest_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])

# ── In-process task store (production: replace with Redis/Supabase row) ────────
_tasks: dict[str, IngestTaskStatus] = {}
_tasks_lock = threading.Lock()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/document", response_model=IngestTaskStatus)
async def ingest_document_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form(..., description="past_tender | cv | methodology | company_profile"),
    source_name: str = Form(..., description="Human-readable document name"),
    uploaded_by: str = Form(default="user"),
):
    """
    Upload a single document to the knowledge base.
    Parsing, enrichment, guard, embedding, and upsert run in a background thread.
    Returns task_id immediately — poll /ingest/status/{task_id} for progress.
    """
    allowed_doc_types = {"past_tender", "cv", "methodology", "company_profile"}
    if doc_type not in allowed_doc_types:
        raise HTTPException(
            status_code=422,
            detail=f"doc_type must be one of: {', '.join(sorted(allowed_doc_types))}",
        )

    task_id = str(uuid.uuid4())
    file_content = await file.read()
    filename = file.filename or f"upload_{task_id}"

    # Create upload directory and save file
    uploads_path = Path(settings.uploads_dir)
    uploads_path.mkdir(parents=True, exist_ok=True)
    saved_path = uploads_path / f"{task_id}_{filename}"
    saved_path.write_bytes(file_content)

    # Initialise task status
    initial_status = IngestTaskStatus(
        task_id=task_id,
        status="running",
        filename=filename,
    )
    with _tasks_lock:
        _tasks[task_id] = initial_status

    background_tasks.add_task(
        _run_ingest_task,
        task_id=task_id,
        file_path=str(saved_path),
        doc_type=doc_type,
        source_name=source_name,
        uploaded_by=uploaded_by,
    )

    return initial_status


@router.get("/status/{task_id}", response_model=IngestTaskStatus)
def get_ingest_status(task_id: str):
    """Poll background ingest task status."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.post("/bulk", response_model=BulkIngestResponse)
def bulk_ingest(x_admin_key: Annotated[str | None, Header()] = None):
    """
    Seed the knowledge base from the kb/ directory.
    Requires X-Admin-Key header matching ADMIN_KEY in settings.
    Runs synchronously — may take a few minutes for the full KB.
    """
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    logger.info(f"[ingest] Starting bulk ingest from {settings.kb_seed_dir}")
    results: list[IngestResult] = bulk_ingest_kb_directory(settings.kb_seed_dir)

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    return BulkIngestResponse(
        total=len(results),
        committed=status_counts.get("committed", 0),
        guard_blocked=status_counts.get("guard_blocked", 0),
        guard_flagged=status_counts.get("guard_flagged", 0),
        errors=sum(v for k, v in status_counts.items() if k.startswith("error")),
        results=[
            {
                "document_id": r.document_id,
                "filename": r.filename,
                "status": r.status,
                "chunks_created": r.chunks_created,
                "guard_flags": r.guard_flags,
            }
            for r in results
        ],
    )


# ── Background worker ─────────────────────────────────────────────────────────

def _run_ingest_task(
    task_id: str,
    file_path: str,
    doc_type: str,
    source_name: str,
    uploaded_by: str,
) -> None:
    """Run the ingest pipeline and update task status on completion."""
    result = ingest_document(
        file_path=file_path,
        doc_type=doc_type,
        source_name=source_name,
        uploaded_by=uploaded_by,
    )

    final_status = IngestTaskStatus(
        task_id=task_id,
        status="completed" if result.status in ("committed", "guard_flagged") else "error",
        document_id=result.document_id,
        filename=result.filename,
        chunks_created=result.chunks_created,
        guard_flags=result.guard_flags,
        error=result.error,
    )

    with _tasks_lock:
        _tasks[task_id] = final_status
