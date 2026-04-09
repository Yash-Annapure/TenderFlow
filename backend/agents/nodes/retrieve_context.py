"""
Node: retrieve_context

Retrieval strategy (revised for fixed 7-section format):

The 7 mandatory response sections are structural templates, not tender topics.
A query of "Executive Summary: Introduce Meridian..." finds nothing in the KB.
Instead retrieval is driven by:

  1. Tender-context extraction  — one Haiku call extracts the domain, contracting
     authority, key regulations/topics, and required skills from the raw tender text.

  2. Per-section query templates — each section_id has its own pair of query
     templates that describe *what KB content feeds that section*, parameterised
     with the extracted tender context.

  3. Multi-angle retrieval + merge — two queries per section are embedded in one
     batch call, each query retrieves independently, results are merged and
     deduplicated by chunk identity keeping the higher similarity score.

  4. Three-tier fallback
       Tier-1  narrow doc_type + primary threshold
       Tier-2  all doc_types, lower threshold (0.35)
       Tier-3  HyDE — Haiku generates a hypothetical KB passage for re-embedding

  5. Haiku rerank — scores each candidate chunk 0-10 against section requirements
     plus the extracted tender domain for precision.

Updates TenderState:
  - retrieved_chunks      (section_id → list of chunk dicts)
  - sections              (confidence and gap_flag updated per section)
  - primary_scores
  - primary_score_total
  - status                → "retrieving"
"""

import logging
import re
import time

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


# ── Per-section query templates ────────────────────────────────────────────────
# Each section has two query angles:
#   q1 — primary KB focus (matches the dominant doc_type for that section)
#   q2 — secondary angle (broader or domain-enriched)
# Placeholders: {domain} {authority} {keywords} {skills} {deliverables}

_SECTION_QUERY_TEMPLATES: dict[str, list[str]] = {
    "executive_summary": [
        "{domain} past project track record deliverables {authority}",
        "company capabilities overview {keywords} EU institutional proposal",
    ],
    "problem_framing": [
        "{domain} problem analysis regulatory gap research approach",
        "{keywords} identification challenge market mapping EU policy",
    ],
    "entity_typology": [
        "{domain} entity classification typology framework {keywords}",
        "{domain} provider categories sector taxonomy classification approach",
    ],
    "methodology": [
        "{domain} methodology data pipeline analytical framework {keywords}",
        "{keywords} identification scoring research method quantitative",
    ],
    "deliverables": [
        "{domain} project deliverables dataset report milestones {authority}",
        "{keywords} output work plan timeline EU institutional contract",
    ],
    "team": [
        "{skills} expert consultant team {domain}",
        "CV analyst data scientist regulatory specialist {domain}",
    ],
    "price": [
        "budget cost estimate {domain} EU tender staff days pricing",
        "cost breakdown infrastructure data consultancy {keywords} proposal",
    ],
}

# Fallback for any section_id not in the table above
_DEFAULT_QUERY_TEMPLATES = [
    "{domain} {keywords} EU institutional tender",
    "{domain} methodology deliverables {authority}",
]


def _fill_template(template: str, ctx: dict) -> str:
    """Substitute context placeholders in a query template."""
    return (
        template
        .replace("{domain}", ctx.get("domain", ""))
        .replace("{authority}", ctx.get("authority", ""))
        .replace("{keywords}", " ".join(ctx.get("keywords", [])[:5]))
        .replace("{skills}", " ".join(ctx.get("skills", [])[:4]))
        .replace("{deliverables}", " ".join(ctx.get("deliverables", [])[:3]))
        .strip()
    )


def _build_section_queries(section: dict, tender_ctx: dict) -> list[str]:
    """Return 2 retrieval queries for a section, grounded in the tender context."""
    templates = _SECTION_QUERY_TEMPLATES.get(
        section["section_id"], _DEFAULT_QUERY_TEMPLATES
    )
    queries = [_fill_template(t, tender_ctx) for t in templates]

    # Append requirements as a third query so specific tender asks are covered
    reqs = " | ".join((section.get("requirements") or [])[:3])
    if reqs:
        queries.append(
            f"{tender_ctx.get('domain', '')} {tender_ctx.get('authority', '')} {reqs}"[:300]
        )

    return queries


# ── Main node ──────────────────────────────────────────────────────────────────

