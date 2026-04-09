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
import re

import anthropic

from agents.state import STATUS_RETRIEVING, TenderState
from config.settings import settings
from core.embeddings import embed_queries, embed_query
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
    _token_usage: list[dict] = []

    tender_excerpt = state.get("tender_text") or ""
    queries = [_build_section_query(s, tender_excerpt) for s in state["sections"]]

    # Single batch call — all sections embedded together
    query_embeddings = embed_queries(queries)

    client = _get_client()

    for i, section in enumerate(state["sections"]):
        section_id = section["section_id"]
        doc_types = section.get("doc_types_needed") or None

        chunks = retrieve_chunks(
            query=queries[i],
            doc_types=doc_types,
            threshold=settings.retrieval_threshold,
            query_embedding=query_embeddings[i],
        )

        # Fallback 1: drop doc_type filter, lower threshold (no extra LLM cost, 1 extra RPC)
        if not chunks:
            logger.info(
                f"[retrieve_context] '{section_id}': 0 chunks at primary threshold="
                f"{settings.retrieval_threshold}, fallback-1 (all doc_types, threshold=0.35)"
            )
            chunks = retrieve_chunks(
                query=queries[i],
                doc_types=None,
                threshold=0.35,
                top_k=4,
                query_embedding=query_embeddings[i],
            )

        # Fallback 2: HyDE — Haiku generates a hypothetical KB passage, re-embed and retry.
        # Only fires when fallback-1 also returns 0. ~300 Haiku tokens per affected section.
        if not chunks:
            logger.info(
                f"[retrieve_context] '{section_id}': fallback-1 empty, running HyDE"
            )
            hyde_passage, hyde_usage = _generate_hyde_passage(
                client,
                section.get("section_name", ""),
                section.get("requirements") or [],
                tender_excerpt,
            )
            if hyde_usage:
                _token_usage.append(hyde_usage)
            hyde_embedding = embed_query(hyde_passage)
            chunks = retrieve_chunks(
                query=hyde_passage,
                doc_types=None,
                threshold=0.30,
                top_k=4,
                query_embedding=hyde_embedding,
            )
            if chunks:
                logger.info(
                    f"[retrieve_context] '{section_id}': HyDE recovered {len(chunks)} chunks"
                )

        chunks, rerank_usage = _rerank_chunks(
            client,
            section.get("section_name", ""),
            section.get("requirements") or [],
            chunks,
        )
        if rerank_usage:
            _token_usage.append(rerank_usage)

        retrieved_chunks[section_id] = chunks
        logger.debug(
            f"[retrieve_context] Section '{section_id}': {len(chunks)} chunks after rerank"
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

    # Compute primary scores (includes _effective_weights sentinel)
    primary_scores = _compute_primary_scores(state, retrieved_chunks)
    effective_weights: dict = primary_scores.pop("_effective_weights", {})

    weight_sum = sum(effective_weights.values()) or 1.0
    primary_total = min(
        sum(primary_scores.get(k, 0) * effective_weights.get(k, 0)
            for k in primary_scores) / weight_sum,
        100.0,
    )

    logger.info(f"[retrieve_context] Primary score: {primary_total:.1f}")

    return {
        "retrieved_chunks": retrieved_chunks,
        "sections": updated_sections,
        "primary_scores": primary_scores,
        "primary_score_total": primary_total,
        "status": STATUS_RETRIEVING,
        "token_usage": _token_usage,
    }


# ── Query Formulation ─────────────────────────────────────────────────────────

def _build_section_query(section: dict, tender_excerpt: str) -> str:
    """
    Build a rich embedding query for a section.
    Uses all requirements (not just first 3) plus a tender excerpt for context.
    """
    all_reqs = " | ".join(section.get("requirements") or [])
    return (
        f"{section.get('section_name', '')}: {all_reqs}"
        f"\nTender context: {tender_excerpt[:300]}"
    )


def _generate_hyde_passage(
    client: anthropic.Anthropic,
    section_name: str,
    requirements: list[str],
    tender_excerpt: str,
) -> tuple[str, dict | None]:
    """
    HyDE: generate a short hypothetical KB chunk that would answer this section.
    Returns (passage, usage_dict | None).
    """
    reqs = "; ".join(requirements[:4])
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "Write a concise 3-sentence description of past work or methodology "
                    "relevant to this proposal section. Be specific and technical. "
                    "Write as if from a past project document.\n\n"
                    f"Section: {section_name}\n"
                    f"Requirements: {reqs}\n"
                    f"Tender context: {tender_excerpt[:200]}"
                ),
            }],
        )
        usage = {"op": "hyde", "model": "claude-haiku-4-5-20251001",
                 "input": response.usage.input_tokens, "output": response.usage.output_tokens}
        return response.content[0].text.strip(), usage
    except Exception as e:
        logger.warning(f"[hyde] Haiku call failed for '{section_name}': {e} — using plain query")
        return f"{section_name}: {reqs}", None


