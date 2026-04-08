"""Request/response schemas for the HITL router."""

from typing import Optional
from pydantic import BaseModel


class SectionEdit(BaseModel):
    section_id: str
    user_edits: str  # Empty string = "no changes, keep AI draft"


class HITLSubmitRequest(BaseModel):
    sections: list[SectionEdit]
    feedback: str = ""
    request_another_round: bool = False
    output_format: str = "docx"


class ReviewResponse(BaseModel):
    tender_id: str
    hitl_iteration: int
    final_score: float
    sections: list[dict]
    score_justifications: dict
