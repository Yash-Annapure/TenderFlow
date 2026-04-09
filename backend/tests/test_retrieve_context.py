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


def test_query_uses_all_requirements():
    """Query must include all requirements, not just first 3."""
    from agents.nodes.retrieve_context import _build_section_query

    section = _make_section(
        requirements=["req1", "req2", "req3", "req4", "req5"]
    )
    query = _build_section_query(section, tender_excerpt="Tender for AI services.")

    assert "req4" in query
    assert "req5" in query


def test_query_includes_tender_excerpt():
    """Query must include a snippet of the tender text for context."""
    from agents.nodes.retrieve_context import _build_section_query

    section = _make_section()
    query = _build_section_query(section, tender_excerpt="AI ecosystem mapping procurement 2024")

    assert "AI ecosystem mapping" in query


def test_query_includes_section_name():
    """Query must include the section name."""
    from agents.nodes.retrieve_context import _build_section_query

    section = _make_section(name="Technical Methodology")
    query = _build_section_query(section, tender_excerpt="some context")

    assert "Technical Methodology" in query


def test_query_handles_none_requirements():
    """Must not raise TypeError when requirements is explicitly None."""
    from agents.nodes.retrieve_context import _build_section_query

    section = _make_section()
    section["requirements"] = None  # explicit None, not missing key

    query = _build_section_query(section, tender_excerpt="context")
    assert isinstance(query, str)


def test_rerank_sorts_by_score_and_takes_top_n():
    """Chunks must be sorted by Haiku score descending, returning top_n=4 max."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "Relevant methodology text about AI mapping.", "doc_type": "methodology", "source_name": "A"},
        {"chunk_text": "Unrelated HR policy paragraph about leave.", "doc_type": "company_profile", "source_name": "B"},
        {"chunk_text": "Past tender on data governance aligned with requirements.", "doc_type": "past_tender", "source_name": "C"},
    ]

    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="8,2,7")]

    result = _rerank_chunks(mock_client, "Background", ["Describe company"], chunks)

    # All 3 returned (3 < top_n=4), sorted: A(8) > C(7) > B(2)
    assert len(result) == 3
    assert result[0]["source_name"] == "A"
    assert result[1]["source_name"] == "C"
    assert result[2]["source_name"] == "B"


def test_rerank_returns_all_if_haiku_fails():
    """If Haiku call raises, return original chunks unfiltered."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "Some chunk", "doc_type": "methodology", "source_name": "X"},
    ]
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")

    result = _rerank_chunks(mock_client, "Background", ["req"], chunks)
    assert result == chunks


def test_rerank_skipped_when_no_chunks():
    """Empty input returns empty output without calling Haiku."""
    from agents.nodes.retrieve_context import _rerank_chunks

    mock_client = MagicMock()
    result = _rerank_chunks(mock_client, "Background", ["req"], [])
    mock_client.messages.create.assert_not_called()
    assert result == []


def test_rerank_handles_score_count_mismatch():
    """If Haiku returns wrong number of scores, return original chunks unchanged."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "Chunk A", "doc_type": "methodology", "source_name": "A"},
        {"chunk_text": "Chunk B", "doc_type": "past_tender", "source_name": "B"},
        {"chunk_text": "Chunk C", "doc_type": "cv", "source_name": "C"},
    ]
    mock_client = MagicMock()
    # Returns only 2 scores for 3 chunks
    mock_client.messages.create.return_value.content = [MagicMock(text="8,2")]

    result = _rerank_chunks(mock_client, "Background", ["req"], chunks)
    assert result == chunks  # falls back to original


def test_rerank_handles_unparseable_output():
    """If Haiku returns non-numeric text, return original chunks without crashing."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [{"chunk_text": "Some chunk", "doc_type": "cv", "source_name": "X"}]
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="cannot parse this")]

    result = _rerank_chunks(mock_client, "Background", ["req"], chunks)
    assert result == chunks