def _rerank_chunks(
    client: anthropic.Anthropic,
    section_name: str,
    requirements: list[str],
    chunks: list[dict],
    top_n: int = 4,
) -> tuple[list[dict], dict | None]:
    """
    Score each chunk 0-10 with Haiku, sort descending, return top_n.
    Returns (ranked_chunks, usage_dict | None).
    """
    if not chunks:
        return chunks, None

    reqs_text = "; ".join(requirements[:5])
    numbered = "\n".join(
        f"{i}. [{c.get('doc_type', 'doc')}] {c.get('chunk_text', '')[:200]}"
        for i, c in enumerate(chunks)
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Section: {section_name}\n"
                        f"Requirements: {reqs_text}\n\n"
                        f"Rate each chunk's relevance 0-10:\n{numbered}\n\n"
                        "Respond with ONLY comma-separated integers, one per chunk. Example: 8,3,7"
                    ),
                }
            ],
        )
        usage = {"op": "rerank", "model": "claude-haiku-4-5-20251001",
                 "input": response.usage.input_tokens, "output": response.usage.output_tokens}
        scores_text = response.content[0].text.strip()
        raw_tokens = re.split(r"[,\s]+", scores_text)
        scores = [float(t) for t in raw_tokens if t]

        if len(scores) != len(chunks):
            logger.warning(
                f"[rerank] Score count mismatch ({len(scores)} vs {len(chunks)}) "
                f"for '{section_name}', using original order truncated to {top_n}"
            )
            return chunks[:top_n], usage

        scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        kept = [c for _, c in scored[:top_n]]
        logger.debug(
            f"[rerank] '{section_name}': {len(chunks)} → {len(kept)} chunks "
            f"(top scores: {[round(s, 1) for s, _ in scored[:top_n]]})"
        )
        return kept, usage

    except (ValueError, IndexError) as e:
        logger.warning(f"[rerank] Could not parse Haiku scores for '{section_name}': {e!r}")
        return chunks[:top_n], None
    except Exception as e:
        logger.warning(f"[rerank] Haiku call failed for '{section_name}': {e} — using top {top_n} by similarity")
        return chunks[:top_n], None


# ── Primary Scoring Modules ───────────────────────────────────────────────────

