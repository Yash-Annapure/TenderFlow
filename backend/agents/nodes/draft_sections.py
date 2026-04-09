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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# Sections whose content is derived primarily from the tender document itself.
# Even with zero KB chunks these must always be drafted (not show INSUFFICIENT CONTEXT).
_TENDER_PRIMARY_SECTIONS = {"deliverables", "team", "price", "entity_typology"}


def _extract_tender_context_for_section(section_id: str, tender_text: str) -> str:
    """
    Return the most relevant portion of the tender text for a given section type.
    For table sections we need the actual tender deliverables / team / award criteria text.
    For prose sections we need the background and objectives.
    Returns up to 4000 chars.
    """
    # Section markers to search for — ordered from most specific to least
    ANCHORS: dict[str, list[str]] = {
        "executive_summary":  ["1.", "background", "policy context", "objective"],
        "problem_framing":    ["1.", "background", "existing", "gap", "insufficient"],
        "entity_typology":    ["2.", "3.", "scope", "objective", "entities", "organizations"],
        "methodology":        ["4.", "methodolog", "approach", "coverage", "classification"],
        "deliverables":       ["5.", "deliverable", "d1", "d2 —", "d1 —"],
        "team":               ["6.", "team composition", "key expertise", "expertise requirement"],
        "price":              ["7.", "award criteria", "price", "budget", "eur"],
    }
    anchors = ANCHORS.get(section_id, [])
    text_lower = tender_text.lower()

    best_pos = -1
    for anchor in anchors:
        pos = text_lower.find(anchor.lower())
        if pos != -1:
            best_pos = pos
            break   # take the first match (anchors are ordered best-first)

    if best_pos == -1:
        return tender_text[:4000]

    start = max(0, best_pos - 100)
    return tender_text[start:start + 4000]


def draft_sections(state: TenderState) -> dict:
    """Draft all sections then compute quality scores."""
    logger.info(f"[draft_sections] Drafting {len(state['sections'])} sections")

    client = _get_client()
    retrieved_chunks = state.get("retrieved_chunks", {})
    tender_text = state.get("tender_text", "")

    _token_usage: list[dict] = []
    _usage_lock = __import__("threading").Lock()

    def _draft_section_task(section: dict) -> dict:
        section_id = section["section_id"]
        chunks = retrieved_chunks.get(section_id, [])
        updated = dict(section)

        # Table sections (Deliverables, Team, Price, Entity Typology) are always drafted
        # because their content comes primarily from the tender document, not the KB.
        # Only pure KB-dependent prose sections get the INSUFFICIENT CONTEXT fallback.
        if not chunks and section_id not in _TENDER_PRIMARY_SECTIONS:
            updated["draft_text"] = INSUFFICIENT_CONTEXT_TEMPLATE.format(
                section_name=section["section_name"],
                doc_types=", ".join(section.get("doc_types_needed", ["relevant"])),
            )
            updated["confidence"] = "LOW"
            return updated

        context = "\n\n".join(
            f"[{c.get('doc_type', 'doc')} — {c.get('source_name', '')}]\n{c['chunk_text']}"
            for c in chunks
        ) if chunks else "[No knowledge base content retrieved — draft from tender document only]"

        sources = list({c.get("source_name", "") for c in chunks if c.get("source_name")})
        tender_section_text = _extract_tender_context_for_section(section_id, tender_text)
        draft_text, usage = _draft_one_section(client, section, context, tender_section_text)
        if usage:
            with _usage_lock:
                _token_usage.append(usage)
        updated["draft_text"] = draft_text
        updated["sources_used"] = sources
        return updated

    # Draft sections with limited concurrency to avoid 529 overloads.
    # 7 sections × 2 workers = 4 batches rather than one 7-way spike.
    updated_sections_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(_draft_section_task, s): s["section_id"] for s in state["sections"]}
        for future in as_completed(futures):
            result = future.result()
            updated_sections_map[result["section_id"]] = result

    # Preserve original section order
    updated_sections = [updated_sections_map[s["section_id"]] for s in state["sections"]]

    # Quality scoring
    compliance_score, compliance_usage = _score_compliance(updated_sections, state.get("compliance_checklist", []))
    robustness_score, robustness_usage = _score_robustness(updated_sections)
    if compliance_usage:
        _token_usage.append(compliance_usage)
    if robustness_usage:
        _token_usage.append(robustness_usage)
    quality_score = compliance_score * 0.55 + robustness_score * 0.45
    primary_total = state.get("primary_score_total", 0.0)
    final_score = primary_total * 0.60 + quality_score * 0.40

    primary_scores = state.get("primary_scores", {})
    justifications = _build_justifications(
        updated_sections, primary_scores, primary_total,
        compliance_score, robustness_score, final_score,
    )

    logger.info(f"[draft_sections] Final score: {final_score:.1f} ({_band(final_score)})")

    return {
        "sections": updated_sections,
        "compliance_score": compliance_score,
        "robustness_score": robustness_score,
        "quality_score_total": quality_score,
        "final_score": final_score,
        "score_justifications": justifications,
        "status": STATUS_AWAITING_REVIEW,
        "token_usage": _token_usage,
    }


