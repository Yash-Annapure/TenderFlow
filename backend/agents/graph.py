"""
LangGraph StateGraph definition.

Graph topology:
    START → analyse_tender → retrieve_context → draft_sections
          → human_review  ← INTERRUPT POINT
          → finalise → END
                 ↑
            (loop if request_another_round and iteration < MAX_HITL_ITERATIONS)

Checkpointing:
    Attempts PostgresSaver backed by Supabase session-mode pooler (port 5432).
    Falls back to MemorySaver if DB connection fails at startup — HITL still
    works within the session, but state is lost on process restart.

    tender_id is used as the LangGraph thread_id — every resume picks up from
    the exact interrupt point even across process restarts (PostgresSaver only).

HITL Resume Pattern:
    1. Graph pauses before human_review (interrupt_before).
    2. API calls graph.update_state(config, {user_edits, user_feedback, hitl_iteration})
    3. API calls graph.invoke(None, config) to resume.
    4. Graph runs human_review (no-op) → finalise → END (or loops).
"""

import logging
import threading

from langgraph.graph import END, START, StateGraph

from agents.nodes.analyse_tender import analyse_tender
from agents.nodes.draft_sections import draft_sections
from agents.nodes.finalise import finalise
from agents.nodes.human_review import human_review
from agents.nodes.retrieve_context import retrieve_context
from agents.state import TenderState
from config.settings import settings

logger = logging.getLogger(__name__)

_compiled_graph = None
_checkpointer = None
_init_lock = threading.Lock()


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


def _make_postgres_checkpointer():
    """
    Build a PostgresSaver backed by a psycopg_pool.ConnectionPool.

    Uses session-mode pooler URL (port 5432) from settings.langgraph_db_url.
    autocommit=True: required — PostgresSaver manages its own transactions.
    prepare_threshold=None: disables prepared statements (pgbouncer-safe).
    """
    from psycopg_pool import ConnectionPool
    from langgraph.checkpoint.postgres import PostgresSaver

    pool = ConnectionPool(
        conninfo=settings.langgraph_db_url,
        min_size=1,
        max_size=3,
        kwargs={"autocommit": True, "prepare_threshold": None},
        open=True,
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()  # idempotent — creates checkpoint tables if not present
    host = settings.langgraph_db_url.split("@")[-1]
    logger.info(f"[graph] PostgresSaver ready — {host}")
    return checkpointer


def get_graph():
    """
    Return the compiled LangGraph with checkpointing.
    Attempts PostgresSaver first; falls back to MemorySaver on DB failure.
    Thread-safe singleton via double-checked locking.
    """
    global _compiled_graph, _checkpointer

    if _compiled_graph is not None:
        return _compiled_graph

    with _init_lock:
        if _compiled_graph is not None:
            return _compiled_graph

        try:
            _checkpointer = _make_postgres_checkpointer()
        except Exception as e:
            logger.warning(
                f"[graph] PostgresSaver init failed ({e!r}), "
                "falling back to MemorySaver — HITL state will not survive restarts"
            )
            from langgraph.checkpoint.memory import MemorySaver
            _checkpointer = MemorySaver()

        builder = _build_graph()
        _compiled_graph = builder.compile(
            checkpointer=_checkpointer,
            interrupt_before=["human_review"],
        )
        logger.info(f"[graph] Graph compiled with {type(_checkpointer).__name__}")

    return _compiled_graph


def get_thread_config(tender_id: str) -> dict:
    """Return the LangGraph config dict for a given tender thread."""
    return {"configurable": {"thread_id": tender_id}}
