"""
retrieve_context node
Loads relevant knowledge base files from disk.
Picks categories based on the sections identified by analyse_tender.
"""

import logging

from agents.state import TenderState
from tools.kb_reader import load_kb_context

logger = logging.getLogger(__name__)

# Keywords per section name → KB categories to load
_CATEGORY_HINTS = {
    "team": ["team_cvs"],
    "cv": ["team_cvs"],
    "personnel": ["team_cvs"],
    "expert": ["team_cvs"],
    "method": ["methodology"],
    "technical": ["methodology"],
    "approach": ["methodology"],
    "past": ["past_tenders"],
    "experience": ["past_tenders"],
    "reference": ["past_tenders"],
    "company": ["company"],
    "profile": ["company"],
    "credentials": ["company"],
    "capacity": ["company"],
    "deliver": ["methodology", "past_tenders"],
    "price": ["company"],
    "budget": ["company", "past_tenders"],
}


def _pick_categories(sections: list[dict]) -> list[str]:
    """Select KB categories relevant to the identified sections."""
    cats: set[str] = set()
    for section in sections:
        name = section.get("name", "").lower()
        for keyword, categories in _CATEGORY_HINTS.items():
            if keyword in name:
                cats.update(categories)
    # Always include company profile and team CVs as baseline
    cats.update(["company", "team_cvs"])
    return list(cats)


def run(state: TenderState) -> dict:
    sections = state.get("sections", [])
    logger.info(f"retrieve_context: {len(sections)} sections to cover")

    categories = _pick_categories(sections)
    logger.info(f"retrieve_context: loading categories {categories}")

    # Load all relevant KB content (4000 chars per file keeps tokens reasonable)
    context = load_kb_context(categories=categories, max_chars_per_file=4000)

    # If we got very little, load everything
    if len(context) < 500:
        logger.warning("retrieve_context: sparse context, loading full KB")
        context = load_kb_context(categories=None, max_chars_per_file=3000)

    logger.info(f"retrieve_context: loaded {len(context)} chars of context")
    return {"retrieved_context": context, "status": "drafting"}
