"""
Tender API router.

Endpoints:
  POST /tender/start          — submit tender text or PDF, kick off agent
  GET  /tender/{id}/status    — poll job status + draft
  GET  /tender/{id}/review    — get draft for HITL editor
  POST /tender/{id}/submit    — submit human edits, resume graph
  GET  /tender/{id}/download  — get final draft as plain text
"""

import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from agents.graph import get_graph

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tender", tags=["tender"])

# In-memory job store (no database needed for the simple version)
_jobs: dict[str, dict] = {}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class StartResponse(BaseModel):
    tender_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    tender_id: str
    status: str
    sections: list[dict]
    draft: Optional[str] = None
    error: Optional[str] = None


class ReviewResponse(BaseModel):
    tender_id: str
    sections: list[dict]
    draft: str


class SubmitRequest(BaseModel):
    user_feedback: str = ""
    user_edits: str = ""


class SubmitResponse(BaseModel):
    tender_id: str
    status: str
    message: str


# ── Background task ───────────────────────────────────────────────────────────

def _run_graph(tender_id: str, tender_text: str):
    """Run the LangGraph agent synchronously in a thread pool."""
    graph = get_graph()
    config = {"configurable": {"thread_id": tender_id}}

    _jobs[tender_id]["status"] = "analysing"

    try:
        # Run until interrupt (before human_review)
        for step in graph.stream(
            {
                "tender_id": tender_id,
                "tender_text": tender_text,
                "sections": [],
                "retrieved_context": "",
                "draft": "",
                "user_feedback": "",
                "user_edits": "",
                "final_draft": "",
                "status": "analysing",
                "hitl_iteration": 0,
                "error": None,
            },
            config=config,
            stream_mode="updates",
        ):
            # Each step is a dict of {node_name: state_updates}
            for node_name, updates in step.items():
                if not isinstance(updates, dict):
                    continue  # skip __interrupt__ tuples emitted by LangGraph
                logger.info(f"[{tender_id}] node={node_name} status={updates.get('status', '?')}")
                _jobs[tender_id].update({
                    "status": updates.get("status", _jobs[tender_id]["status"]),
                    "sections": updates.get("sections", _jobs[tender_id].get("sections", [])),
                    "draft": updates.get("draft", _jobs[tender_id].get("draft", "")),
                    "error": updates.get("error"),
                })

    except Exception as e:
        logger.exception(f"[{tender_id}] Graph error: {e}")
        _jobs[tender_id]["status"] = "error"
        _jobs[tender_id]["error"] = str(e)


def _resume_graph(tender_id: str, user_feedback: str, user_edits: str):
    """Inject human edits and resume graph after interrupt."""
    graph = get_graph()
    config = {"configurable": {"thread_id": tender_id}}

    # Inject human edits into the graph state
    graph.update_state(
        config,
        {"user_feedback": user_feedback, "user_edits": user_edits},
        as_node="human_review",
    )

    _jobs[tender_id]["status"] = "finalising"

    try:
        for step in graph.stream(None, config=config, stream_mode="updates"):
            for node_name, updates in step.items():
                if not isinstance(updates, dict):
                    continue  # skip __interrupt__ tuples emitted by LangGraph
                logger.info(f"[{tender_id}] resume node={node_name} status={updates.get('status', '?')}")
                _jobs[tender_id].update({
                    "status": updates.get("status", _jobs[tender_id]["status"]),
                    "final_draft": updates.get("final_draft", _jobs[tender_id].get("final_draft", "")),
                    "error": updates.get("error"),
                })
    except Exception as e:
        logger.exception(f"[{tender_id}] Resume error: {e}")
        _jobs[tender_id]["status"] = "error"
        _jobs[tender_id]["error"] = str(e)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/start", response_model=StartResponse)
async def start_tender(
    background_tasks: BackgroundTasks,
    tender_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Start a new tender response job.
    Accepts either:
    - `tender_text` form field (plain text)
    - `file` upload (PDF — text extracted via PyMuPDF)
    """
    if not tender_text and not file:
        raise HTTPException(status_code=400, detail="Provide either tender_text or a file upload")

    text = tender_text or ""

    if file:
        raw = await file.read()
        if file.filename and file.filename.lower().endswith(".pdf"):
            try:
                import fitz
                doc = fitz.open(stream=raw, filetype="pdf")
                text = "\n\n".join(page.get_text() for page in doc)
                doc.close()
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {e}")
        else:
            text = raw.decode("utf-8", errors="replace")

    if not text.strip():
        raise HTTPException(status_code=400, detail="Tender text is empty")

    tender_id = str(uuid.uuid4())
    _jobs[tender_id] = {
        "tender_id": tender_id,
        "status": "queued",
        "sections": [],
        "draft": "",
        "final_draft": "",
        "error": None,
    }

    # Run the graph in a background thread (FastAPI thread pool)
    loop = asyncio.get_event_loop()
    background_tasks.add_task(
        loop.run_in_executor, None, _run_graph, tender_id, text
    )

    return StartResponse(
        tender_id=tender_id,
        status="queued",
        message="Tender analysis started. Poll /tender/{id}/status for progress.",
    )


@router.get("/{tender_id}/status", response_model=StatusResponse)
def get_status(tender_id: str):
    job = _jobs.get(tender_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return StatusResponse(
        tender_id=tender_id,
        status=job["status"],
        sections=job.get("sections", []),
        draft=job.get("draft"),
        error=job.get("error"),
    )


@router.get("/{tender_id}/review", response_model=ReviewResponse)
def get_review(tender_id: str):
    job = _jobs.get(tender_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("awaiting_review", "finalising", "done"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is not ready for review (status: {job['status']})",
        )
    return ReviewResponse(
        tender_id=tender_id,
        sections=job.get("sections", []),
        draft=job.get("draft", ""),
    )


@router.post("/{tender_id}/submit", response_model=SubmitResponse)
async def submit_review(
    tender_id: str,
    body: SubmitRequest,
    background_tasks: BackgroundTasks,
):
    job = _jobs.get(tender_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "awaiting_review":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not awaiting review (status: {job['status']})",
        )

    loop = asyncio.get_event_loop()
    background_tasks.add_task(
        loop.run_in_executor, None, _resume_graph, tender_id, body.user_feedback, body.user_edits
    )

    return SubmitResponse(
        tender_id=tender_id,
        status="finalising",
        message="Feedback received. Finalising draft...",
    )


@router.get("/{tender_id}/download")
def download_draft(tender_id: str):
    job = _jobs.get(tender_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(
            status_code=409,
            detail=f"Draft not ready yet (status: {job['status']})",
        )

    final = job.get("final_draft") or job.get("draft", "")
    return {"tender_id": tender_id, "final_draft": final}
