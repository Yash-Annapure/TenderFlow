from typing import TypedDict, Optional


class SectionDraft(TypedDict):
    name: str
    requirements: list[str]
    draft_text: str
    confidence: str  # HIGH | MEDIUM | LOW


class TenderState(TypedDict):
    tender_id: str
    tender_text: str

    # Populated by analyse_tender
    sections: list[SectionDraft]

    # Populated by retrieve_context
    retrieved_context: str

    # Populated by draft_sections
    draft: str

    # Populated by human_review (injected via graph.update_state)
    user_feedback: str
    user_edits: str

    # Populated by finalise
    final_draft: str

    status: str
    hitl_iteration: int
    error: Optional[str]
