"""
Node: analyse_tender

Model: claude-haiku-4-5-20251001 (fast, sufficient for structural extraction)

Outputs written to TenderState:
  - sections           (list[SectionDraft] with id, name, requirements, doc_types_needed)
  - compliance_checklist
  - dimension_weights  (W1-W5, sum=1.0)
  - status             → "analysing"
"""

import logging
from pathlib import Path
from typing import Any

import anthropic

from agents.state import SectionDraft, STATUS_ANALYSING, TenderState
from config.settings import settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "analyse_tender.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""

_ANALYSE_TOOL: dict[str, Any] = {
    "name": "analyse_tender",
    "description": "Analyse a tender document and extract its complete structure",
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_id": {"type": "string"},
                        "section_name": {"type": "string"},
                        "requirements": {"type": "array", "items": {"type": "string"}},
                        "doc_types_needed": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["past_tender", "cv", "methodology", "company_profile"],
                            },
                        },
                        "word_count_target": {"type": "integer", "default": 500},
                    },
                    "required": ["section_id", "section_name", "requirements", "doc_types_needed"],
                },
            },
            "compliance_checklist": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "mandatory": {"type": "boolean"},
                        "category": {"type": "string"},
                    },
                    "required": ["item", "mandatory"],
                },
            },
            "dimension_weights": {
                "type": "object",
                "description": "Scoring dimension weights summing to 1.0",
                "properties": {
                    "W1_track_record": {"type": "number"},
                    "W2_expertise_depth": {"type": "number"},
                    "W3_methodology_fit": {"type": "number"},
                    "W4_delivery_credibility": {"type": "number"},
                    "W5_pricing_competitiveness": {"type": "number"},
                },
                "required": [
                    "W1_track_record",
                    "W2_expertise_depth",
                    "W3_methodology_fit",
                    "W4_delivery_credibility",
                    "W5_pricing_competitiveness",
                ],
            },
        },
        "required": ["sections", "compliance_checklist", "dimension_weights"],
    },
}

_DEFAULT_WEIGHTS = {
    "W1_track_record": 0.25,
    "W2_expertise_depth": 0.25,
    "W3_methodology_fit": 0.20,
    "W4_delivery_credibility": 0.20,
    "W5_pricing_competitiveness": 0.10,
}

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def analyse_tender(state: TenderState) -> dict:
    """Parse the tender and populate sections, checklist, and dimension weights."""
    logger.info(f"[analyse_tender] tender_id={state['tender_id']}")

    tender_text = state["tender_text"]
    client = _get_client()

    messages = [
        {
            "role": "user",
            "content": (
                "Analyse this tender document thoroughly.\n\n"
                f"<tender>\n{tender_text[:6000]}\n</tender>\n\n"
                "Use the analyse_tender tool to return the complete structure."
            ),
        }
    ]

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            system=_SYSTEM_PROMPT,
            tools=[_ANALYSE_TOOL],
            tool_choice={"type": "tool", "name": "analyse_tender"},
            messages=messages,
        )
    except Exception as e:
        logger.error(f"[analyse_tender] API call failed: {e}")
        return {
            "sections": [],
            "compliance_checklist": [],
            "dimension_weights": _DEFAULT_WEIGHTS,
            "status": STATUS_ANALYSING,
            "error_message": str(e),
        }

    analysis: dict = {}
    for block in response.content:
        if block.type == "tool_use":
            analysis = block.input
            break

    if not analysis:
        logger.error("[analyse_tender] No tool_use block in response")
        return {
            "sections": [],
            "compliance_checklist": [],
            "dimension_weights": _DEFAULT_WEIGHTS,
            "status": STATUS_ANALYSING,
        }

    sections: list[SectionDraft] = [
        SectionDraft(
            section_id=s["section_id"],
            section_name=s["section_name"],
            requirements=s.get("requirements", []),
            doc_types_needed=s.get("doc_types_needed", []),
            word_count_target=s.get("word_count_target", 500),
            draft_text="",
            confidence="LOW",
            gap_flag=None,
            user_edits=None,
            finalised_content=None,
            sources_used=[],
        )
        for s in analysis.get("sections", [])
    ]

    logger.info(f"[analyse_tender] Extracted {len(sections)} sections")

    return {
        "sections": sections,
        "compliance_checklist": analysis.get("compliance_checklist", []),
        "dimension_weights": analysis.get("dimension_weights", _DEFAULT_WEIGHTS),
        "status": STATUS_ANALYSING,
        # Initialise scoring fields to 0 so downstream nodes can safely read them
        "primary_scores": {},
        "primary_score_total": 0.0,
        "compliance_score": 0.0,
        "robustness_score": 0.0,
        "quality_score_total": 0.0,
        "final_score": 0.0,
        "score_justifications": {},
        "retrieved_chunks": {},
        "user_feedback": "",
        "request_another_round": False,
        "hitl_iteration": 0,
        "output_path": None,
        "error_message": None,
    }