def test_rerank_returns_top_n_sorted_even_when_all_score_low():
    """When all chunks score < 5, return them sorted best-first (top_n max), not empty."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "Low relevance A", "doc_type": "methodology", "source_name": "A"},
        {"chunk_text": "Low relevance B", "doc_type": "cv", "source_name": "B"},
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="2,1")]

    result = _rerank_chunks(mock_client, "Background", ["req"], chunks)
    assert len(result) == 2          # both returned (2 < top_n=4)
    assert result[0]["source_name"] == "A"  # score 2 > score 1, A comes first


def test_settings_threshold_is_0_60():
    """Primary retrieval threshold must be 0.60."""
    import importlib
    import config.settings as settings_mod
    importlib.invalidate_caches()
    assert settings_mod.settings.retrieval_threshold == pytest.approx(0.60, abs=0.01)


# ── Fallback + HyDE tests ─────────────────────────────────────────────────────

def test_fallback1_triggered_when_primary_returns_empty():
    """When primary retrieval returns 0 chunks, fallback-1 (all doc_types, threshold=0.35) fires."""
    from agents.nodes.retrieve_context import retrieve_context

    fallback_chunks = [{"chunk_text": "Fallback chunk", "doc_type": "past_tender",
                        "source_name": "F", "similarity": 0.38}]

    call_count = {"n": 0}
    def fake_retrieve(query, doc_types, threshold, top_k=None, query_embedding=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []          # primary returns nothing
        return fallback_chunks  # fallback-1 returns content

    state = _make_state(sections=[_make_section(section_id="s1", name="AI Ecosystem Mapping Methodology",
                                                doc_types=["methodology"])])

    with patch("agents.nodes.retrieve_context.retrieve_chunks", side_effect=fake_retrieve), \
         patch("agents.nodes.retrieve_context.embed_queries", return_value=[[0.1] * 512]), \
         patch("agents.nodes.retrieve_context._rerank_chunks", side_effect=lambda c, n, r, chunks: chunks), \
         patch("agents.nodes.retrieve_context._compute_primary_scores", return_value={
             "M1_track_record": 0, "M2_expertise_depth": 0, "M3_methodology_fit": 30,
             "M4_delivery_credibility": 0, "M5_pricing": 70}):

        result = retrieve_context(state)

    assert result["retrieved_chunks"]["s1"] == fallback_chunks
    assert call_count["n"] == 2  # primary + fallback-1


def test_fallback1_not_triggered_when_primary_succeeds():
    """When primary retrieval finds chunks, fallback-1 must never be called."""
    from agents.nodes.retrieve_context import retrieve_context

    primary_chunks = [{"chunk_text": "Primary chunk", "doc_type": "methodology",
                       "source_name": "P", "similarity": 0.72}]
    call_count = {"n": 0}

    def fake_retrieve(query, doc_types, threshold, top_k=None, query_embedding=None):
        call_count["n"] += 1
        return primary_chunks

    state = _make_state(sections=[_make_section(section_id="s1")])

    with patch("agents.nodes.retrieve_context.retrieve_chunks", side_effect=fake_retrieve), \
         patch("agents.nodes.retrieve_context.embed_queries", return_value=[[0.1] * 512]), \
         patch("agents.nodes.retrieve_context._rerank_chunks", side_effect=lambda c, n, r, chunks: chunks), \
         patch("agents.nodes.retrieve_context._compute_primary_scores", return_value={
             "M1_track_record": 0, "M2_expertise_depth": 0, "M3_methodology_fit": 30,
             "M4_delivery_credibility": 0, "M5_pricing": 70}):

        retrieve_context(state)

    assert call_count["n"] == 1  # only primary fired


def test_hyde_triggered_when_both_primary_and_fallback1_empty():
    """When primary AND fallback-1 both return 0, HyDE (fallback-2) fires."""
    from agents.nodes.retrieve_context import retrieve_context

    hyde_chunks = [{"chunk_text": "HyDE chunk", "doc_type": "methodology",
                    "source_name": "H", "similarity": 0.32}]
    call_count = {"n": 0}

    def fake_retrieve(query, doc_types, threshold, top_k=None, query_embedding=None):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return []       # primary + fallback-1 both fail
        return hyde_chunks  # HyDE retrieval succeeds

    state = _make_state(sections=[_make_section(section_id="s1", doc_types=["methodology"])])

    with patch("agents.nodes.retrieve_context.retrieve_chunks", side_effect=fake_retrieve), \
         patch("agents.nodes.retrieve_context.embed_queries", return_value=[[0.1] * 512]), \
         patch("agents.nodes.retrieve_context.embed_query", return_value=[0.2] * 512), \
         patch("agents.nodes.retrieve_context._generate_hyde_passage", return_value="hypothetical passage"), \
         patch("agents.nodes.retrieve_context._rerank_chunks", side_effect=lambda c, n, r, chunks: chunks), \
         patch("agents.nodes.retrieve_context._compute_primary_scores", return_value={
             "M1_track_record": 0, "M2_expertise_depth": 0, "M3_methodology_fit": 30,
             "M4_delivery_credibility": 0, "M5_pricing": 70}):

        result = retrieve_context(state)

    assert result["retrieved_chunks"]["s1"] == hyde_chunks
    assert call_count["n"] == 3  # primary + fallback-1 + HyDE


def test_hyde_passage_generation_graceful_fallback():
    """_generate_hyde_passage must not raise when Haiku fails — returns plain string."""
    from agents.nodes.retrieve_context import _generate_hyde_passage

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("Haiku API error")

    result = _generate_hyde_passage(mock_client, "AI Ecosystem Mapping", ["req1", "req2"], "tender text")

    assert isinstance(result, str)
    assert len(result) > 0


def test_m1_uses_similarity_not_raw_count():
    """M1 should reward high-similarity chunks over many low-similarity chunks."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    high_sim_chunks = {
        "s1": [{"doc_type": "past_tender", "similarity": 0.90}],
    }
    low_sim_chunks = {
        "s1": [
            {"doc_type": "past_tender", "similarity": 0.31},
            {"doc_type": "past_tender", "similarity": 0.32},
            {"doc_type": "past_tender", "similarity": 0.33},
        ],
    }

    state = _make_state(sections=[_make_section()])
    high_scores = _compute_primary_scores(state, high_sim_chunks)
    low_scores = _compute_primary_scores(state, low_sim_chunks)

    assert high_scores["M1_track_record"] > low_scores["M1_track_record"]


