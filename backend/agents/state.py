"""
TenderState — the spine of the LangGraph agent.

Every node reads from and writes to this TypedDict.
The full state is checkpointed to Supabase after every node transition,
so the HITL interrupt/resume cycle survives process restarts.

SectionDraft lifecycle:
  analyse_tender   → populates section_id, section_name, requirements, doc_types_needed
  retrieve_context → populates confidence, gap_flag
  draft_sections   → populates draft_text, sources_used
  [HITL interrupt] → user populates user_edits (via API)
  finalise         → populates finalised_content
"""

from typing import Optional, TypedDict


class SectionDraft(TypedDict):
    section_id: str                  # snake_case identifier, e.g. "company_background"
    section_name: str                # Exact name from the tender document
    requirements: list[str]          # Bullet-point requirements extracted from the tender
    doc_types_needed: list[str]      # KB doc types relevant to this section
    word_count_target: int           # Target word count (set by analyse_tender, default 500)

    draft_text: str                  # AI-generated draft (post draft_sections node)
    confidence: str                  # "HIGH" | "MEDIUM" | "LOW" (set by retrieve_context)
    gap_flag: Optional[str]          # Human-readable gap description, None if sufficient context

    user_edits: Optional[str]        # Human-edited version (injected via HITL submit API)
    finalised_content: Optional[str] # Sonnet-polished final version (post finalise node)
    sources_used: list[str]          # Source document names used in this section


class TenderState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────────────────
    tender_id: str                   # UUID — also used as LangGraph thread_id
    tender_text: str                 # Full parsed text of the incoming tender document
    tender_filename: str             # Original filename (for DOCX cover page)
    output_format: str               # "docx" (pdf reserved for post-hackathon)

    # ── Tender Analysis (analyse_tender node) ─────────────────────────────────
    sections: list[SectionDraft]
    compliance_checklist: list[dict] # [{item, mandatory, category}]
    dimension_weights: dict[str, float]  # W1_track_record … W5_pricing (sum=1.0)

    # ── Retrieval (retrieve_context node) ─────────────────────────────────────
    retrieved_chunks: dict[str, list[dict]]  # section_id → list of chunk dicts

    # ── Scoring ───────────────────────────────────────────────────────────────
    primary_scores: dict[str, float]     # module_name → 0-100
    primary_score_total: float           # weighted sum of M1-M5
    compliance_score: float              # Module 6 (Haiku)
    robustness_score: float              # Module 7 (Haiku)
    quality_score_total: float           # compliance×0.55 + robustness×0.45
    final_score: float                   # primary×0.60 + quality×0.40
    score_justifications: dict[str, str] # module_name → explanation string

    # ── HITL (human_review / finalise nodes) ──────────────────────────────────
    user_feedback: str                   # Free-text feedback submitted with user edits
    request_another_round: bool          # True → loop back to human_review after finalise
    hitl_iteration: int                  # Incremented on each HITL submit (max 3)

    # ── Output ────────────────────────────────────────────────────────────────
    output_path: Optional[str]           # Absolute path to generated .docx file
    status: str                          # See STATUS_* constants below
    error_message: Optional[str]


# ── Status constants ───────────────────────────────────────────────────────────
# These values are mirrored in the tender_jobs.status CHECK constraint.
STATUS_PENDING = "pending"
STATUS_ANALYSING = "analysing"
STATUS_RETRIEVING = "retrieving"
STATUS_DRAFTING = "drafting"
STATUS_AWAITING_REVIEW = "awaiting_review"
STATUS_FINALISING = "finalising"
STATUS_DONE = "done"
STATUS_ERROR = "error"
