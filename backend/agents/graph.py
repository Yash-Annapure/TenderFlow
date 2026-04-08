"""
TenderFlow LangGraph agent.

Graph flow:
  START → analyse_tender → retrieve_context → draft_sections
        → [INTERRUPT] → human_review → finalise → END
"""

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.state import TenderState
from agents.nodes import (
    analyse_tender,
    draft_sections,
    finalise,
    human_review,
    retrieve_context,
)

logger = logging.getLogger(__name__)

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
        logger.info("LangGraph compiled with MemorySaver checkpointer")
    return _graph


def _build_graph():
    builder = StateGraph(TenderState)

    builder.add_node("analyse_tender", analyse_tender.run)
    builder.add_node("retrieve_context", retrieve_context.run)
    builder.add_node("draft_sections", draft_sections.run)
    builder.add_node("human_review", human_review.run)
    builder.add_node("finalise", finalise.run)

    builder.add_edge(START, "analyse_tender")
    builder.add_edge("analyse_tender", "retrieve_context")
    builder.add_edge("retrieve_context", "draft_sections")
    builder.add_edge("draft_sections", "human_review")
    builder.add_edge("human_review", "finalise")
    builder.add_edge("finalise", END)

    checkpointer = MemorySaver()
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