def test_m4_uses_similarity_not_raw_count():
    """M4 should reward high-similarity CV chunks."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    high_sim_chunks = {
        "s1": [{"doc_type": "cv", "similarity": 0.88}],
    }
    low_sim_chunks = {
        "s1": [
            {"doc_type": "cv", "similarity": 0.31},
            {"doc_type": "cv", "similarity": 0.32},
            {"doc_type": "cv", "similarity": 0.31},
        ],
    }

    state = _make_state(sections=[_make_section()])
    high_scores = _compute_primary_scores(state, high_sim_chunks)
    low_scores = _compute_primary_scores(state, low_sim_chunks)

    assert high_scores["M4_delivery_credibility"] > low_scores["M4_delivery_credibility"]


def test_m1_zero_when_no_past_tender_chunks():
    """M1 must be 0.0 when no past_tender chunks retrieved."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    state = _make_state(sections=[_make_section()])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "cv", "similarity": 0.8}]})
    assert scores["M1_track_record"] == 0.0


def test_m1_caps_at_100():
    """M1 must never exceed 100."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    chunks = {
        "s1": [{"doc_type": "past_tender", "similarity": 1.0} for _ in range(20)],
    }
    state = _make_state(sections=[_make_section()])
    scores = _compute_primary_scores(state, chunks)
    assert scores["M1_track_record"] <= 100.0


# ── M2 redesign tests ─────────────────────────────────────────────────────────

def test_m2_uses_best_sim_per_section():
    """M2 = avg of best-chunk similarity per section, doc_type agnostic."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    sections = [
        _make_section("s1", doc_types=["methodology", "cv", "past_tender"]),
        _make_section("s2", doc_types=["past_tender"]),
    ]
    retrieved = {
        "s1": [{"doc_type": "past_tender", "similarity": 0.80}],
        "s2": [{"doc_type": "past_tender", "similarity": 0.70}],
    }
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    # avg best-sim = (0.80 + 0.70) / 2 = 0.75 → M2 = 75.0
    assert abs(scores["M2_expertise_depth"] - 75.0) < 1.0


