"""
Retrieval tool — semantic search against Supabase pgvector.

Calls the `match_kb_chunks` RPC defined in the DB migration.
Supports filtering by doc_type array and sector_tags for precision retrieval.

Top-K defaults are per-doc_type (from design doc):
  past_tender / methodology → 6 chunks
  cv / company_profile      → 3 chunks
"""

import logging
from typing import Optional

from config.settings import settings
from core.embeddings import embed_query
from core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Per-doc_type top-K overrides — higher for richer content types
_TOP_K_BY_DOC_TYPE: dict[str, int] = {
    "past_tender": settings.retrieval_top_k_default,
    "methodology": settings.retrieval_top_k_default,
    "cv": settings.retrieval_top_k_cv,
    "company_profile": settings.retrieval_top_k_cv,
}

ALL_DOC_TYPES = ["past_tender", "cv", "methodology", "company_profile"]


def retrieve_chunks(
    query: str,
    doc_types: Optional[list[str]] = None,
    sector_tags: Optional[list[str]] = None,
    top_k: Optional[int] = None,
    threshold: Optional[float] = None,
) -> list[dict]:
    """
    Perform a cosine similarity search against kb_chunks.

    Args:
        query:       Natural language query (embedded with voyage-3-lite, input_type='query').
        doc_types:   Filter to these doc_type values. Defaults to all types.
        sector_tags: Optional sector filter — only chunks matching at least one tag are returned.
        top_k:       Maximum chunks to return. Auto-selected per doc_type if a single type is given.
        threshold:   Minimum similarity score (0-1). Defaults to RETRIEVAL_THRESHOLD setting.

    Returns:
        List of chunk dicts: {id, document_id, chunk_text, doc_type, sector_tags,
                              regulatory_frameworks, similarity}
        Empty list if no matches above threshold.
    """
    supabase = get_supabase()
    resolved_doc_types = doc_types or ALL_DOC_TYPES
    resolved_threshold = threshold if threshold is not None else settings.retrieval_threshold

    if top_k is None:
        if doc_types and len(doc_types) == 1:
            top_k = _TOP_K_BY_DOC_TYPE.get(doc_types[0], settings.retrieval_top_k_default)
        else:
            top_k = settings.retrieval_top_k_default

    logger.debug(
        f"[retrieval] query='{query[:60]}...' doc_types={resolved_doc_types} "
        f"top_k={top_k} threshold={resolved_threshold}"
    )

    # Embed the query
    embedding = embed_query(query)

    try:
        result = supabase.rpc(
            "match_kb_chunks",
            {
                "query_embedding": embedding,
                "filter_doc_types": resolved_doc_types,
                "filter_sector_tags": sector_tags or [],
                "match_threshold": resolved_threshold,
                "match_count": top_k,
            },
        ).execute()
    except Exception as e:
        logger.error(f"[retrieval] RPC call failed: {e}")
        return []

    chunks = result.data or []
    logger.debug(f"[retrieval] Found {len(chunks)} chunks above threshold")
    return chunks