def retrieve_context(state: TenderState) -> dict:
    """Retrieve KB chunks per section and compute primary scoring modules."""
    logger.info(f"[retrieve_context] {len(state['sections'])} sections to retrieve")

    tender_text = state.get("tender_text") or ""
    client = _get_client()
    _token_usage: list[dict] = []

    # Step 1 ── extract tender domain context (1 Haiku call ~150 tokens)
    tender_ctx, ctx_usage = _extract_tender_context(client, tender_text)
    if ctx_usage:
        _token_usage.append(ctx_usage)
    logger.info(
        f"[retrieve_context] Tender context: domain='{tender_ctx['domain']}' "
        f"authority='{tender_ctx['authority']}' keywords={tender_ctx['keywords']}"
    )

    # Step 2 ── build per-section query lists
    section_queries: dict[str, list[str]] = {}
    for section in state["sections"]:
        section_queries[section["section_id"]] = _build_section_queries(section, tender_ctx)

    # Step 3 ── batch embed ALL queries in one API call
    all_query_texts: list[str] = []
    query_spans: dict[str, tuple[int, int]] = {}
    for sid, queries in section_queries.items():
        start = len(all_query_texts)
        all_query_texts.extend(queries)
        query_spans[sid] = (start, start + len(queries))

    all_embeddings = embed_queries(all_query_texts)

    # Step 4 ── multi-angle retrieval + merge per section
    retrieved_chunks: dict[str, list[dict]] = {}

    for section in state["sections"]:
        sid = section["section_id"]
        doc_types = section.get("doc_types_needed") or None
        start, end = query_spans[sid]
        queries = all_query_texts[start:end]
        embeddings = all_embeddings[start:end]

        # Primary retrieval: each query angle → merge, dedup by best similarity
        merged: dict[str, dict] = {}
        for query, emb in zip(queries, embeddings):
            chunks = retrieve_chunks(
                query=query,
                doc_types=doc_types,
                threshold=settings.retrieval_threshold,
                query_embedding=emb,
            )
            for c in chunks:
                # Dedup key: prefer explicit id, fall back to text fingerprint
                cid = str(c.get("id") or c.get("chunk_id") or
                          f"{c.get('source_name','')}|{(c.get('chunk_text') or '')[:60]}")
                if cid not in merged or c.get("similarity", 0) > merged[cid].get("similarity", 0):
                    merged[cid] = c

        chunks = list(merged.values())
        # Sort by similarity desc for consistent ordering before rerank
        chunks.sort(key=lambda x: x.get("similarity", 0), reverse=True)

        # Fallback Tier-1 ── drop doc_type filter + lower threshold
        if not chunks:
            logger.info(
                f"[retrieve_context] '{sid}': 0 chunks with doc_type filter, "
                "falling back to all doc_types threshold=0.35"
            )
            for query, emb in zip(queries[:2], embeddings[:2]):
                fb = retrieve_chunks(
                    query=query,
                    doc_types=None,
                    threshold=0.35,
                    top_k=4,
                    query_embedding=emb,
                )
                for c in fb:
                    cid = str(c.get("id") or c.get("chunk_id") or
                              f"{c.get('source_name','')}|{(c.get('chunk_text') or '')[:60]}")
                    if cid not in merged or c.get("similarity", 0) > merged[cid].get("similarity", 0):
                        merged[cid] = c
            chunks = sorted(merged.values(), key=lambda x: x.get("similarity", 0), reverse=True)

        # Fallback Tier-2 ── HyDE
        if not chunks:
            logger.info(f"[retrieve_context] '{sid}': fallback-1 empty, running HyDE")
            hyde_passage, hyde_usage = _generate_hyde_passage(
                client, section, tender_ctx
            )
            if hyde_usage:
                _token_usage.append(hyde_usage)
            hyde_emb = embed_query(hyde_passage)
            chunks = retrieve_chunks(
                query=hyde_passage,
                doc_types=None,
                threshold=0.30,
                top_k=4,
                query_embedding=hyde_emb,
            )
            if chunks:
                logger.info(f"[retrieve_context] '{sid}': HyDE recovered {len(chunks)} chunks")

        # Rerank: Haiku scores each chunk against requirements + tender domain
        chunks, rerank_usage = _rerank_chunks(client, section, tender_ctx, chunks)
        if rerank_usage:
            _token_usage.append(rerank_usage)

        retrieved_chunks[sid] = chunks
        logger.debug(f"[retrieve_context] '{sid}': {len(chunks)} chunks after rerank")

    # Step 5 ── update section confidence flags
    updated_sections = []
    for section in state["sections"]:
        updated = dict(section)
        chunks = retrieved_chunks.get(section["section_id"], [])
        if not chunks:
            updated["confidence"] = "LOW"
            updated["gap_flag"] = (
                f"No relevant KB content found for "
                f"{', '.join(section.get('doc_types_needed', ['any']))} "
                f"in domain: {tender_ctx.get('domain', 'this tender')}"
            )
        elif len(chunks) < 2:
            updated["confidence"] = "MEDIUM"
            updated["gap_flag"] = None
        else:
            updated["confidence"] = "HIGH"
            updated["gap_flag"] = None
        updated_sections.append(updated)

    # Step 6 ── primary scoring
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


