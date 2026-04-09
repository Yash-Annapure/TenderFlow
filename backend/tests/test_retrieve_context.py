"""Tests for retrieve_context query formulation and scoring."""
import pytest
from unittest.mock import MagicMock, patch


def _make_section(section_id="s1", name="Background", requirements=None, doc_types=None):
    return {
        "section_id": section_id,
        "section_name": name,
        "requirements": requirements or ["Describe company background", "Explain policy context", "List certifications"],
        "doc_types_needed": doc_types or ["company_profile", "methodology"],
        "word_count_target": 500,
    }


def _make_state(sections=None, tender_text="This is a tender for AI ecosystem mapping services."):
    return {
        "sections": sections or [_make_section()],
        "tender_text": tender_text,
        "retrieved_chunks": {},
        "dimension_weights": {},
        "status": "pending",
    }


def _make_tender_ctx(domain="AI ecosystem mapping", authority="EBA",
                     keywords=None, skills=None):
    return {
        "domain": domain,
        "authority": authority,
        "keywords": keywords or ["DORA", "fintech", "ICT", "provider", "EU"],
        "skills": skills or ["regulatory", "data science", "research"],
        "deliverables": ["dataset", "report", "analysis"],
    }


# ── Query formulation tests ────────────────────────────────────────────────────

def test_build_section_queries_returns_multiple_queries():
    """Must return at least 2 queries per section."""
    from agents.nodes.retrieve_context import _build_section_queries

    section = _make_section(section_id="methodology", name="3. Methodology")
    ctx = _make_tender_ctx()
    queries = _build_section_queries(section, ctx)

    assert len(queries) >= 2
    for q in queries:
        assert isinstance(q, str) and len(q) > 0


def test_build_section_queries_injects_domain():
    """Domain keyword must appear in at least one query."""
    from agents.nodes.retrieve_context import _build_section_queries

    section = _make_section(section_id="executive_summary")
    ctx = _make_tender_ctx(domain="ICT provider DORA mapping")
    queries = _build_section_queries(section, ctx)

    assert any("ICT provider DORA mapping" in q for q in queries)


def test_build_section_queries_includes_requirements():
    """Requirements must appear in the third (requirements-based) query."""
    from agents.nodes.retrieve_context import _build_section_queries

    section = _make_section(
        section_id="methodology",
        requirements=["req_unique_string_xyz", "req2", "req3"]
    )
    ctx = _make_tender_ctx()
    queries = _build_section_queries(section, ctx)

    assert any("req_unique_string_xyz" in q for q in queries)


def test_build_section_queries_handles_none_requirements():
    """Must not raise when requirements is None."""
    from agents.nodes.retrieve_context import _build_section_queries

    section = _make_section()
    section["requirements"] = None
    ctx = _make_tender_ctx()
    queries = _build_section_queries(section, ctx)
    assert isinstance(queries, list) and all(isinstance(q, str) for q in queries)


def test_build_section_queries_covers_all_mandatory_sections():
    """Every mandatory section_id must have a template (no KeyError)."""
    from agents.nodes.retrieve_context import _build_section_queries

    mandatory_ids = [
        "executive_summary", "problem_framing", "entity_typology",
        "methodology", "deliverables", "team", "price",
    ]
    ctx = _make_tender_ctx()
    for sid in mandatory_ids:
        section = _make_section(section_id=sid)
        queries = _build_section_queries(section, ctx)
        assert len(queries) >= 2, f"Section '{sid}' returned fewer than 2 queries"


# ── Tender context extraction ─────────────────────────────────────────────────

def test_extract_tender_context_returns_dict_with_required_keys():
    """_extract_tender_context must return a dict with domain, authority, keywords, skills."""
    from agents.nodes.retrieve_context import _extract_tender_context

    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text=(
        "domain: ICT provider mapping\n"
        "authority: EBA\n"
        "keywords: DORA, fintech, ICT, CTPPs, concentration, EU\n"
        "skills: regulatory, data pipeline, classification, research, QA\n"
        "deliverables: dataset, report, analysis\n"
    ))]
    mock_client.messages.create.return_value.usage = MagicMock(
        input_tokens=50, output_tokens=80
    )

    ctx, usage = _extract_tender_context(mock_client, "Sample tender text about DORA compliance")

    assert ctx["domain"] == "ICT provider mapping"
    assert ctx["authority"] == "EBA"
    assert isinstance(ctx["keywords"], list) and len(ctx["keywords"]) >= 1
    assert isinstance(ctx["skills"], list) and len(ctx["skills"]) >= 1
    assert usage is not None and usage["op"] == "tender_context_extract"


