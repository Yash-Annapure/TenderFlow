"""Request/response schemas for the tender router."""

from typing import Literal, Optional
from pydantic import BaseModel


class StartTenderRequest(BaseModel):
    output_format: Literal["docx"] = "docx"


class TenderJobResponse(BaseModel):
    tender_id: str
    status: str
    tender_filename: Optional[str] = None
    sections: Optional[list[dict]] = None
    score_json: Optional[dict] = None
    output_path: Optional[str] = None
    hitl_iteration: int = 0
    error_msg: Optional[str] = None