# ── Tender context extraction ──────────────────────────────────────────────────

def _extract_tender_context(
    client: anthropic.Anthropic,
    tender_text: str,
) -> tuple[dict, dict | None]:
    """
    One Haiku call (~150 output tokens) to extract:
      domain       — 3-5 word topic label
      authority    — contracting body name
      keywords     — 6 technical/regulatory terms
      skills       — 5 professional skills implied by the tender
      deliverables — 3 expected output types

    Returns (context_dict, usage_dict | None).
    Falls back to keyword extraction from text on failure.
    """
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": (
                        "Extract the following from this tender document. "
                        "Respond in the exact format shown — no other text.\n\n"
                        "domain: <3-5 word topic, e.g. 'ICT provider DORA mapping'>\n"
                        "authority: <contracting body, e.g. 'EBA'>\n"
                        "keywords: <6 comma-separated technical/regulatory terms>\n"
                        "skills: <5 comma-separated professional skills needed>\n"
                        "deliverables: <3 comma-separated output types, e.g. 'dataset,report,analysis'>\n\n"
                        f"Tender:\n{tender_text[:2000]}"
                    ),
                }],
            )
            usage = {
                "op": "tender_context_extract",
                "model": "claude-haiku-4-5-20251001",
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            }
            ctx = _parse_context_response(response.content[0].text)
            return ctx, usage

        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                time.sleep([5, 15][attempt])
                continue
            logger.warning(f"[tender_context] Haiku failed ({e}), using fallback extraction")
            return _fallback_context(tender_text), None
        except Exception as e:
            logger.warning(f"[tender_context] Haiku failed ({e}), using fallback extraction")
            return _fallback_context(tender_text), None

    return _fallback_context(tender_text), None


def _parse_context_response(text: str) -> dict:
    """Parse key: value lines from the Haiku context response."""
    result: dict = {"domain": "", "authority": "", "keywords": [], "skills": [], "deliverables": []}
    for line in text.strip().splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "domain":
            result["domain"] = val
        elif key == "authority":
            result["authority"] = val
        elif key == "keywords":
            result["keywords"] = [k.strip() for k in val.split(",") if k.strip()]
        elif key == "skills":
            result["skills"] = [s.strip() for s in val.split(",") if s.strip()]
        elif key == "deliverables":
            result["deliverables"] = [d.strip() for d in val.split(",") if d.strip()]
    return result


def _fallback_context(tender_text: str) -> dict:
    """Simple regex-based fallback when Haiku is unavailable."""
    words = re.findall(r'\b[A-Z][A-Z0-9]{2,}\b', tender_text[:3000])
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    keywords = [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:6]]
    return {
        "domain": "EU institutional tender",
        "authority": "",
        "keywords": keywords,
        "skills": ["regulatory", "data analysis", "project management", "research", "technical"],
        "deliverables": ["report", "dataset", "analysis"],
    }


# ── HyDE ───────────────────────────────────────────────────────────────────────

