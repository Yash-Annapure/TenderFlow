"""
Node: draft_sections

Model: claude-sonnet-4-6 (per section draft)
       claude-haiku-4-5-20251001 (Module 6 compliance, Module 7 robustness scoring)

For each section:
  - If chunks available → Sonnet drafts 400-600 words
  - If no chunks       → inserts [INSUFFICIENT CONTEXT] placeholder

Then runs quality scoring:
  Module 6: Compliance Coverage (Haiku, ~900 tokens)
  Module 7: Robustness Index    (Haiku, ~700 tokens)

Final Score = Primary×0.60 + (M6×0.55 + M7×0.45)×0.40

Updates TenderState:
  - sections            (draft_text, sources_used updated)
  - compliance_score
  - robustness_score
  - quality_score_total
  - final_score
  - score_justifications
  - status              → "awaiting_review"
"""

import json
import logging
import re
from pathlib import Path

import anthropic

from agents.state import STATUS_AWAITING_REVIEW, TenderState
from config.settings import settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "draft_section.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""

INSUFFICIENT_CONTEXT_TEMPLATE = (
    "[INSUFFICIENT CONTEXT] The knowledge base does not contain enough information "
    "to draft the '{section_name}' section. Please upload relevant {doc_types} documents "
    "via the Knowledge Base interface and re-run."
)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def draft_sections(state: TenderState) -> dict:
    """Draft all sections then compute quality scores."""
    logger.info(f"[draft_sections] Drafting {len(state['sections'])} sections")

    client = _get_client()
    updated_sections = []

    for section in state["sections"]:
        section_id = section["section_id"]
        chunks = state.get("retrieved_chunks", {}).get(section_id, [])

        if not chunks:
            updated = dict(section)
            updated["draft_text"] = INSUFFICIENT_CONTEXT_TEMPLATE.format(
                section_name=section["section_name"],
                doc_types=", ".join(section.get("doc_types_needed", ["relevant"])),
            )
            updated["confidence"] = "LOW"
            updated_sections.append(updated)
            continue

        context = "\n\n".join(
            f"[{c.get('doc_type', 'doc')} — {c.get('source_name', '')}]\n{c['chunk_text']}"
            for c in chunks
        )
        sources = list({c.get("source_name", "") for c in chunks if c.get("source_name")})

        draft_text = _draft_one_section(client, section, context, state.get("tender_text", "")[:2000])

        updated = dict(section)
        updated["draft_text"] = draft_text
        updated["sources_used"] = sources
        updated_sections.append(updated)

    # Quality scoring
    compliance_score = _score_compliance(updated_sections, state.get("compliance_checklist", []))
    robustness_score = _score_robustness(updated_sections)
    quality_score = compliance_score * 0.55 + robustness_score * 0.45
    primary_total = state.get("primary_score_total", 0.0)
    final_score = primary_total * 0.60 + quality_score * 0.40

    justifications = {
        "Primary Score": (
            f"{primary_total:.1f}/100 — weighted aggregate of Track Record, Expertise Depth, "
            "Methodology Fit, Delivery Credibility, and Pricing Competitiveness"
        ),
        "Compliance Coverage": f"{compliance_score:.1f}/100 — mandatory requirement coverage across all sections",
        "Robustness Index": f"{robustness_score:.1f}/100 — density of quantified claims and named project references",
        "Final Score": (
            f"{final_score:.1f}/100 — Primary (60%) + Quality (40%) weighted composite. "
            f"Band: {_band(final_score)}"
        ),
    }

    logger.info(f"[draft_sections] Final score: {final_score:.1f} ({_band(final_score)})")

    return {
        "sections": updated_sections,
        "compliance_score": compliance_score,
        "robustness_score": robustness_score,
        "quality_score_total": quality_score,
        "final_score": final_score,
        "score_justifications": justifications,
        "status": STATUS_AWAITING_REVIEW,
    }


# ── Drafting helpers ───────────────────────────────────────────────────────────

def _draft_one_section(
    client: anthropic.Anthropic,
    section: dict,
    context: str,
    tender_excerpt: str,
) -> str:
    requirements_text = "\n".join(f"- {r}" for r in section.get("requirements", []))
    word_target = section.get("word_count_target", 500)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1400,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Section to draft: {section['section_name']}\n"
                        f"Target length: ~{word_target} words\n\n"
                        f"Requirements from the tender:\n{requirements_text}\n\n"
                        f"Tender context (excerpt):\n{tender_excerpt[:500]}\n\n"
                        f"Relevant knowledge base content:\n<context>\n{context[:3500]}\n</context>\n\n"
                        "Draft the section now:"
                    ),
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"[draft_sections] Sonnet call failed for '{section['section_name']}': {e}")
        return f"[DRAFT ERROR: {e}]"


# ── Quality scoring ────────────────────────────────────────────────────────────

def _all_drafts(sections: list[dict]) -> str:
    return "\n\n".join(
        f"## {s['section_name']}\n{s.get('draft_text', '')}"
        for s in sections
        if s.get("draft_text") and "INSUFFICIENT CONTEXT" not in s.get("draft_text", "")
    )


def _band(score: float) -> str:
    if score >= 90:
        return "EXCELLENT"
    if score >= 75:
        return "STRONG"
    if score >= 60:
        return "MODERATE"
    return "WEAK"


def _score_compliance(sections: list[dict], checklist: list[dict]) -> float:
    """Module 6: Haiku rates compliance checklist coverage (~900 tokens)."""
    if not checklist:
        return 75.0

    drafts = _all_drafts(sections)
    if not drafts.strip():
        return 20.0

    mandatory = [item["item"] for item in checklist if item.get("mandatory")]
    optional = [item["item"] for item in checklist if not item.get("mandatory")]

    client = _get_client()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Score 0-100: what % of these requirements are addressed in the draft sections?\n"
                        "Mandatory items count 70% of the score, optional 30%.\n"
                        "Respond with only a number.\n\n"
                        f"Mandatory requirements:\n{json.dumps(mandatory[:15], indent=2)}\n\n"
                        f"Optional requirements:\n{json.dumps(optional[:10], indent=2)}\n\n"
                        f"Drafted sections (excerpt):\n{drafts[:3000]}"
                    ),
                }
            ],
        )
        return min(float(response.content[0].text.strip()), 100.0)
    except (ValueError, Exception):
        return 60.0


def _score_robustness(sections: list[dict]) -> float:
    """Module 7: Haiku counts quantified claims and named references (~700 tokens)."""
    drafts = _all_drafts(sections)
    if not drafts.strip():
        return 20.0

    client = _get_client()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Score 0-100 for robustness of these tender sections.\n"
                        "Scoring guide:\n"
                        "  +10 per unique quantified claim (number/€/%) up to 40 pts\n"
                        "  +10 per named project or client reference up to 30 pts\n"
                        "  -10 per unsupported assertion (claim with no evidence)\n"
                        "  Base score: 30\n"
                        "Respond with only a number.\n\n"
                        f"Sections:\n{drafts[:3000]}"
                    ),
                }
            ],
        )
        return max(min(float(response.content[0].text.strip()), 100.0), 0.0)
    except (ValueError, Exception):
        return 50.0
