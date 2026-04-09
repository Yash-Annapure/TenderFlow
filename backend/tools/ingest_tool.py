"""
Full document ingestion pipeline.

Flow per document:
  1. Parse       → core.document_parser   (text extraction)
  2. Enrich      → Claude tool-use         (structured JSON metadata)
  3. Guard       → enrichment.guard        (3-layer integrity check)
  4. Chunk       → core.chunker            (recursive text splitting)
  5. Embed       → core.embeddings         (voyage-3-lite vectors)
  6. Upsert      → Supabase                (kb_documents + kb_chunks + kb_enrichments)

The pipeline is synchronous and intended to run in a background thread
so the FastAPI route can return immediately with a task_id.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

from config.settings import settings
from core.chunker import chunk_text
from core.document_parser import parse_file
from core.embeddings import embed_documents
from core.supabase_client import get_supabase_admin
from enrichment.guard import GuardResult, commit_facts, run_guard
from enrichment.model_router import get_model_for_doc_type
from enrichment.schemas import SCHEMA_MAP

logger = logging.getLogger(__name__)

# Maps KB seed-directory names → canonical doc_type values
DOC_TYPE_FROM_DIR: dict[str, str] = {
    "company": "company_profile",
    "methodology": "methodology",
    "past_tenders": "past_tender",
    "team_cvs": "cv",
}

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".xlsx"}

# Skip macOS archive artifacts
_SKIP_PATTERNS = {"__MACOSX", ".DS_Store"}


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class IngestResult:
    document_id: str
    filename: str
    chunks_created: int
    status: str  # "committed" | "guard_flagged" | "guard_blocked" | "error"
    guard_flags: list = None
    error: str = ""

    def __post_init__(self):
        if self.guard_flags is None:
            self.guard_flags = []


# ── Singleton Anthropic client ─────────────────────────────────────────────────

_anthropic_client: Optional[anthropic.Anthropic] = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


# ── Public API ─────────────────────────────────────────────────────────────────

def ingest_document(
    file_path: str,
    doc_type: str,
    source_name: str,
    uploaded_by: str = "system",
    file_content: Optional[bytes] = None,
) -> IngestResult:
    """
    Ingest a single document into the KB.

    Args:
        file_path:    Path to the file (used for type detection and storage reference).
        doc_type:     One of: past_tender, cv, methodology, company_profile.
        source_name:  Human-readable document name (displayed in retrieval results).
        uploaded_by:  Username or "system" for seed ingest.
        file_content: Raw bytes — if None, the file is read from file_path.

    Returns:
        IngestResult with status "committed", "guard_flagged", "guard_blocked", or "error".
    """
    supabase = get_supabase_admin()
    filename = Path(file_path).name

    try:
        # ── 1. Parse ──────────────────────────────────────────────────────────
        logger.info(f"[ingest] Parsing {filename} ({doc_type})")
        raw_text = parse_file(file_path, file_content)

        if not raw_text.strip():
            raise ValueError(f"No text extracted from {filename}")

        # ── 2. Create kb_documents row ────────────────────────────────────────
        doc_row = supabase.table("kb_documents").insert(
            {
                "filename": filename,
                "doc_type": doc_type,
                "source_name": source_name,
                "file_path": file_path,
                "raw_text": raw_text[:50_000],  # cap for storage efficiency
                "status": "pending",
                "uploaded_by": uploaded_by,
            }
        ).execute()
        document_id: str = doc_row.data[0]["id"]

        # ── 3. Enrich ─────────────────────────────────────────────────────────
        model = get_model_for_doc_type(doc_type)
        logger.info(f"[ingest] Enriching {filename} with {model}")
        enrichment = _enrich_document(raw_text, doc_type)
        if not enrichment:
            logger.warning(
                f"[ingest] Enrichment returned empty for {filename} — "
                f"proceeding with no metadata (embedding-only retrieval)"
            )

        # ── 4. Guard ──────────────────────────────────────────────────────────
        logger.info(f"[ingest] Running integrity guard on {filename}")
        guard: GuardResult = run_guard(doc_type, enrichment, raw_text, document_id)

        if guard.has_blocks():
            supabase.table("kb_pending_reviews").insert(
                {"document_id": document_id, "flags": guard.to_json()}
            ).execute()
            supabase.table("kb_documents").update({"status": "guard_flagged"}).eq(
                "id", document_id
            ).execute()
            logger.warning(f"[ingest] Guard BLOCKED {filename}: {[f.message for f in guard.flags]}")
            return IngestResult(document_id, filename, 0, "guard_blocked", guard.to_json())

        # ── 5. Persist enrichment ─────────────────────────────────────────────
        supabase.table("kb_enrichments").insert(
            {"document_id": document_id, "schema_json": enrichment, "model_used": model}
        ).execute()
        commit_facts(enrichment, doc_type, document_id)

        # ── 6. Chunk ──────────────────────────────────────────────────────────
        logger.info(f"[ingest] Chunking {filename}")
        chunks = chunk_text(raw_text)
        if not chunks:
            raise ValueError(f"No chunks produced from {filename}")

        # ── 7. Embed ──────────────────────────────────────────────────────────
        logger.info(f"[ingest] Embedding {len(chunks)} chunks from {filename}")
        embeddings = embed_documents(chunks)

        # Denormalised metadata for fast pgvector filtering
        sector_tags = enrichment.get("sector_tags", [])
        tender_type_tags = enrichment.get("tender_type_tags") or enrichment.get("best_fit_tender_types", [])
        authority_type = enrichment.get("authority_type")
        regulatory_frameworks = enrichment.get("regulatory_frameworks_invoked") or enrichment.get(
            "regulatory_frameworks_known", []
        )

        # ── 8. Upsert chunks ──────────────────────────────────────────────────
        BATCH_SIZE = 50
        chunk_rows = [
            {
                "document_id": document_id,
                "chunk_text": chunk,
                "embedding": embedding,
                "chunk_index": i,
                "doc_type": doc_type,
                "sector_tags": sector_tags,
                "tender_type_tags": tender_type_tags,
                "authority_type": authority_type,
                "regulatory_frameworks": regulatory_frameworks,
                "source_name": source_name,
                "token_count": len(chunk.split()),
            }
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]

        for i in range(0, len(chunk_rows), BATCH_SIZE):
            supabase.table("kb_chunks").insert(chunk_rows[i : i + BATCH_SIZE]).execute()

        # ── 9. Mark committed ─────────────────────────────────────────────────
        final_status = "committed"
        if guard.has_warnings():
            final_status = "guard_flagged"
            supabase.table("kb_pending_reviews").insert(
                {
                    "document_id": document_id,
                    "flags": [f for f in guard.to_json() if f["severity"] == "WARN"],
                }
            ).execute()

        supabase.table("kb_documents").update(
            {"status": final_status, "chunk_count": len(chunks)}
        ).eq("id", document_id).execute()

        logger.info(f"[ingest] {filename} → {final_status} ({len(chunks)} chunks)")
        return IngestResult(document_id, filename, len(chunks), final_status, guard.to_json())

    except Exception as exc:
        logger.error(f"[ingest] Failed to ingest {filename}: {exc}", exc_info=True)
        return IngestResult(
            str(uuid.uuid4()), filename, 0, "error", error=str(exc)
        )


def bulk_ingest_kb_directory(
    kb_dir: str, uploaded_by: str = "system"
) -> list[IngestResult]:
    """
    Walk a KB seed directory tree and ingest every supported document.

    Directory structure convention:
        kb/
          company/         → company_profile
          methodology/     → methodology
          past_tenders/    → past_tender
          team_cvs/        → cv

    Automatically skips __MACOSX artifacts, .DS_Store, and ._* files.
    """
    results: list[IngestResult] = []
    kb_path = Path(kb_dir)

    if not kb_path.exists():
        logger.error(f"[ingest] KB directory not found: {kb_dir}")
        return results

    for file_path in sorted(kb_path.rglob("*")):
        # Skip macOS and hidden artifacts
        if any(skip in file_path.parts for skip in _SKIP_PATTERNS):
            continue
        if file_path.name.startswith("._") or file_path.name.startswith("."):
            continue
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.debug(f"[ingest] Skipping unsupported extension: {file_path.name}")
            continue

        parent_dir = file_path.parent.name.lower()
        doc_type = DOC_TYPE_FROM_DIR.get(parent_dir, "company_profile")
        source_name = file_path.stem.replace("_", " ").title()

        result = ingest_document(
            file_path=str(file_path),
            doc_type=doc_type,
            source_name=source_name,
            uploaded_by=uploaded_by,
        )
        results.append(result)
        # Respect Voyage AI free-tier rate limit (3 RPM = 1 request per 20s)
        if result.chunks_created > 0:
            time.sleep(21)

    total = len(results)
    committed = sum(1 for r in results if r.status == "committed")
    logger.info(f"[ingest] Bulk ingest complete: {committed}/{total} committed")
    return results


# ── Internal helpers ───────────────────────────────────────────────────────────

def _enrich_document(raw_text: str, doc_type: str) -> dict:
    """
    Call Claude with tool_choice forced to the enrichment schema.
    Returns the extracted metadata dict, or {} on failure.
    """
    schema = SCHEMA_MAP.get(doc_type)
    if not schema:
        return {}

    model = get_model_for_doc_type(doc_type)
    client = _get_anthropic()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            tools=[schema],
            tool_choice={"type": "tool", "name": schema["name"]},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Extract structured metadata from this {doc_type.replace('_', ' ')} document. "
                        "Use the provided tool. IMPORTANT: Only populate numeric fields (amounts, percentages, counts) "
                        "if the value is explicitly and clearly stated in the document as a clean, readable number. "
                        "Do NOT extract garbled, corrupted, or concatenated values. "
                        "Do NOT estimate or infer numeric values. Omit any field you are not certain about.\n\n"
                        f"<document>\n{raw_text[:8000]}\n</document>"
                    ),
                }
            ],
        )
    except Exception as e:
        logger.error(f"[ingest] Enrichment API call failed for {doc_type}: {e}")
        return {}

    for block in response.content:
        if block.type == "tool_use":
            return block.input

    return {}
