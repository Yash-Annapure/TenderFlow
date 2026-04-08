"""
Node: retrieve_context

For each section, calls the retrieval tool with a doc_type filter, then
computes the Primary Score (Modules 1-5).

Module breakdown:
  M1 Track Record        — count of past_tender chunks retrieved (SQL proxy)
  M2 Expertise Depth     — % of doc_types_needed covered by retrieved chunks
  M3 Methodology Fit     — Haiku quality assessment (~400 tokens)
  M4 Delivery Credibility — CV chunk coverage
  M5 Pricing             — neutral 70 when pricing data unavailable

Updates TenderState:
  - retrieved_chunks      (section_id → list of chunk dicts)
  - sections              (confidence and gap_flag updated per section)
  - primary_scores
  - primary_score_total
  - status                → "retrieving"
"""

import logging

import anthropic

from agents.state import STATUS_RETRIEVING, TenderState
from config.settings import settings
from tools.retrieval_tool import retrieve_chunks

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def retrieve_context(state: TenderState) -> dict:
    """Retrieve KB chunks per section and compute primary scoring modules."""
    logger.info(f"[retrieve_context] {len(state['sections'])} sections to retrieve")

    retrieved_chunks: dict[str, list[dict]] = {}

    for section in state["sections"]:
        section_id = section["section_id"]
        doc_types = section.get("doc_types_needed") or None
        query = f"{section['section_name']}: {' '.join(section['requirements'][:3])}"

        chunks = retrieve_chunks(
            query=query,
            doc_types=doc_types,
            threshold=settings.retrieval_threshold,
        )
        retrieved_chunks[section_id] = chunks
        logger.debug(
            f"[retrieve_context] Section '{section_id}': {len(chunks)} chunks retrieved"
        )

    # Update section confidence flags
    updated_sections = []
    for section in state["sections"]:
        updated = dict(section)
        chunks = retrieved_chunks.get(section["section_id"], [])

        if not chunks:
            updated["confidence"] = "LOW"
            updated["gap_flag"] = (
                f"No relevant content found in KB for doc_type(s): "
                f"{', '.join(section.get('doc_types_needed', ['any']))}"
            )
        elif len(chunks) < 2:
            updated["confidence"] = "MEDIUM"
            updated["gap_flag"] = None
        else:
            updated["confidence"] = "HIGH"
            updated["gap_flag"] = None

        updated_sections.append(updated)

    # Compute primary scores
    primary_scores = _compute_primary_scores(state, retrieved_chunks)
    weights = state.get("dimension_weights", {})

    module_weight_map = {
        "M1_track_record": weights.get("W1_track_record", 0.25),
        "M2_expertise_depth": weights.get("W2_expertise_depth", 0.25),
        "M3_methodology_fit": weights.get("W3_methodology_fit", 0.20),
        "M4_delivery_credibility": weights.get("W4_delivery_credibility", 0.20),
        "M5_pricing": weights.get("W5_pricing_competitiveness", 0.10),
    }

    weight_sum = sum(module_weight_map.values()) or 1.0
    primary_total = min(
        sum(
            primary_scores.get(k, 0) * w
            for k, w in module_weight_map.items()
        ) / weight_sum,
        100.0,
    )

    logger.info(f"[retrieve_context] Primary score: {primary_total:.1f}")

    return {
        "retrieved_chunks": retrieved_chunks,
        "sections": updated_sections,
        "primary_scores": primary_scores,
        "primary_score_total": primary_total,
        "status": STATUS_RETRIEVING,
    }


# ── Primary Scoring Modules ───────────────────────────────────────────────────

def _compute_primary_scores(state: TenderState, retrieved_chunks: dict) -> dict[str, float]:
    scores: dict[str, float] = {}

    # M1: Track Record — past tender chunks retrieved
    past_chunks = sum(
        len([c for c in chunks if c.get("doc_type") == "past_tender"])
        for chunks in retrieved_chunks.values()
    )
    scores["M1_track_record"] = min(past_chunks * 15.0, 100.0)

    # M2: Expertise Depth — doc_type coverage across all section needs
    total_needed = sum(len(s.get("doc_types_needed", [])) for s in state["sections"])
    if total_needed > 0:
        covered = sum(
            len(
                [
                    c
                    for c in retrieved_chunks.get(s["section_id"], [])
                    if c.get("doc_type") in s.get("doc_types_needed", [])
                ]
            )
            for s in state["sections"]
        )
        scores["M2_expertise_depth"] = min((covered / total_needed) * 100.0, 100.0)
    else:
        scores["M2_expertise_depth"] = 50.0

    # M3: Methodology Fit — Haiku assessment
    methodology_chunks: list[dict] = []
    for chunks in retrieved_chunks.values():
        methodology_chunks.extend(c for c in chunks if c.get("doc_type") == "methodology")
    scores["M3_methodology_fit"] = _score_methodology_fit(
        methodology_chunks, state.get("tender_text", "")[:1000]
    )

    # M4: Delivery Credibility — CV coverage
    cv_chunks = sum(
        len([c for c in chunks if c.get("doc_type") == "cv"])
        for chunks in retrieved_chunks.values()
    )
    scores["M4_delivery_credibility"] = min(cv_chunks * 20.0, 100.0)

    # M5: Pricing — neutral when no pricing data in KB
    scores["M5_pricing"] = 70.0

    return scores


def _score_methodology_fit(methodology_chunks: list[dict], tender_excerpt: str) -> float:
    """Haiku: 0-100 methodology fit score (~400 tokens)."""
    if not methodology_chunks:
        return 30.0

    client = _get_client()
    methodology_text = "\n\n".join(
        c.get("chunk_text", "") for c in methodology_chunks[:3]
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Rate how well this methodology fits the tender requirements. "
                        "Score 0-100. Respond with only a number.\n\n"
                        f"Tender excerpt:\n{tender_excerpt[:500]}\n\n"
                        f"Methodology:\n{methodology_text[:1000]}"
                    ),
                }
            ],
        )
        return float(response.content[0].text.strip())
    except (ValueError, Exception):
        return 50.0