def _generate_hyde_passage(
    client: anthropic.Anthropic,
    section: dict,
    tender_ctx: dict,
) -> tuple[str, dict | None]:
    """
    HyDE: generate a hypothetical KB chunk that would answer this section.
    Uses tender domain context for specificity.
    Returns (passage, usage_dict | None).
    """
    reqs = "; ".join((section.get("requirements") or [])[:3])
    domain = tender_ctx.get("domain", "")
    keywords = ", ".join(tender_ctx.get("keywords", [])[:4])

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": (
                        "Write a concise 3-sentence excerpt from a past project document "
                        f"relevant to this tender section. Domain: {domain}. "
                        f"Key topics: {keywords}. Be specific and technical.\n\n"
                        f"Section: {section.get('section_name', '')}\n"
                        f"Requirements: {reqs}"
                    ),
                }],
            )
            usage = {
                "op": "hyde",
                "model": "claude-haiku-4-5-20251001",
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            }
            return response.content[0].text.strip(), usage
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                time.sleep([5, 15][attempt])
                continue
            fallback = f"{domain} {section.get('section_name', '')} {reqs}"
            logger.warning(f"[hyde] Failed for '{section.get('section_id')}': {e}")
            return fallback, None
        except Exception as e:
            fallback = f"{domain} {section.get('section_name', '')} {reqs}"
            logger.warning(f"[hyde] Failed for '{section.get('section_id')}': {e}")
            return fallback, None

    return f"{domain} {section.get('section_name', '')}", None


# ── Reranker ───────────────────────────────────────────────────────────────────

def _rerank_chunks(
    client: anthropic.Anthropic,
    section: dict,
    tender_ctx: dict,
    chunks: list[dict],
    top_n: int = 4,
) -> tuple[list[dict], dict | None]:
    """
    Haiku rates each chunk 0-10 for relevance to the section + tender domain.
    Returns (top_n ranked chunks, usage_dict | None).
    """
    if not chunks:
        return chunks, None

    section_name = section.get("section_name", "")
    reqs_text = "; ".join((section.get("requirements") or [])[:4])
    domain = tender_ctx.get("domain", "")
    numbered = "\n".join(
        f"{i}. [{c.get('doc_type', 'doc')}] {(c.get('chunk_text') or '')[:200]}"
        for i, c in enumerate(chunks)
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    f"Tender domain: {domain}\n"
                    f"Section: {section_name}\n"
                    f"Requirements: {reqs_text}\n\n"
                    f"Rate each chunk's relevance 0-10:\n{numbered}\n\n"
                    "Respond with ONLY comma-separated integers, one per chunk. Example: 8,3,7"
                ),
            }],
        )
        usage = {
            "op": "rerank",
            "model": "claude-haiku-4-5-20251001",
            "input": response.usage.input_tokens,
            "output": response.usage.output_tokens,
        }
        scores_text = response.content[0].text.strip()
        raw_tokens = re.split(r"[,\s]+", scores_text)
        scores = [float(t) for t in raw_tokens if t]

        if len(scores) != len(chunks):
            logger.warning(
                f"[rerank] Score count mismatch ({len(scores)} vs {len(chunks)}) "
                f"for '{section_name}', using original order"
            )
            return chunks[:top_n], usage

        scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        # Store normalised rerank score (0–1) in each chunk for use in primary scoring
        kept = []
        for rk_score, c in scored[:top_n]:
            c = dict(c)
            c["rerank_score"] = rk_score / 10.0   # normalise 0-10 → 0-1
            kept.append(c)
        logger.debug(
            f"[rerank] '{section_name}': {len(chunks)} → {len(kept)} "
            f"(top scores: {[round(s, 1) for s, _ in scored[:top_n]]})"
        )
        return kept, usage

    except (ValueError, IndexError) as e:
        logger.warning(f"[rerank] Score parse failed for '{section_name}': {e!r}")
        return chunks[:top_n], None
    except Exception as e:
        logger.warning(f"[rerank] Haiku failed for '{section_name}': {e}")
        return chunks[:top_n], None


# ── Primary Scoring ────────────────────────────────────────────────────────────

def _blended_score(c: dict) -> float:
    """Blend cosine similarity (60%) with normalised rerank score (40%).
    If no rerank score available, fall back to similarity only."""
    sim = c.get("similarity", 0.5)
    rk  = c.get("rerank_score")          # 0–1, set by _rerank_chunks
    if rk is None:
        return sim
    return 0.60 * sim + 0.40 * rk


