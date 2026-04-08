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


def test_rerank_drops_low_scoring_chunks():
    """Chunks scoring < 5 from Haiku must be dropped."""
    from agents.nodes.retrieve_context import _rerank_chunks

    chunks = [
        {"chunk_text": "Relevant methodology text about AI mapping.", "doc_type": "methodology", "source_name": "A"},
        {"chunk_text": "Unrelated HR policy paragraph about leave.", "doc_type": "company_profile", "source_name": "B"},
        {"chunk_text": "Past tender on data governance aligned with requirements.", "doc_type": "past_tender", "source_name": "C"},
    ]

    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [
        MagicMock(text="8,2,7")
    ]

    result = _rerank_chunks(mock_client, "Background", ["Describe company"], chunks)

    assert len(result) == 2
    assert result[0]["source_name"] == "A"
    assert result[1]["source_name"] == "C"


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
