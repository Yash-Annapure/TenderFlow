"""
finalise node
Uses Claude Sonnet to apply human edits and feedback to produce the final draft.
"""

import logging
import os

import anthropic

from agents.state import TenderState

logger = logging.getLogger(__name__)

_PROMPT = """\
You are finalising a tender response draft based on human reviewer feedback.

ORIGINAL DRAFT:
{draft}

HUMAN FEEDBACK:
{feedback}

HUMAN EDITS (specific section changes):
{edits}

Your task:
1. Apply all the human edits and feedback to improve the draft
2. Ensure consistent tone and professional language throughout
3. Fix any gaps flagged as [INSUFFICIENT CONTEXT: ...] if the human provided guidance
4. Keep the same section structure (## Section Name headings)
5. The final output should be submission-ready

Return the complete final tender response draft."""


def run(state: TenderState) -> dict:
    logger.info("finalise: applying human feedback")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    draft = state.get("draft", "")
    feedback = state.get("user_feedback", "No feedback provided.")
    edits = state.get("user_edits", "No specific edits provided.")

    # If no feedback or edits, just mark as done without another LLM call
    if feedback in ("", "No feedback provided.") and edits in ("", "No specific edits provided."):
        logger.info("finalise: no changes requested, using draft as final")
        return {"final_draft": draft, "status": "done"}

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        messages=[{
            "role": "user",
            "content": _PROMPT.format(draft=draft, feedback=feedback, edits=edits),
        }],
    )

    final_draft = msg.content[0].text.strip()
    logger.info(f"finalise: final draft {len(final_draft)} chars")
    return {"final_draft": final_draft, "status": "done"}