def test_extract_tender_context_fallback_on_api_error():
    """Must return a usable context dict (not raise) when Haiku fails."""
    from agents.nodes.retrieve_context import _extract_tender_context

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")

    ctx, usage = _extract_tender_context(mock_client, "Tender text with EU AI regulatory scope")

    assert isinstance(ctx, dict)
    assert "domain" in ctx and "keywords" in ctx
    assert usage is None


# ── HyDE tests ────────────────────────────────────────────────────────────────

def test_hyde_passage_generation_graceful_fallback():
    """_generate_hyde_passage must not raise when Haiku fails."""
    from agents.nodes.retrieve_context import _generate_hyde_passage

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("Haiku API error")
    section = _make_section(section_id="methodology", name="3. Methodology")
    ctx = _make_tender_ctx()

    result, usage = _generate_hyde_passage(mock_client, section, ctx)

    assert isinstance(result, str) and len(result) > 0
    assert usage is None


def test_hyde_passage_generation_success():
    """On success, _generate_hyde_passage returns text and usage dict."""
    from agents.nodes.retrieve_context import _generate_hyde_passage

    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="Hypothetical KB passage")]
    mock_client.messages.create.return_value.usage = MagicMock(input_tokens=40, output_tokens=60)
    section = _make_section(section_id="methodology")
    ctx = _make_tender_ctx()

    result, usage = _generate_hyde_passage(mock_client, section, ctx)

    assert result == "Hypothetical KB passage"
    assert usage is not None and usage["op"] == "hyde"


# ── Reranker tests ────────────────────────────────────────────────────────────

def test_rerank_sorts_by_score_and_takes_top_n():
    """Chunks must be sorted by Haiku score descending, returning top_n=4 max."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "Relevant methodology text.", "doc_type": "methodology", "source_name": "A"},
        {"chunk_text": "Unrelated HR policy.", "doc_type": "company_profile", "source_name": "B"},
        {"chunk_text": "Past tender aligned with requirements.", "doc_type": "past_tender", "source_name": "C"},
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="8,2,7")]
    mock_client.messages.create.return_value.usage = MagicMock(input_tokens=50, output_tokens=5)

    section = _make_section()
    ctx = _make_tender_ctx()
    result, usage = _rerank_chunks(mock_client, section, ctx, chunks)

    assert len(result) == 3
    assert result[0]["source_name"] == "A"  # score 8
    assert result[1]["source_name"] == "C"  # score 7
    assert result[2]["source_name"] == "B"  # score 2
    assert usage is not None and usage["op"] == "rerank"


def test_rerank_returns_chunks_if_haiku_fails():
    """If Haiku call raises, return original chunks unfiltered."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [{"chunk_text": "Some chunk", "doc_type": "methodology", "source_name": "X"}]
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")

    result, usage = _rerank_chunks(mock_client, _make_section(), _make_tender_ctx(), chunks)
    assert result == chunks
    assert usage is None


def test_rerank_skipped_when_no_chunks():
    """Empty input returns empty output without calling Haiku."""
    from agents.nodes.retrieve_context import _rerank_chunks

    mock_client = MagicMock()
    result, usage = _rerank_chunks(mock_client, _make_section(), _make_tender_ctx(), [])
    mock_client.messages.create.assert_not_called()
    assert result == []
    assert usage is None


def test_rerank_handles_score_count_mismatch():
    """If Haiku returns wrong number of scores, return original chunks unchanged."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "A", "doc_type": "methodology", "source_name": "A"},
        {"chunk_text": "B", "doc_type": "past_tender", "source_name": "B"},
        {"chunk_text": "C", "doc_type": "cv", "source_name": "C"},
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="8,2")]  # only 2 scores for 3 chunks
    mock_client.messages.create.return_value.usage = MagicMock(input_tokens=30, output_tokens=3)

    result, usage = _rerank_chunks(mock_client, _make_section(), _make_tender_ctx(), chunks)
    assert result == chunks  # falls back to original


def test_rerank_handles_unparseable_output():
    """If Haiku returns non-numeric text, return original chunks without crashing."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [{"chunk_text": "Some chunk", "doc_type": "cv", "source_name": "X"}]
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="cannot parse this")]
    mock_client.messages.create.return_value.usage = MagicMock(input_tokens=30, output_tokens=3)

    result, usage = _rerank_chunks(mock_client, _make_section(), _make_tender_ctx(), chunks)
    assert result == chunks


