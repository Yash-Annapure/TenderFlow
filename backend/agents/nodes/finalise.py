"""
Node: finalise

Model: claude-sonnet-4-6 (finishing touches on edited sections)

For each section:
  - If user_edits is non-empty  → Sonnet polishes the edit (tone, grammar, flow)
  - If user_edits is empty      → draft_text is used as-is for finalised_content

Then calls output_tool to render the DOCX and uploads to outputs/.

Updates TenderState:
  - sections         (finalised_content set per section)
  - output_path
  - status           → "done"
  - request_another_round → False (reset for next iteration detection)
"""

import logging
from pathlib import Path

import anthropic

from agents.state import STATUS_DONE, STATUS_FINALISING, TenderState
from config.settings import settings
from tools.output_tool import render_docx

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "finalise.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def finalise(state: TenderState) -> dict:
    """Apply finishing touches to user-edited sections, then render DOCX."""
    logger.info(
        f"[finalise] iteration={state.get('hitl_iteration', 0)}, "
        f"sections={len(state['sections'])}"
    )

    client = _get_client()
    user_feedback = state.get("user_feedback", "")
    updated_sections = []

    for section in state["sections"]:
        updated = dict(section)
        user_edits = (section.get("user_edits") or "").strip()

        if user_edits:
            logger.debug(f"[finalise] Polishing section '{section['section_id']}'")
            updated["finalised_content"] = _apply_finishing_touches(
                client, section, user_edits, user_feedback
            )
        else:
            # No human edits — preserve AI draft unchanged
            updated["finalised_content"] = section.get("draft_text", "")

        updated_sections.append(updated)

    # Render DOCX
    final_state = {**state, "sections": updated_sections}
    output_path = render_docx(final_state, state["tender_id"])

    logger.info(f"[finalise] DOCX rendered → {output_path}")

    return {
        "sections": updated_sections,
        "output_path": output_path,
        "status": STATUS_DONE,
        "request_another_round": False,
    }


def _apply_finishing_touches(
    client: anthropic.Anthropic,
    section: dict,
    user_edits: str,
    user_feedback: str,
) -> str:
    """Sonnet: polish the human-edited text without changing its substance."""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1400,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Section: {section['section_name']}\n\n"
                        f"Reviewer's overall feedback:\n{user_feedback or 'No specific feedback provided.'}\n\n"
                        f"Human-edited text to polish:\n<edited>\n{user_edits}\n</edited>\n\n"
                        "Return only the polished text:"
                    ),
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"[finalise] Sonnet polish failed for '{section['section_id']}': {e}")
        return user_edits  # Fall back to raw user edit on error
