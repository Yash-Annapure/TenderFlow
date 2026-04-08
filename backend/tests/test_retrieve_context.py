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
