"""
draft_sections node
Uses Claude Sonnet to draft each section of the tender response,
grounded in the retrieved KB context.
"""

import json
import logging
import os
import re

import anthropic

from agents.state import TenderState

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior consultant at Meridian Intelligence GmbH, an expert at writing EU institutional tender responses.
You write precise, professional, evidence-backed tender proposals.
Always ground your writing in the provided Knowledge Base content.
If the KB doesn't contain enough information for a section, flag it clearly with [INSUFFICIENT CONTEXT: <what is missing>]."""

_PROMPT = """\
You are drafting a tender response. Below is the tender information and our Knowledge Base.

TENDER SECTIONS TO ADDRESS:
{sections_json}

KNOWLEDGE BASE (company info, CVs, methodology, past tenders):
{context}

TENDER TEXT (first part):
{tender_snippet}

---

Write a complete, professional tender response draft. For each section:
1. Write 300-500 words of polished proposal text
2. Ground every claim in the Knowledge Base
3. Use specific names, figures, and project references from the KB
4. Mark any gaps with [INSUFFICIENT CONTEXT: description]

Format your response as:

## [Section Name]
**Confidence:** HIGH/MEDIUM/LOW

[Section draft text...]

---

Write all sections in sequence. Be specific, not generic."""


def run(state: TenderState) -> dict:
    logger.info("draft_sections: starting")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    sections = state.get("sections", [])
    context = state.get("retrieved_context", "")
    tender_text = state.get("tender_text", "")

    # Build a compact sections summary for the prompt
    sections_summary = json.dumps(
        [{"name": s["name"], "requirements": s.get("requirements", [])} for s in sections],
        indent=2,
    )

    # Truncate inputs to stay within token budget
    context_trunc = context[:14000] if len(context) > 14000 else context
    tender_snippet = tender_text[:2000] if len(tender_text) > 2000 else tender_text

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": _PROMPT.format(
                sections_json=sections_summary,
                context=context_trunc,
                tender_snippet=tender_snippet,
            ),
        }],
    )

    draft = msg.content[0].text.strip()

    # Parse confidence levels back into sections
    updated_sections = _update_section_confidence(sections, draft)

    logger.info(f"draft_sections: generated {len(draft)} char draft")
    return {
        "sections": updated_sections,
        "draft": draft,
        "status": "awaiting_review",
    }


def _update_section_confidence(sections: list[dict], draft: str) -> list[dict]:
    """Extract per-section confidence from the draft and update sections list."""
    updated = []
    for section in sections:
        name = section["name"]
        confidence = "MEDIUM"

        # Look for the section block in the draft
        pattern = re.compile(
            rf"##\s+{re.escape(name)}.*?\*\*Confidence:\*\*\s*(HIGH|MEDIUM|LOW)",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(draft)
        if match:
            confidence = match.group(1).upper()

        # Extract draft text for this section
        section_pattern = re.compile(
            rf"##\s+{re.escape(name)}\s*\n(.*?)(?=\n##\s|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        section_match = section_pattern.search(draft)
        draft_text = section_match.group(1).strip() if section_match else ""

        updated.append({**section, "draft_text": draft_text, "confidence": confidence})

    return updated
