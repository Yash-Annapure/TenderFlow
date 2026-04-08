"""Request/response schemas for the ingest router."""

from typing import Literal, Optional
from pydantic import BaseModel


class IngestTaskStatus(BaseModel):
    task_id: str
    status: str  # "pending" | "running" | "completed" | "error"
    document_id: Optional[str] = None
    filename: Optional[str] = None
    chunks_created: int = 0
    guard_flags: list[dict] = []
    error: str = ""


class BulkIngestResponse(BaseModel):
    total: int
    committed: int
    guard_blocked: int
    guard_flagged: int
    errors: int
    results: list[dict]