# ── Drafting helpers ───────────────────────────────────────────────────────────

def _draft_one_section(
    client: anthropic.Anthropic,
    section: dict,
    context: str,
    tender_section_text: str,
) -> tuple[str, dict | None]:
    """
    Draft one section using Sonnet.
    tender_section_text: the most relevant portion of the raw tender (up to 4000 chars).
    context: KB chunks formatted as text.
    Returns (draft_text, usage_dict | None).
    """
    section_id = section["section_id"]
    requirements_text = "\n".join(f"- {r}" for r in section.get("requirements", []))

    is_table = section_id in _TENDER_PRIMARY_SECTIONS
    # Table sections need more output tokens (multi-row markdown tables)
    max_tokens = 1400 if is_table else 1000
    word_hint = (
        "(Output only the markdown pipe table — no prose before or after the table.)"
        if is_table else
        f"(Word target: {min(section.get('word_count_target', 250), 300)} words. Dense and precise.)"
    )

    user_message = (
        f"Section to draft: {section['section_name']}\n\n"
        f"══ TENDER DOCUMENT EXTRACT (primary source — read this carefully) ══\n"
        f"{tender_section_text[:4000]}\n\n"
        f"══ SECTION REQUIREMENTS ══\n"
        f"{requirements_text}\n\n"
        f"══ KNOWLEDGE BASE EVIDENCE (past work, CVs, methodology) ══\n"
        f"<context>\n{context[:3000]}\n</context>\n\n"
        f"Draft the '{section['section_name']}' section now. {word_hint}"
    )

    _RETRY_DELAYS = [5, 15, 30]

    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            usage = {
                "op": "draft_section",
                "model": "claude-sonnet-4-6",
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            }
            return response.content[0].text.strip(), usage
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < len(_RETRY_DELAYS):
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    f"[draft_sections] Anthropic overloaded (529) for '{section['section_name']}' "
                    f"— retry {attempt + 1}/{len(_RETRY_DELAYS)} in {delay}s"
                )
                time.sleep(delay)
            else:
                logger.error(f"[draft_sections] Sonnet call failed for '{section['section_name']}': {e}")
                return f"[DRAFT ERROR: {e}]", None
        except Exception as e:
            logger.error(f"[draft_sections] Sonnet call failed for '{section['section_name']}': {e}")
            return f"[DRAFT ERROR: {e}]", None


# ── Justification builder ─────────────────────────────────────────────────────

_MODULE_LABELS = {
    "M1_track_record": "Track Record",
    "M2_expertise_depth": "Expertise Depth",
    "M3_methodology_fit": "Methodology Fit",
    "M4_delivery_credibility": "Delivery Credibility",
    "M5_pricing": "Pricing Proxy",
}