def _compute_primary_scores(state: TenderState, retrieved_chunks: dict) -> dict[str, float]:
    scores: dict[str, float] = {}

    # M1: Track Record — rerank-blended past tender coverage
    past_chunks = [
        c
        for chunks in retrieved_chunks.values()
        for c in chunks
        if c.get("doc_type") == "past_tender"
    ]
    if past_chunks:
        blended = [_blended_score(c) for c in past_chunks]
        avg_blended  = sum(blended) / len(blended)
        count_factor = min(len(blended) / 5.0, 1.0) ** 0.5
        scores["M1_track_record"] = min(avg_blended * count_factor * 100.0, 100.0)
    else:
        scores["M1_track_record"] = 0.0

    # M2: Expertise Depth — best blended score per section, averaged across sections
    section_best = []
    for s in state["sections"]:
        chunks = retrieved_chunks.get(s["section_id"], [])
        if chunks:
            section_best.append(max(_blended_score(c) for c in chunks))
        else:
            section_best.append(0.0)
    scores["M2_expertise_depth"] = (
        (sum(section_best) / len(section_best)) * 100.0
        if section_best else 50.0
    )

    # M3: Methodology Fit — blended score of methodology chunks
    methodology_chunks = [
        c
        for chunks in retrieved_chunks.values()
        for c in chunks
        if c.get("doc_type") == "methodology"
    ]
    scores["M3_methodology_fit"] = _score_methodology_fit(methodology_chunks)

    # M4: Delivery Credibility — CV coverage; floor is 0 (no CVs → no credit)
    cv_chunks = [
        c
        for chunks in retrieved_chunks.values()
        for c in chunks
        if c.get("doc_type") == "cv"
    ]
    if cv_chunks:
        blended     = [_blended_score(c) for c in cv_chunks]
        avg_blended = sum(blended) / len(blended)
        count_factor = min(len(blended) / 4.0, 1.0) ** 0.5
        scores["M4_delivery_credibility"] = min(avg_blended * count_factor * 100.0, 100.0)
    else:
        scores["M4_delivery_credibility"] = 0.0   # was 50 — dishonest floor removed

    # M5: Pricing — derive from budget match between tender and drafted price section
    scores["M5_pricing"] = _score_pricing(state, retrieved_chunks)

    # Weight reallocation for absent doc_types
    kb_has_cv          = bool(cv_chunks)
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

    scores["_effective_weights"] = w
    return scores


def _score_methodology_fit(methodology_chunks: list[dict]) -> float:
    """Blended rerank+similarity score of methodology chunks scaled to 0-100."""
    if not methodology_chunks:
        return 50.0
    blended = [_blended_score(c) for c in methodology_chunks]
    return round(min(sum(blended) / len(blended) * 100.0, 100.0), 1)


def _score_pricing(state: TenderState, retrieved_chunks: dict) -> float:
    """
    M5: Compare drafted Price section TOTAL against the tender's stated budget.
    Returns 0-100 based on how close the bid is to the tender's expected value.
    Falls back to 65 if either figure cannot be parsed.
    """
    import re as _re

    def _extract_eur(text: str) -> float | None:
        """Return first EUR amount found (millions or raw), or None."""
        # e.g. EUR 3.2M, €3,200,000, 3.2 million EUR
        m = _re.search(
            r'(?:EUR|€)\s*([\d,\.]+)\s*[Mm](?:illion)?|'
            r'([\d,\.]+)\s*[Mm](?:illion)?\s*(?:EUR|€)|'
            r'(?:EUR|€)\s*([\d\.,]+)',
            text, _re.IGNORECASE
        )
        if not m:
            return None
        raw = next(g for g in m.groups() if g is not None)
        raw = raw.replace(',', '')
        val = float(raw)
        # heuristic: if < 1000 assume millions
        return val * 1_000_000 if val < 10_000 else val

    # Get tender budget from the price section tender extract
    tender_text = state.get("tender_text", "")
    tender_budget = _extract_eur(tender_text[-6000:])   # budget usually near the end

    # Get bid total from the drafted price section
    price_section = next(
        (s for s in state.get("sections", []) if s.get("section_id") == "price"),
        None
    )
    draft_price_text = (
        (price_section or {}).get("draft_text") or ""
    )
    bid_total = _extract_eur(draft_price_text)

    if tender_budget and bid_total and tender_budget > 0:
        deviation = abs(bid_total - tender_budget) / tender_budget
        # <5% deviation → 95, <15% → ~80, <30% → ~55, >50% → 30
        score = max(30.0, 100.0 - deviation * 230.0)
        logger.debug(
            f"[M5] tender_budget={tender_budget/1e6:.2f}M  "
            f"bid={bid_total/1e6:.2f}M  deviation={deviation:.1%}  score={score:.1f}"
        )
        return round(score, 1)

    # No budget parseable — neutral but not inflated
    return 65.0