def _compute_primary_scores(state: TenderState, retrieved_chunks: dict) -> dict[str, float]:
    scores: dict[str, float] = {}

    # M1: Track Record — similarity-weighted past tender coverage
    # Avg similarity is the primary quality driver; count provides a sub-linear
    # volume bonus (square-root dampened, saturates at 5 chunks) so a single
    # high-similarity chunk scores better than several low-similarity ones.
    past_sims = [
        c.get("similarity", 0.5)
        for chunks in retrieved_chunks.values()
        for c in chunks
        if c.get("doc_type") == "past_tender"
    ]
    if past_sims:
        avg_sim = sum(past_sims) / len(past_sims)
        count_factor = min(len(past_sims) / 5.0, 1.0) ** 0.5
        scores["M1_track_record"] = min(avg_sim * count_factor * 100.0, 100.0)
    else:
        scores["M1_track_record"] = 0.0

    # M2: Expertise Depth — avg quality of best-retrieved chunk per section.
    # Measures whether retrieval can actually serve content for each section.
    # Doc_type agnostic: M1 captures past_tender quality, M4 captures CV quality.
    # Empty section → 0.0 (genuine retrieval gap, penalise).
    section_best_sims = []
    for s in state["sections"]:
        chunks = retrieved_chunks.get(s["section_id"], [])
        if chunks:
            section_best_sims.append(max(c.get("similarity", 0.0) for c in chunks))
        else:
            section_best_sims.append(0.0)
    scores["M2_expertise_depth"] = (
        (sum(section_best_sims) / len(section_best_sims)) * 100.0
        if section_best_sims else 50.0
    )

    # M3: Methodology Fit — Haiku assessment (neutral 50 when no methodology in KB)
    methodology_chunks: list[dict] = []
    for chunks in retrieved_chunks.values():
        methodology_chunks.extend(c for c in chunks if c.get("doc_type") == "methodology")
    scores["M3_methodology_fit"] = _score_methodology_fit(
        methodology_chunks, state.get("tender_text", "")[:1000]
    )

    # M4: Delivery Credibility — similarity-weighted CV coverage.
    # 50 = neutral/unknown (no CVs in KB at all — three-layer fallback confirms absence).
    # 0 is never emitted for missing doc_type — that conflates "bad team" with "no data".
    cv_sims = [
        c.get("similarity", 0.5)
        for chunks in retrieved_chunks.values()
        for c in chunks
        if c.get("doc_type") == "cv"
    ]
    if cv_sims:
        avg_sim = sum(cv_sims) / len(cv_sims)
        count_factor = min(len(cv_sims) / 4.0, 1.0) ** 0.5
        # Scale to 50-100: having any CV is always above neutral.
        # quality=1.0 (4 high-sim CVs) → 100; quality=0.4 (1 mid-sim CV) → 70.
        quality = avg_sim * count_factor
        scores["M4_delivery_credibility"] = min(50.0 + quality * 50.0, 100.0)
    else:
        scores["M4_delivery_credibility"] = 50.0  # neutral: absent from KB, not assessed

    # M5: Pricing — neutral when no pricing data in KB
    scores["M5_pricing"] = 70.0

    # ── Weight reallocation ───────────────────────────────────────────────────
    # When a doc_type is absent from KB, its module gets a neutral score (50).
    # But neutral scores at 20% weight each structurally cap primary at ~67.
    # Redistribute absent-module weights to modules that have real data,
    # so the score reflects actual KB strength rather than penalising missing content.
    kb_has_cv = bool(cv_sims)
    kb_has_methodology = bool(methodology_chunks)

    base = state.get("dimension_weights") or {}
    w = {
        "M1_track_record":         base.get("W1_track_record", 0.25),
        "M2_expertise_depth":      base.get("W2_expertise_depth", 0.25),
        "M3_methodology_fit":      base.get("W3_methodology_fit", 0.20),
        "M4_delivery_credibility": base.get("W4_delivery_credibility", 0.20),
        "M5_pricing":              base.get("W5_pricing_competitiveness", 0.10),
    }

    unassessable = []
    if not kb_has_methodology:
        unassessable.append("M3_methodology_fit")
    if not kb_has_cv:
        unassessable.append("M4_delivery_credibility")

    if unassessable:
        freed = sum(w[k] for k in unassessable)
        assessed = [k for k in w if k not in unassessable]
        assessed_total = sum(w[k] for k in assessed) or 1.0
        for k in unassessable:
            w[k] = 0.0
        for k in assessed:
            w[k] += freed * (w[k] / assessed_total)

    scores["_effective_weights"] = w  # consumed by caller, not stored in TenderState
    return scores


def _score_methodology_fit(methodology_chunks: list[dict], tender_excerpt: str) -> float:
    """
    Score methodology fit as average cosine similarity of retrieved methodology chunks.

    Each chunk's `similarity` (0-1, from pgvector RPC) captures semantic alignment
    with the section query which incorporates tender context. Averaging and scaling
    to 0-100 gives a deterministic, free, consistent M3 score.

    Returns 50.0 (neutral) when no methodology chunks exist in the KB.
    """
    if not methodology_chunks:
        return 50.0  # neutral — absent from KB, not penalised

    sims = [c.get("similarity", 0.0) for c in methodology_chunks]
    avg_sim = sum(sims) / len(sims)
    return round(min(avg_sim * 100.0, 100.0), 1)
