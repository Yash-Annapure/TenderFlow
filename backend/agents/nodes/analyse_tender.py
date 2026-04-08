"""
analyse_tender node
Uses Claude Haiku to extract sections and requirements from the tender text.
"""

import json
import logging
import os
import re

import anthropic

from agents.state import TenderState

logger = logging.getLogger(__name__)

_PROMPT = """\
You are a tender analysis expert. Analyse the following tender document and identify the main sections that need to be addressed in a response.

For each section, list the key requirements the response must cover.

TENDER DOCUMENT:
{tender_text}

Return ONLY a JSON array (no markdown, no explanation):
[
  {{
    "name": "Section Name",
    "requirements": ["requirement 1", "requirement 2", "..."],
    "draft_text": "",
    "confidence": "LOW"
  }},
  ...
]

Identify 4-8 sections that cover the full scope of the tender."""


def run(state: TenderState) -> dict:
    logger.info("analyse_tender: starting")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    tender_text = state.get("tender_text", "")
    if not tender_text:
        return {"status": "error", "error": "No tender text provided"}

    # Truncate very long tenders to avoid token limits
    if len(tender_text) > 6000:
        tender_text = tender_text[:6000] + "\n\n[... truncated ...]"

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        messages=[{
            "role": "user",
            "content": _PROMPT.format(tender_text=tender_text),
        }],
    )

    raw = msg.content[0].text.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        sections = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse sections JSON, using fallback")
        sections = [
            {"name": "Executive Summary", "requirements": ["Overview of our approach"], "draft_text": "", "confidence": "LOW"},
            {"name": "Technical Approach", "requirements": ["Methodology", "Technical solution"], "draft_text": "", "confidence": "LOW"},
            {"name": "Team & Expertise", "requirements": ["Relevant experience", "Key personnel"], "draft_text": "", "confidence": "LOW"},
            {"name": "Past Experience", "requirements": ["Relevant projects", "References"], "draft_text": "", "confidence": "LOW"},
            {"name": "Work Plan & Deliverables", "requirements": ["Timeline", "Milestones"], "draft_text": "", "confidence": "LOW"},
        ]

    logger.info(f"analyse_tender: found {len(sections)} sections")
    return {"sections": sections, "status": "retrieving"}