def test_m2_penalises_empty_section():
    """Sections with no retrieved chunks contribute 0 to M2 avg."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    sections = [_make_section("s1"), _make_section("s2")]
    retrieved = {
        "s1": [{"doc_type": "past_tender", "similarity": 0.80}],
        "s2": [],
    }
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    # avg = (0.80 + 0.0) / 2 = 0.40 → M2 = 40.0
    assert abs(scores["M2_expertise_depth"] - 40.0) < 1.0


def test_m2_not_broken_by_missing_doc_types():
    """Old formula gave 9/100 when only past_tender found in multi-type sections."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    sections = [
        _make_section(f"s{i}", doc_types=["methodology", "cv", "past_tender"])
        for i in range(8)
    ]
    retrieved = {
        f"s{i}": [{"doc_type": "past_tender", "similarity": 0.72}]
        for i in range(8)
    }
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    assert scores["M2_expertise_depth"] >= 60.0, (
        f"M2={scores['M2_expertise_depth']:.1f} — old formula would give ~9, new must give ≥60"
    )


# ── M3 fallback test ──────────────────────────────────────────────────────────

def test_m3_fallback_is_50_not_30():
    """_score_methodology_fit must return 50.0 (neutral) not 30.0 (penalty) when no chunks."""
    from agents.nodes.retrieve_context import _score_methodology_fit
    assert _score_methodology_fit([], "some tender text") == 50.0


def test_m3_score_is_avg_similarity_scaled():
    """M3 must equal avg similarity × 100 — deterministic, no LLM call."""
    from agents.nodes.retrieve_context import _score_methodology_fit

    chunks = [
        {"similarity": 0.80, "doc_type": "methodology"},
        {"similarity": 0.60, "doc_type": "methodology"},
    ]
    score = _score_methodology_fit(chunks, "some tender text")
    assert abs(score - 70.0) < 0.5  # avg 0.70 → 70.0


def test_m3_in_scores_is_50_when_no_methodology_in_kb():
    """M3 in _compute_primary_scores must be 50 when KB has no methodology docs."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    state = _make_state(sections=[_make_section(doc_types=["past_tender"])])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "past_tender", "similarity": 0.75}]})
    assert scores["M3_methodology_fit"] == 50.0


# ── M4 neutral tests ──────────────────────────────────────────────────────────

def test_m4_is_50_when_no_cv_chunks():
    """M4 must be 50 (neutral/unknown) when no CV chunks exist — not 0 (catastrophic)."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    state = _make_state(sections=[_make_section(doc_types=["past_tender"])])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "past_tender", "similarity": 0.80}]})
    assert scores["M4_delivery_credibility"] == 50.0


def test_m4_nonzero_when_cv_chunks_present():
    """M4 must use similarity formula (not neutral) when CV chunks ARE retrieved."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    state = _make_state(sections=[_make_section(doc_types=["cv"])])
    scores = _compute_primary_scores(state, {"s1": [{"doc_type": "cv", "similarity": 0.80}]})
    assert scores["M4_delivery_credibility"] > 50.0


def test_m4_never_zero_from_missing_cv_in_kb():
    """Regression: M4 must never be 0.0 just because no CVs in KB."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    sections = [_make_section(doc_types=["methodology", "cv", "past_tender"])]
    retrieved = {"s1": [{"doc_type": "past_tender", "similarity": 0.75}]}
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)
    assert scores["M4_delivery_credibility"] != 0.0


# ── Weight reallocation tests ─────────────────────────────────────────────────

def test_effective_weights_reallocated_when_no_cv_no_methodology():
    """When no CV or methodology, M3/M4 weights must be 0 and others get the surplus."""
    from agents.nodes.retrieve_context import _compute_primary_scores

    sections = [_make_section(f"s{i}", doc_types=["past_tender"]) for i in range(6)]
    retrieved = {f"s{i}": [{"doc_type": "past_tender", "similarity": 0.75}] for i in range(6)}
    state = _make_state(sections=sections)
    scores = _compute_primary_scores(state, retrieved)

    eff_w = scores.get("_effective_weights", {})
    assert eff_w, "Expected _effective_weights in scores"
    assert abs(sum(eff_w.values()) - 1.0) < 0.001, "Weights must sum to 1.0"
    assert eff_w.get("M3_methodology_fit") == 0.0
    assert eff_w.get("M4_delivery_credibility") == 0.0


def test_primary_total_hits_70_with_good_past_tenders_only():
    """Demo target: primary ≥ 69 achievable with strong past-tender KB only."""
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
    assert primary >= 69.0, f"Primary {primary:.1f} below 69 — demo target missed"
