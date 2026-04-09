"""
HITL router — /tender/{id}/review and /tender/{id}/submit

This is the most critical router — it implements the human-in-the-loop
interrupt/resume cycle using LangGraph's checkpointing mechanism.

GET  /tender/{id}/review   Return current draft sections for the editor UI
POST /tender/{id}/submit   Inject user edits into state and resume the graph
"""

import logging
import threading

from fastapi import APIRouter, BackgroundTasks, HTTPException

from agents.graph import get_graph, get_thread_config
from agents.state import STATUS_AWAITING_REVIEW, STATUS_DONE, STATUS_ERROR, STATUS_FINALISING
from api.schemas.hitl_schemas import HITLSubmitRequest, ReviewResponse
from core.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tender", tags=["hitl"])


@router.get("/{tender_id}/review", response_model=ReviewResponse)
def get_review(tender_id: str):
    """
    Return the current draft sections for display in the HITL editor.
    Only available when status is 'awaiting_review'.
    """
    supabase = get_supabase_admin()
    result = supabase.table("tender_jobs").select("*").eq("id", tender_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Tender job {tender_id} not found")

    job = result.data[0]
    if job["status"] not in (STATUS_AWAITING_REVIEW, STATUS_DONE):
        raise HTTPException(
            status_code=409,
            detail=f"Tender is not awaiting review (status: {job['status']})",
        )

    score_json = job.get("score_json") or {}
    return ReviewResponse(
        tender_id=tender_id,
        hitl_iteration=job.get("hitl_iteration", 0),
        final_score=score_json.get("final_score", 0.0),
        sections=job.get("sections_json") or [],
        score_justifications=score_json.get("score_justifications", {}),
    )


@router.post("/{tender_id}/submit")
def submit_review(
    tender_id: str,
    body: HITLSubmitRequest,
    background_tasks: BackgroundTasks,
):
    """
    Submit user edits and resume the LangGraph agent.

    Flow:
      1. Validate job is in awaiting_review state
      2. Load current graph state from Supabase checkpoint
      3. Merge user edits into the sections list
      4. Inject user_feedback, request_another_round, hitl_iteration into state
      5. Update tender_jobs to "finalising"
      6. Resume graph in background thread

    Returns immediately — poll /tender/{id}/status for completion.
    """
    supabase = get_supabase_admin()

    # Validate job state
    result = supabase.table("tender_jobs").select("status, hitl_iteration").eq(
        "id", tender_id
    ).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Tender job {tender_id} not found")

    job = result.data[0]
    if job["status"] not in (STATUS_AWAITING_REVIEW, STATUS_DONE):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit: tender is not in a reviewable state (status: {job['status']})",
        )

    current_iteration = job.get("hitl_iteration", 0)
    new_iteration = current_iteration + 1

    # Build edits + new-section lookup from the submitted payload
    edits_map = {edit.section_id: edit.user_edits for edit in body.sections}
    submitted_ids = {edit.section_id for edit in body.sections}

    graph = get_graph()
    config = get_thread_config(tender_id)

    # Load current state snapshot
    state_snapshot = graph.get_state(config)
    current_sections: list[dict] = list(state_snapshot.values.get("sections", []))
    existing_ids = {s["section_id"] for s in current_sections}

    # Apply user edits to existing sections
    updated_sections = []
    for section in current_sections:
        updated = dict(section)
        if section["section_id"] in edits_map:
            updated["user_edits"] = edits_map[section["section_id"]]
        updated_sections.append(updated)

    # Append brand-new sections the user added in the UI
    for edit in body.sections:
        if edit.section_id not in existing_ids:
            updated_sections.append({
                "section_id": edit.section_id,
                "section_name": edit.section_name or edit.section_id,
                "user_edits": edit.user_edits or "",
                "draft_text": edit.user_edits or "",
                "requirements": edit.requirements or [],
                "sources_used": [],
                "confidence": "MEDIUM",
                "gap_flag": None,
                "word_count_target": 400,
            })

    resubmit_from_done = job["status"] == STATUS_DONE

    # Inject updated state into checkpoint.
    # For jobs already at END (done), use as_node="human_review" so the graph
    # treats this as a new checkpoint after human_review, with finalise next.
    update_kwargs = {}
    if resubmit_from_done:
        update_kwargs["as_node"] = "human_review"

    graph.update_state(
        config,
        {
            "sections": updated_sections,
            "user_feedback": body.feedback,
            "request_another_round": body.request_another_round,
            "hitl_iteration": new_iteration,
        },
        **update_kwargs,
    )

    # Update DB status
    supabase.table("tender_jobs").update(
        {"status": STATUS_FINALISING, "hitl_iteration": new_iteration, "updated_at": "now()"}
    ).eq("id", tender_id).execute()

    # Resume graph in background
    background_tasks.add_task(_resume_graph, tender_id=tender_id)

    return {
        "tender_id": tender_id,
        "status": STATUS_FINALISING,
        "hitl_iteration": new_iteration,
        "message": "Review submitted. Poll /tender/{id}/status for completion.",
    }


# ── Background graph resume ────────────────────────────────────────────────────

def _resume_graph(tender_id: str) -> None:
    """
    Resume the paused LangGraph from the human_review interrupt point.
    Passing None as the input tells LangGraph to continue from the checkpoint.
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
            logger.error(f"[hitl] Failed to update job {tender_id}: {e}")

    try:
        # stream resume so we can update status as finalise node runs
        for chunk in graph.stream(None, config, stream_mode="updates"):
            if "finalise" in chunk:
                _update_job(STATUS_FINALISING)

        state_snapshot = graph.get_state(config)
        current_values = state_snapshot.values

        if state_snapshot.next and "human_review" in state_snapshot.next:
            # Another HITL round was requested — loop back to awaiting_review
            sections_for_frontend = [
                {k: v for k, v in s.items() if k not in ("finalised_content",)}
                for s in current_values.get("sections", [])
            ]
            score_json = {
                "final_score": current_values.get("final_score", 0),
                "score_justifications": current_values.get("score_justifications", {}),
            }
            _update_job(
                STATUS_AWAITING_REVIEW,
                {"sections_json": sections_for_frontend, "score_json": score_json},
            )
        else:
            # Graph reached END — persist finalised sections so history view can show them
            final_sections = [
                {k: v for k, v in s.items()}
                for s in current_values.get("sections", [])
            ]
            _update_job(
                STATUS_DONE,
                {
                    "output_path": current_values.get("output_path"),
                    "sections_json": final_sections,
                },
            )
            logger.info(f"[hitl] Tender {tender_id} completed → {current_values.get('output_path')}")

    except Exception as e:
        logger.error(f"[hitl] Graph resume failed for {tender_id}: {e}", exc_info=True)
        _update_job(STATUS_ERROR, {"error_msg": str(e)})
