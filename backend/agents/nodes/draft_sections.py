"""
draft_sections node
Drafts each tender section in parallel using Haiku.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from agents.state import TenderState

logger = logging.getLogger(__name__)

_SECTION_PROMPT = """\
Draft a tender response section for Meridian Intelligence GmbH.

SECTION: {name}
REQUIREMENTS: {requirements}

KNOWLEDGE BASE:
{context}

TENDER (excerpt):
{tender_snippet}

Write 200-350 words of professional proposal text grounded in the KB.
Output only the section body — no heading, no "Confidence:" label.
If KB lacks info, write [INSUFFICIENT CONTEXT: <what is missing>]."""


def _draft_one(
    client: anthropic.Anthropic,
    name: str,
    requirements: list[str],
    context: str,
    tender_snippet: str,
) -> tuple[str, str]:
    """Returns (section_name, draft_text)."""
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": _SECTION_PROMPT.format(
                name=name,
                requirements=", ".join(requirements),
                context=context,
                tender_snippet=tender_snippet,
            ),
        }],
    )
    return name, msg.content[0].text.strip()


def run(state: TenderState) -> dict:
    logger.info("draft_sections: starting parallel draft")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    sections = state.get("sections", [])
    context = state.get("retrieved_context", "")[:6000]
    tender_snippet = state.get("tender_text", "")[:800]

    drafts: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=min(len(sections), 6)) as pool:
        futures = {
            pool.submit(
                _draft_one,
                client,
                s["name"],
                s.get("requirements", []),
                context,
                tender_snippet,
            ): s
            for s in sections
        }
        for future in as_completed(futures):
            section = futures[future]
            try:
                name, text = future.result()
                drafts[name] = text
                logger.info(f"draft_sections: done [{name}]")
            except Exception as e:
                logger.warning(f"draft_sections: failed [{section['name']}]: {e}")
                drafts[section["name"]] = f"[DRAFT ERROR: {e}]"

    # Assemble full draft and update sections
    draft_parts = []
    updated_sections = []
    for s in sections:
        name = s["name"]
        text = drafts.get(name, "[DRAFT MISSING]")
        confidence = "HIGH" if "[INSUFFICIENT CONTEXT" not in text else "LOW"
        draft_parts.append(f"## {name}\n**Confidence:** {confidence}\n\n{text}\n\n---")
        updated_sections.append({**s, "draft_text": text, "confidence": confidence})

    draft = "\n\n".join(draft_parts)
    logger.info(f"draft_sections: assembled {len(draft)} char draft from {len(sections)} sections")
    return {"sections": updated_sections, "draft": draft, "status": "awaiting_review"}