def _build_justifications(
    sections: list[dict],
    primary_scores: dict,
    primary_total: float,
    compliance_score: float,
    robustness_score: float,
    final_score: float,
) -> dict[str, str]:
    # ── Primary: show every module score ──────────────────────────────────────
    module_parts = [
        f"{_MODULE_LABELS.get(k, k)} {v:.0f}"
        for k, v in primary_scores.items()
        if k in _MODULE_LABELS
    ]
    real_modules = {k: v for k, v in primary_scores.items() if k != "M5_pricing"}
    if real_modules:
        best_k = max(real_modules, key=real_modules.get)
        worst_k = min(real_modules, key=real_modules.get)
        strength_line = (
            f"Strongest module: {_MODULE_LABELS.get(best_k, best_k)} "
            f"({real_modules[best_k]:.0f}/100). "
            f"Weakest: {_MODULE_LABELS.get(worst_k, worst_k)} "
            f"({real_modules[worst_k]:.0f}/100)."
        )
    else:
        strength_line = ""
    primary_just = (
        f"{primary_total:.1f}/100 — "
        + (", ".join(module_parts) + ". " if module_parts else "")
        + strength_line
    )

    # ── Compliance: interpret the score ───────────────────────────────────────
    if compliance_score >= 80:
        compliance_note = "Strong — mandatory tender requirements are well covered across drafted sections."
    elif compliance_score >= 65:
        compliance_note = "Moderate — most mandatory requirements addressed; review checklist for gaps before submission."
    else:
        compliance_note = "Needs work — significant mandatory requirements may be missing. Cross-check the compliance checklist section by section."
    compliance_just = f"{compliance_score:.1f}/100 — {compliance_note}"

    # ── Robustness: section confidence breakdown ───────────────────────────────
    high_conf = [s["section_name"] for s in sections if s.get("confidence") == "HIGH"]
    low_conf  = [s["section_name"] for s in sections if s.get("confidence") == "LOW"]
    total = len(sections) or 1
    grounding_line = (
        f"{len(high_conf)}/{total} sections fully grounded in the knowledge base"
        + (f" ({', '.join(high_conf[:3])}{'...' if len(high_conf) > 3 else ''})." if high_conf else ".")
    )
    if low_conf:
        grounding_line += (
            f" {len(low_conf)} section(s) drafted with limited KB support "
            f"({', '.join(low_conf[:3])}{'...' if len(low_conf) > 3 else ''}) — "
            "supplement with specific figures, client names, and measurable outcomes."
        )
    if robustness_score >= 70:
        robust_note = f"Good evidence density. {grounding_line}"
    elif robustness_score >= 50:
        robust_note = f"Moderate evidence density. {grounding_line}"
    else:
        robust_note = f"Low evidence density — drafts lack quantified claims. {grounding_line}"
    robustness_just = f"{robustness_score:.1f}/100 — {robust_note}"

    # ── Final: readiness verdict ───────────────────────────────────────────────
    quality_composite = compliance_score * 0.55 + robustness_score * 0.45
    if final_score >= 75:
        verdict = "Ready for human review and final polish before submission."
    elif final_score >= 60:
        verdict = "Usable first draft — targeted strengthening recommended. See Action Items."
    else:
        verdict = "Significant gaps remain. Address Action Items before submission."
    final_just = (
        f"{final_score:.1f}/100 ({_band(final_score)}) — "
        f"Primary Score {primary_total:.0f} × 60% + Quality Score {quality_composite:.0f} × 40%. "
        + verdict
    )

    return {
        "Primary Score": primary_just,
        "Compliance Coverage": compliance_just,
        "Robustness Index": robustness_just,
        "Final Score": final_just,
    }


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


def _score_compliance(sections: list[dict], checklist: list[dict]) -> tuple[float, dict | None]:
    """Module 6: Haiku rates compliance checklist coverage. Returns (score, usage | None)."""
    if not checklist:
        return 75.0, None

    drafts = _all_drafts(sections)
    if not drafts.strip():
        return 20.0, None

    mandatory = [item["item"] for item in checklist if item.get("mandatory")]
    optional = [item["item"] for item in checklist if not item.get("mandatory")]

    client = _get_client()
    for attempt in range(3):
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
            usage = {"op": "compliance_score", "model": "claude-haiku-4-5-20251001",
                     "input": response.usage.input_tokens, "output": response.usage.output_tokens}
            return min(float(response.content[0].text.strip()), 100.0), usage
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                time.sleep([5, 15][attempt]); continue
            return 60.0, None
        except (ValueError, Exception):
            return 60.0, None


def _score_robustness(sections: list[dict]) -> tuple[float, dict | None]:
    """Module 7: Haiku counts quantified claims. Returns (score, usage | None)."""
    drafts = _all_drafts(sections)
    if not drafts.strip():
        return 20.0, None

    client = _get_client()
    for attempt in range(3):
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
            usage = {"op": "robustness_score", "model": "claude-haiku-4-5-20251001",
                     "input": response.usage.input_tokens, "output": response.usage.output_tokens}
            return max(min(float(response.content[0].text.strip()), 100.0), 0.0), usage
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                time.sleep([5, 15][attempt]); continue
            return 50.0, None
        except (ValueError, Exception):
            return 50.0, None
