"""
Tender router — /tender/*

Endpoints:
  POST /tender/start          Upload tender PDF, start agent job
  GET  /tender/{id}/status    Poll job status + draft sections
  GET  /tender/{id}/download  Stream the generated DOCX file
"""

import asyncio
import json
import logging
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from agents.graph import get_graph, get_thread_config
from agents.state import (
    STATUS_ANALYSING,
    STATUS_AWAITING_REVIEW,
    STATUS_DONE,
    STATUS_DRAFTING,
    STATUS_ERROR,
    STATUS_FINALISING,
    STATUS_PENDING,
    STATUS_RETRIEVING,
    TenderState,
)
from api.schemas.tender_schemas import TenderJobResponse
from config.settings import settings
from core.document_parser import parse_file
from core.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tender", tags=["tender"])


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/start", response_model=TenderJobResponse)
async def start_tender(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Tender document (PDF or text)"),
    output_format: str = "docx",
):
    """
    Upload a tender document and start the agent.
    Returns tender_id immediately — poll /tender/{id}/status for progress.
    """
    tender_id = str(uuid.uuid4())
    file_content = await file.read()
    filename = file.filename or f"tender_{tender_id}.pdf"

    # Save tender file
    uploads_path = Path(settings.uploads_dir)
    uploads_path.mkdir(parents=True, exist_ok=True)
    saved_path = uploads_path / f"{tender_id}_{filename}"
    saved_path.write_bytes(file_content)

    # Parse tender text
    try:
        tender_text = parse_file(str(saved_path), file_content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse tender document: {e}")

    if not tender_text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the tender document")

    # Create tender_jobs row in Supabase
    supabase = get_supabase_admin()
    supabase.table("tender_jobs").insert(
        {
            "id": tender_id,
            "tender_filename": filename,
            "status": STATUS_PENDING,
            "output_format": output_format,
        }
    ).execute()

    # Build initial state
    initial_state: TenderState = {
        "tender_id": tender_id,
        "tender_text": tender_text,
        "tender_filename": filename,
        "output_format": output_format,
        "sections": [],
        "compliance_checklist": [],
        "dimension_weights": {},
        "retrieved_chunks": {},
        "primary_scores": {},
        "primary_score_total": 0.0,
        "compliance_score": 0.0,
        "robustness_score": 0.0,
        "quality_score_total": 0.0,
        "final_score": 0.0,
        "score_justifications": {},
        "user_feedback": "",
        "request_another_round": False,
        "hitl_iteration": 0,
        "output_path": None,
        "status": STATUS_PENDING,
        "error_message": None,
    }

    background_tasks.add_task(_run_graph, tender_id=tender_id, initial_state=initial_state)

    return TenderJobResponse(tender_id=tender_id, status=STATUS_PENDING, tender_filename=filename)


@router.get("/{tender_id}/status", response_model=TenderJobResponse)
def get_tender_status(tender_id: str):
    """Poll job status. When status is 'awaiting_review', sections_json is populated."""
    supabase = get_supabase_admin()
    result = supabase.table("tender_jobs").select("*").eq("id", tender_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Tender job {tender_id} not found")

    job = result.data[0]
    return TenderJobResponse(
        tender_id=tender_id,
        status=job["status"],
        tender_filename=job.get("tender_filename"),
        sections=job.get("sections_json"),
        score_json=job.get("score_json"),
        output_path=job.get("output_path"),
        hitl_iteration=job.get("hitl_iteration", 0),
        error_msg=job.get("error_msg"),
    )


@router.get("/{tender_id}/download")
def download_tender(tender_id: str):
    """Stream the generated DOCX. Only available when status is 'done'."""
    supabase = get_supabase_admin()
    result = supabase.table("tender_jobs").select("status, output_path").eq("id", tender_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Tender job {tender_id} not found")

    job = result.data[0]
    if job["status"] != STATUS_DONE:
        raise HTTPException(
            status_code=409,
            detail=f"Tender is not done yet (status: {job['status']}). Poll /status first.",
        )

    output_path = job.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        path=output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"tenderflow_{tender_id}.docx",
    )


@router.get("/{tender_id}/events")
async def stream_events(tender_id: str):
    """
    SSE endpoint — streams tender job status updates to the frontend.
    Emits a JSON event whenever the status changes.
    Closes when status reaches awaiting_review, done, or error.
    """
    terminal = {STATUS_AWAITING_REVIEW, STATUS_DONE, STATUS_ERROR}

    async def event_generator():
        last_status = None
        while True:
            try:
                supabase = get_supabase_admin()
                result = await asyncio.to_thread(
                    lambda: supabase.table("tender_jobs")
                    .select("status, sections_json, score_json, output_path, error_msg, hitl_iteration")
                    .eq("id", tender_id)
                    .execute()
                )
                if not result.data:
                    yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                    return

                job = result.data[0]
                if job["status"] != last_status:
                    last_status = job["status"]
                    yield f"data: {json.dumps(job)}\n\n"

                if job["status"] in terminal:
                    return

                await asyncio.sleep(1.0)
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/reiterate-section")
async def reiterate_section(body: dict):
    """
    Re-draft a single section using the already-configured Anthropic client.
    Token-optimised: Haiku only, one section, targeted instruction.
    No job state involved — purely a stateless AI call.

    Request body: { section_name, requirements, current_draft, instruction, word_target }
    Response:     { text, input_tokens, output_tokens }
    """
    import anthropic

    section_name  = body.get("section_name", "")
    requirements  = body.get("requirements", [])
    current_draft = (body.get("current_draft") or "")[:2000]
    instruction   = body.get("instruction", "")
    word_target   = int(body.get("word_target", 500))

    if not section_name or not instruction:
        raise HTTPException(status_code=422, detail="section_name and instruction are required")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    req_text = "\n".join(f"- {r}" for r in (requirements or [])[:6])

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system=(
                "You are drafting one section of a formal tender response for a professional consultancy. "
                "Write clearly, be specific, justify claims with evidence. "
                "Output only the revised section text — no commentary, no headings."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Section: {section_name}\n"
                    f"Word target: ~{word_target} words\n"
                    f"Requirements:\n{req_text}\n\n"
                    f"Current draft:\n{current_draft}\n\n"
                    f"Revision instruction: {instruction}\n\n"
                    "Output the revised section text only."
                ),
            }],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Anthropic call failed: {e}")

    return {
        "text":          response.content[0].text.strip(),
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


# ── Background graph runner ────────────────────────────────────────────────────

def _run_graph(tender_id: str, initial_state: TenderState) -> None:
    """
    Run the LangGraph agent in a background thread.
    Updates tender_jobs status after each significant transition.
    The graph pauses before human_review — the thread then returns.
    On HITL submit, the graph is resumed from the hitl router.
    """
    supabase = get_supabase_admin()
    graph = get_graph()
    config = get_thread_config(tender_id)

    def _update_job(status: str, extra: dict | None = None):
        payload = {"status": status, "updated_at": "now()"}
        if extra:
            payload.update(extra)
        try:
            supabase.table("tender_jobs").update(payload).eq("id", tender_id).execute()
        except Exception as e:
            logger.error(f"[tender] Failed to update job {tender_id}: {e}")

    _NODE_STATUS = {
        "analyse_tender": STATUS_ANALYSING,
        "retrieve_context": STATUS_RETRIEVING,
        "draft_sections": STATUS_DRAFTING,
        "finalise": STATUS_FINALISING,
    }

    try:
        _update_job(STATUS_ANALYSING)
        for chunk in graph.stream(initial_state, config, stream_mode="updates"):
            for node_name in chunk:
                new_status = _NODE_STATUS.get(node_name)
                if new_status:
                    _update_job(new_status)

        # Check where the graph paused
        state_snapshot = graph.get_state(config)
        current_values = state_snapshot.values
        logger.info(f"[tender] Graph returned — state_snapshot.next={state_snapshot.next!r}")
        logger.info(f"[tender] sections in state: {len(current_values.get('sections', []))}")

        if state_snapshot.next and "human_review" in state_snapshot.next:
            # Paused at HITL interrupt — save draft sections for frontend
            sections_for_frontend = [
                {k: v for k, v in s.items() if k not in ("user_edits", "finalised_content")}
                for s in current_values.get("sections", [])
            ]
            logger.info(f"[tender] sections_for_frontend count: {len(sections_for_frontend)}")
            score_json = {
                "primary_score_total": current_values.get("primary_score_total", 0),
                "compliance_score": current_values.get("compliance_score", 0),
                "robustness_score": current_values.get("robustness_score", 0),
                "final_score": current_values.get("final_score", 0),
                "score_justifications": current_values.get("score_justifications", {}),
            }
            _update_job(
                STATUS_AWAITING_REVIEW,
                {
                    "sections_json": sections_for_frontend,
                    "score_json": score_json,
                },
            )
        else:
            # Graph ran to completion without HITL (unlikely but handle gracefully)
            _update_job(STATUS_DONE, {"output_path": current_values.get("output_path")})

    except Exception as e:
        logger.error(f"[tender] Graph failed for {tender_id}: {e}", exc_info=True)
        _update_job(STATUS_ERROR, {"error_msg": str(e)})
