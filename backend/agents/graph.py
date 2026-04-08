"""
LangGraph StateGraph definition.

Graph topology:
    START → analyse_tender → retrieve_context → draft_sections
          → human_review  ← INTERRUPT POINT
          → finalise → END
                 ↑             ↑
            (loop if request_another_round and iteration < MAX_HITL_ITERATIONS)

Checkpointing:
    Uses PostgresSaver backed by Supabase (transaction-mode pooler URL).
    The tender_id is used as the LangGraph thread_id so every resume
    picks up from the exact interrupt point even across process restarts.

HITL Resume Pattern:
    1. Graph pauses before human_review (interrupt_before).
    2. API calls graph.update_state(config, {user_edits, user_feedback, hitl_iteration})
    3. API calls graph.invoke(None, config) to resume.
    4. Graph runs human_review (no-op) → finalise → END (or loops).

Singleton:
    get_graph() returns the compiled graph with checkpointer initialised.
    Call once at startup (FastAPI lifespan) to run checkpointer.setup().
"""

import logging

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from agents.nodes.analyse_tender import analyse_tender
from agents.nodes.draft_sections import draft_sections
from agents.nodes.finalise import finalise
from agents.nodes.human_review import human_review
from agents.nodes.retrieve_context import retrieve_context
from agents.state import TenderState
from config.settings import settings

logger = logging.getLogger(__name__)


def _should_loop_or_end(state: TenderState) -> str:
    """Conditional edge after finalise: loop back for another HITL round or finish."""
    if (
        state.get("request_another_round")
        and state.get("hitl_iteration", 0) < settings.max_hitl_iterations
    ):
        logger.info(
            f"[graph] Another HITL round requested "
            f"(iteration {state.get('hitl_iteration', 0)} / {settings.max_hitl_iterations})"
        )
        return "human_review"
    return END


def _build_graph() -> StateGraph:
    builder = StateGraph(TenderState)

    builder.add_node("analyse_tender", analyse_tender)
    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("draft_sections", draft_sections)
    builder.add_node("human_review", human_review)
    builder.add_node("finalise", finalise)

    builder.add_edge(START, "analyse_tender")
    builder.add_edge("analyse_tender", "retrieve_context")
    builder.add_edge("retrieve_context", "draft_sections")
    builder.add_edge("draft_sections", "human_review")
    builder.add_edge("human_review", "finalise")
    builder.add_conditional_edges("finalise", _should_loop_or_end)

    return builder


# ── Singleton management ───────────────────────────────────────────────────────

from psycopg_pool import ConnectionPool

_compiled_graph = None
_checkpointer: PostgresSaver | None = None
_pool: ConnectionPool | None = None


def get_graph():
    """
    Return the compiled LangGraph with Supabase checkpointing.
    Safe to call multiple times — initialised once.
    """
    global _compiled_graph, _checkpointer, _pool

    if _compiled_graph is None:
        logger.info("[graph] Initialising LangGraph with PostgresSaver checkpointer")
        _pool = ConnectionPool(
            conninfo=settings.supabase_db_url,
            kwargs={"autocommit": True, "prepare_threshold": None}
        )
        _checkpointer = PostgresSaver(_pool)
        _checkpointer.setup()  # idempotent — creates checkpoint tables if not present

        builder = _build_graph()
        _compiled_graph = builder.compile(
            checkpointer=_checkpointer,
            interrupt_before=["human_review"],
        )
        logger.info("[graph] Graph compiled and ready")

    return _compiled_graph


def get_thread_config(tender_id: str) -> dict:
    """Return the LangGraph config dict for a given tender thread."""
    return {"configurable": {"thread_id": tender_id}}