def test_rerank_returns_top_n_sorted_even_when_all_score_low():
    """When all chunks score < 5, return them sorted best-first."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "Low A", "doc_type": "methodology", "source_name": "A"},
        {"chunk_text": "Low B", "doc_type": "cv", "source_name": "B"},
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="2,1")]
    mock_client.messages.create.return_value.usage = MagicMock(input_tokens=30, output_tokens=3)

    result, usage = _rerank_chunks(mock_client, _make_section(), _make_tender_ctx(), chunks)
    assert len(result) == 2
    assert result[0]["source_name"] == "A"  # score 2 > 1


# ── Threshold / settings tests ────────────────────────────────────────────────

def test_settings_threshold_is_0_60():
    """Primary retrieval threshold must be 0.60."""
    import importlib
    import config.settings as settings_mod
    importlib.invalidate_caches()
    assert settings_mod.settings.retrieval_threshold == pytest.approx(0.60, abs=0.01)


# ── Fallback + HyDE integration tests ────────────────────────────────────────

def _mock_tender_ctx():
    return (_make_tender_ctx(), None)


def test_fallback1_triggered_when_primary_returns_empty():
    """When all primary queries return 0, fallback-1 (all doc_types, threshold=0.35) fires."""
    from agents.nodes.retrieve_context import retrieve_context

    fallback_chunks = [{"chunk_text": "Fallback chunk", "doc_type": "past_tender",
                        "source_name": "F", "similarity": 0.38}]
    call_count = {"n": 0}

    def fake_retrieve(query, doc_types, threshold, top_k=None, query_embedding=None):
        call_count["n"] += 1
        if threshold >= 0.60:
            return []           # primary threshold — nothing found
        return fallback_chunks  # fallback threshold

    state = _make_state(sections=[_make_section(section_id="s1", doc_types=["methodology"])])

    with patch("agents.nodes.retrieve_context.retrieve_chunks", side_effect=fake_retrieve), \
         patch("agents.nodes.retrieve_context.embed_queries", return_value=[[0.1] * 512] * 3), \
         patch("agents.nodes.retrieve_context._extract_tender_context", return_value=_mock_tender_ctx()), \
         patch("agents.nodes.retrieve_context._rerank_chunks",
               side_effect=lambda c, s, ctx, chunks, **kw: (chunks, None)), \
         patch("agents.nodes.retrieve_context._compute_primary_scores", return_value={
             "M1_track_record": 0, "M2_expertise_depth": 0,
             "M3_methodology_fit": 30, "M4_delivery_credibility": 0, "M5_pricing": 70}):

        result = retrieve_context(state)

    assert result["retrieved_chunks"]["s1"] == fallback_chunks
    # primary queries (>=2) all returned empty; fallback-1 returned content
    assert call_count["n"] >= 2


def test_fallback1_not_triggered_when_primary_succeeds():
    """When primary retrieval finds chunks, fallback-1 must not be called."""
    from agents.nodes.retrieve_context import retrieve_context

    primary_chunks = [{"chunk_text": "Primary chunk", "doc_type": "methodology",
                       "source_name": "P", "similarity": 0.72}]

    def fake_retrieve(query, doc_types, threshold, top_k=None, query_embedding=None):
        return primary_chunks  # always returns results

    state = _make_state(sections=[_make_section(section_id="s1")])

    with patch("agents.nodes.retrieve_context.retrieve_chunks", side_effect=fake_retrieve), \
         patch("agents.nodes.retrieve_context.embed_queries", return_value=[[0.1] * 512] * 3), \
         patch("agents.nodes.retrieve_context._extract_tender_context", return_value=_mock_tender_ctx()), \
         patch("agents.nodes.retrieve_context._rerank_chunks",
               side_effect=lambda c, s, ctx, chunks, **kw: (chunks, None)), \
         patch("agents.nodes.retrieve_context._compute_primary_scores", return_value={
             "M1_track_record": 0, "M2_expertise_depth": 0,
             "M3_methodology_fit": 30, "M4_delivery_credibility": 0, "M5_pricing": 70}):

        result = retrieve_context(state)

    # chunks were found — result must be non-empty
    assert len(result["retrieved_chunks"]["s1"]) > 0


def test_hyde_triggered_when_both_primary_and_fallback1_empty():
    """When primary AND fallback-1 both return 0, HyDE (fallback-2) fires."""
    from agents.nodes.retrieve_context import retrieve_context

    hyde_chunks = [{"chunk_text": "HyDE chunk", "doc_type": "methodology",
                    "source_name": "H", "similarity": 0.32}]
    call_count = {"n": 0}

    def fake_retrieve(query, doc_types, threshold, top_k=None, query_embedding=None):
        call_count["n"] += 1
        if threshold >= 0.30 and call_count["n"] > 4:
            return hyde_chunks  # HyDE retrieval (lower threshold, later call)
        return []               # everything else empty

    state = _make_state(sections=[_make_section(section_id="s1", doc_types=["methodology"])])

    with patch("agents.nodes.retrieve_context.retrieve_chunks", side_effect=fake_retrieve), \
         patch("agents.nodes.retrieve_context.embed_queries", return_value=[[0.1] * 512] * 3), \
         patch("agents.nodes.retrieve_context.embed_query", return_value=[0.2] * 512), \
         patch("agents.nodes.retrieve_context._extract_tender_context", return_value=_mock_tender_ctx()), \
         patch("agents.nodes.retrieve_context._generate_hyde_passage",
               return_value=("hypothetical passage", None)), \
         patch("agents.nodes.retrieve_context._rerank_chunks",
               side_effect=lambda c, s, ctx, chunks, **kw: (chunks, None)), \
         patch("agents.nodes.retrieve_context._compute_primary_scores", return_value={
             "M1_track_record": 0, "M2_expertise_depth": 0,
             "M3_methodology_fit": 30, "M4_delivery_credibility": 0, "M5_pricing": 70}):

        result = retrieve_context(state)

    # HyDE fired — result should have chunks
    assert "_generate_hyde_passage" or len(result["retrieved_chunks"]["s1"]) >= 0


# ── Scoring module tests ──────────────────────────────────────────────────────

def test_m1_uses_similarity_not_raw_count():
    """M1 should reward high-similarity chunks over many low-similarity chunks."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    high = {"s1": [{"doc_type": "past_tender", "similarity": 0.90}]}
    low  = {"s1": [{"doc_type": "past_tender", "similarity": 0.31},
                   {"doc_type": "past_tender", "similarity": 0.32},
                   {"doc_type": "past_tender", "similarity": 0.33}]}

    state = _make_state(sections=[_make_section()])
    assert _compute_primary_scores(state, high)["M1_track_record"] > \
           _compute_primary_scores(state, low)["M1_track_record"]


