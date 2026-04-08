"""
TenderFlow Debug UI
-------------------
Gradio-based debug interface for the LangGraph agent.

Run standalone:
    cd debug_ui
    python app.py

Or via main.py:
    cd backend
    python main.py --debug
"""

import sys
import os
import time
import uuid
import threading
import logging
from pathlib import Path

# Add backend to path so we can import agents directly
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# Load .env from backend
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "backend" / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

import gradio as gr
from agents.graph import get_graph

# Simple in-memory job store
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _run_graph(tender_id: str, tender_text: str):
    graph = get_graph()
    config = {"configurable": {"thread_id": tender_id}}

    with _lock:
        _jobs[tender_id]["status"] = "analysing"

    try:
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
            for node_name, updates in step.items():
                if not isinstance(updates, dict):
                    continue  # skip __interrupt__ tuples
                logger.info(f"[{tender_id}] node={node_name} status={updates.get('status', '?')}")
                with _lock:
                    _jobs[tender_id].update({
                        "status": updates.get("status", _jobs[tender_id]["status"]),
                        "sections": updates.get("sections", _jobs[tender_id].get("sections", [])),
                        "draft": updates.get("draft", _jobs[tender_id].get("draft", "")),
                        "error": updates.get("error"),
                    })
    except Exception as e:
        logger.exception(f"[{tender_id}] Graph error: {e}")
        with _lock:
            _jobs[tender_id]["status"] = "error"
            _jobs[tender_id]["error"] = str(e)


def _resume_graph(tender_id: str, user_feedback: str, user_edits: str):
    graph = get_graph()
    config = {"configurable": {"thread_id": tender_id}}

    graph.update_state(
        config,
        {"user_feedback": user_feedback, "user_edits": user_edits},
        as_node="human_review",
    )

    with _lock:
        _jobs[tender_id]["status"] = "finalising"

    try:
        for step in graph.stream(None, config=config, stream_mode="updates"):
            for node_name, updates in step.items():
                if not isinstance(updates, dict):
                    continue  # skip __interrupt__ tuples
                logger.info(f"[{tender_id}] resume node={node_name} status={updates.get('status', '?')}")
                with _lock:
                    _jobs[tender_id].update({
                        "status": updates.get("status", _jobs[tender_id]["status"]),
                        "final_draft": updates.get("final_draft", _jobs[tender_id].get("final_draft", "")),
                        "error": updates.get("error"),
                    })
    except Exception as e:
        logger.exception(f"[{tender_id}] Resume error: {e}")
        with _lock:
            _jobs[tender_id]["status"] = "error"
            _jobs[tender_id]["error"] = str(e)


# ── Gradio event handlers ─────────────────────────────────────────────────────

def submit_tender(tender_text: str):
    if not tender_text.strip():
        return (
            gr.update(value="❌ Please enter tender text.", visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            "",
        )

    tender_id = str(uuid.uuid4())
    _jobs[tender_id] = {
        "tender_id": tender_id,
        "status": "queued",
        "sections": [],
        "draft": "",
        "final_draft": "",
        "error": None,
    }

    thread = threading.Thread(target=_run_graph, args=(tender_id, tender_text), daemon=True)
    thread.start()

    # Poll until done or awaiting review
    timeout = 120
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(1)
        with _lock:
            job = dict(_jobs[tender_id])
        status = job["status"]

        if status == "error":
            return (
                gr.update(value=f"❌ Error: {job['error']}", visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
                tender_id,
            )
        if status == "awaiting_review":
            sections_text = _format_sections(job.get("sections", []))
            draft = job.get("draft", "")
            return (
                gr.update(value=f"✅ Analysis complete. Review the draft below.\n\n**Sections found:**\n{sections_text}", visible=True),
                gr.update(value=draft, visible=True),
                gr.update(visible=True),
                tender_id,
            )

    return (
        gr.update(value=f"⏳ Still running (status: {status}). Try refreshing.", visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
        tender_id,
    )


def submit_review(tender_id: str, user_feedback: str, user_edits: str):
    if not tender_id:
        return gr.update(value="❌ No active job. Submit a tender first.", visible=True), gr.update(visible=False)

    with _lock:
        job = _jobs.get(tender_id)
    if not job or job["status"] != "awaiting_review":
        return gr.update(value=f"❌ Job not awaiting review (status: {job['status'] if job else 'unknown'})", visible=True), gr.update(visible=False)

    thread = threading.Thread(target=_resume_graph, args=(tender_id, user_feedback, user_edits), daemon=True)
    thread.start()

    # Poll until done
    timeout = 120
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(1)
        with _lock:
            job = dict(_jobs[tender_id])
        status = job["status"]

        if status == "error":
            return gr.update(value=f"❌ Error: {job['error']}", visible=True), gr.update(visible=False)
        if status == "done":
            final = job.get("final_draft", "")
            return (
                gr.update(value="✅ Final draft ready!", visible=True),
                gr.update(value=final, visible=True),
            )

    return gr.update(value=f"⏳ Still finalising (status: {status}).", visible=True), gr.update(visible=False)


def _format_sections(sections: list) -> str:
    if not sections:
        return "None"
    lines = []
    for s in sections:
        name = s.get("name", "?")
        conf = s.get("confidence", "?")
        reqs = s.get("requirements", [])
        lines.append(f"- **{name}** [{conf}]: {', '.join(reqs[:2])}{'...' if len(reqs) > 2 else ''}")
    return "\n".join(lines)


# ── Gradio layout ─────────────────────────────────────────────────────────────

def build_ui():
    with gr.Blocks(title="TenderFlow Debug UI", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# TenderFlow — Debug UI")
        gr.Markdown("Direct agent invocation. For debugging only.")

        tender_id_state = gr.State("")

        with gr.Row():
            with gr.Column(scale=2):
                tender_input = gr.Textbox(
                    label="Tender Text",
                    placeholder="Paste tender document here...",
                    lines=10,
                )
                submit_btn = gr.Button("Analyse Tender", variant="primary")

        status_box = gr.Markdown(visible=False)

        with gr.Group(visible=False) as review_group:
            gr.Markdown("## Draft — Review & Edit")
            draft_box = gr.Textbox(label="Draft", lines=15, interactive=True)
            feedback_input = gr.Textbox(label="Feedback (optional)", placeholder="e.g. Be more concise in section 2", lines=3)
            approve_btn = gr.Button("Approve & Finalise", variant="primary")

        final_box = gr.Textbox(label="Final Draft", lines=15, interactive=False, visible=False)

        submit_btn.click(
            fn=submit_tender,
            inputs=[tender_input],
            outputs=[status_box, draft_box, review_group, tender_id_state],
        )

        approve_btn.click(
            fn=submit_review,
            inputs=[tender_id_state, feedback_input, draft_box],
            outputs=[status_box, final_box],
        )

    return demo


def launch(port: int = 7860, share: bool = False):
    logger.info(f"Launching TenderFlow Debug UI on http://localhost:{port}")
    ui = build_ui()
    ui.launch(server_port=port, share=share, show_error=True)


if __name__ == "__main__":
    launch()
