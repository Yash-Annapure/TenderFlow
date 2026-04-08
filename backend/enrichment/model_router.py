"""
Routes each doc_type to the appropriate Claude model for enrichment.

Rationale:
  past_tender    → Opus   — requires strategic nuance and positioning pattern recognition
  cv             → Sonnet — structured and predictable; Sonnet is sufficient
  methodology    → Sonnet — technical but well-structured
  company_profile → Haiku  — plain fact sheet: names, numbers, dates, certifications
"""

MODEL_ROUTING: dict[str, str] = {
    "past_tender": "claude-opus-4-6",
    "cv": "claude-sonnet-4-6",
    "methodology": "claude-sonnet-4-6",
    "company_profile": "claude-haiku-4-5-20251001",
}


def get_model_for_doc_type(doc_type: str) -> str:
    """Return the Claude model ID for the given doc_type. Falls back to Sonnet."""
    return MODEL_ROUTING.get(doc_type, "claude-sonnet-4-6")