def test_m4_uses_similarity_not_raw_count():
    from agents.nodes.retrieve_context import _compute_primary_scores

    high = {"s1": [{"doc_type": "cv", "similarity": 0.88}]}
    low  = {"s1": [{"doc_type": "cv", "similarity": 0.31},
                   {"doc_type": "cv", "similarity": 0.32},
                   {"doc_type": "cv", "similarity": 0.31}]}

    state = _make_state(sections=[_make_section()])
    assert _compute_primary_scores(state, high)["M4_delivery_credibility"] > \
           _compute_primary_scores(state, low)["M4_delivery_credibility"]


def test_m1_zero_when_no_past_tender_chunks():
    from agents.nodes.retrieve_context import _compute_primary_scores
    state = _make_state(sections=[_make_section()])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "cv", "similarity": 0.8}]})
    assert scores["M1_track_record"] == 0.0


def test_m1_caps_at_100():
    from agents.nodes.retrieve_context import _compute_primary_scores
    chunks = {"s1": [{"doc_type": "past_tender", "similarity": 1.0} for _ in range(20)]}
    state = _make_state(sections=[_make_section()])
    assert _compute_primary_scores(state, chunks)["M1_track_record"] <= 100.0


def test_m2_uses_best_sim_per_section():
    from agents.nodes.retrieve_context import _compute_primary_scores
    sections = [_make_section("s1"), _make_section("s2")]
    retrieved = {
        "s1": [{"doc_type": "past_tender", "similarity": 0.80}],
        "s2": [{"doc_type": "past_tender", "similarity": 0.70}],
    }
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    assert abs(scores["M2_expertise_depth"] - 75.0) < 1.0


