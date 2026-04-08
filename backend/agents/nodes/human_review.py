"""
human_review node
This node is the HITL interrupt point.
LangGraph pauses BEFORE this node when interrupt_before=["human_review"] is set.
The node itself just passes state through — the actual human edits are injected
via graph.update_state() before the graph is resumed.
"""

import logging

from agents.state import TenderState

logger = logging.getLogger(__name__)


def run(state: TenderState) -> dict:
    logger.info("human_review: resuming after human input")
    return {"status": "finalising", "hitl_iteration": state.get("hitl_iteration", 0) + 1}
