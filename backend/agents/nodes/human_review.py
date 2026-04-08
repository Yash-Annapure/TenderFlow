"""
Node: human_review

This node is a named no-op — it exists purely as the interrupt target.

The graph is compiled with:
    interrupt_before=["human_review"]

So LangGraph pauses BEFORE this node runs. The API layer then:
  1. Returns the current draft state to the frontend
  2. Waits for the user to edit sections and submit feedback
  3. Calls graph.update_state() to inject user edits into the checkpointed state
  4. Calls graph.invoke(None, config) to resume

When the graph resumes, it enters this node, which simply passes state through
unchanged. All actual edit-incorporation logic is in the finalise node.
"""

import logging

from agents.state import TenderState

logger = logging.getLogger(__name__)


def human_review(state: TenderState) -> dict:
    """Pass-through — the interrupt happens before this node, not inside it."""
    logger.info(
        f"[human_review] Resuming after HITL iteration {state.get('hitl_iteration', 0)}"
    )
    return {}