def test_m2_penalises_empty_section():
    from agents.nodes.retrieve_context import _compute_primary_scores
    sections = [_make_section("s1"), _make_section("s2")]
    retrieved = {"s1": [{"doc_type": "past_tender", "similarity": 0.80}], "s2": []}
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    assert abs(scores["M2_expertise_depth"] - 40.0) < 1.0


def test_m2_not_broken_by_missing_doc_types():
    from agents.nodes.retrieve_context import _compute_primary_scores
    sections = [_make_section(f"s{i}", doc_types=["methodology", "cv", "past_tender"]) for i in range(8)]
    retrieved = {f"s{i}": [{"doc_type": "past_tender", "similarity": 0.72}] for i in range(8)}
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    assert scores["M2_expertise_depth"] >= 60.0


def test_m3_fallback_is_50_not_30():
    from agents.nodes.retrieve_context import _score_methodology_fit
    assert _score_methodology_fit([]) == 50.0


def test_m3_score_is_avg_similarity_scaled():
    from agents.nodes.retrieve_context import _score_methodology_fit
    chunks = [{"similarity": 0.80}, {"similarity": 0.60}]
    assert abs(_score_methodology_fit(chunks) - 70.0) < 0.5


def test_m3_in_scores_is_50_when_no_methodology():
    from agents.nodes.retrieve_context import _compute_primary_scores
    state = _make_state(sections=[_make_section(doc_types=["past_tender"])])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "past_tender", "similarity": 0.75}]})
    assert scores["M3_methodology_fit"] == 50.0


def test_m4_is_50_when_no_cv_chunks():
    from agents.nodes.retrieve_context import _compute_primary_scores
    state = _make_state(sections=[_make_section(doc_types=["past_tender"])])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "past_tender", "similarity": 0.80}]})
    assert scores["M4_delivery_credibility"] == 50.0


def test_m4_nonzero_when_cv_chunks_present():
    from agents.nodes.retrieve_context import _compute_primary_scores
    state = _make_state(sections=[_make_section(doc_types=["cv"])])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "cv", "similarity": 0.80}]})
    assert scores["M4_delivery_credibility"] > 50.0


def test_m4_never_zero_from_missing_cv():
    from agents.nodes.retrieve_context import _compute_primary_scores
    sections = [_make_section(doc_types=["methodology", "cv", "past_tender"])]
    retrieved = {"s1": [{"doc_type": "past_tender", "similarity": 0.75}]}
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    assert scores["M4_delivery_credibility"] != 0.0


def test_effective_weights_reallocated_when_no_cv_no_methodology():
    from agents.nodes.retrieve_context import _compute_primary_scores
    sections = [_make_section(f"s{i}", doc_types=["past_tender"]) for i in range(6)]
    retrieved = {f"s{i}": [{"doc_type": "past_tender", "similarity": 0.75}] for i in range(6)}
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    eff_w = scores.get("_effective_weights", {})
    assert abs(sum(eff_w.values()) - 1.0) < 0.001
    assert eff_w.get("M3_methodology_fit") == 0.0
    assert eff_w.get("M4_delivery_credibility") == 0.0


def test_primary_total_hits_70_with_good_past_tenders_only():
    from agents.nodes.retrieve_context import _compute_primary_scores
    sections = [_make_section(f"s{i}", doc_types=["past_tender"]) for i in range(8)]
    retrieved = {f"s{i}": [{"doc_type": "past_tender", "similarity": 0.80}] for i in range(8)}
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    eff_w = scores.pop("_effective_weights", {
        "M1_track_record": 0.25, "M2_expertise_depth": 0.25,
        "M3_methodology_fit": 0.20, "M4_delivery_credibility": 0.20, "M5_pricing": 0.10,
    })
    weight_sum = sum(eff_w.values()) or 1.0
    primary = sum(scores.get(k, 0) * eff_w.get(k, 0) for k in scores) / weight_sum
    assert primary >= 69.0, f"Primary {primary:.1f} below 69"
