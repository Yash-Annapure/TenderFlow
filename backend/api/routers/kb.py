"""
Knowledge Base router — /kb/*

Endpoints:
  GET    /kb/documents         List all active KB documents with metadata
  GET    /kb/documents/{id}    Get a single document with its enrichment
  GET    /kb/pending-reviews   List documents flagged for human review
  DELETE /kb/{doc_id}          Soft-delete a document (sets is_active=false)
"""

import logging

from fastapi import APIRouter, Header, HTTPException
from typing import Annotated

from config.settings import settings
from core.supabase_client import get_supabase, get_supabase_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kb", tags=["knowledge-base"])


@router.get("/documents")
def list_documents():
    """List all active KB documents with metadata."""
    supabase = get_supabase()
    result = (
        supabase.table("kb_documents")
        .select("id, filename, doc_type, source_name, status, chunk_count, uploaded_by, uploaded_at")
        .eq("is_active", True)
        .order("uploaded_at", desc=True)
        .execute()
    )
    return {"documents": result.data or []}


@router.get("/documents/{doc_id}")
def get_document(doc_id: str):
    """Get a single document with its enrichment metadata."""
    supabase = get_supabase()

    doc_result = (
        supabase.table("kb_documents")
        .select("*")
        .eq("id", doc_id)
        .eq("is_active", True)
        .execute()
    )
    if not doc_result.data:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    enrichment_result = (
        supabase.table("kb_enrichments")
        .select("schema_json, model_used, created_at")
        .eq("document_id", doc_id)
        .execute()
    )

    doc = doc_result.data[0]
    doc.pop("raw_text", None)  # Don't return large raw text in API response

    return {
        "document": doc,
        "enrichment": enrichment_result.data[0] if enrichment_result.data else None,
    }


@router.get("/pending-reviews")
def list_pending_reviews(x_admin_key: Annotated[str | None, Header()] = None):
    """List documents flagged for human review after guard warnings."""
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    supabase = get_supabase_admin()
    result = (
        supabase.table("kb_pending_reviews")
        .select("*, kb_documents(filename, doc_type, source_name)")
        .is_("resolved_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return {"pending_reviews": result.data or []}


@router.delete("/{doc_id}")
def delete_document(
    doc_id: str,
    x_admin_key: Annotated[str | None, Header()] = None,
):
    """
    Soft-delete a KB document (is_active=false).
    The document's chunks remain in kb_chunks but are excluded from retrieval
    because match_kb_chunks filters on kb_documents.is_active=true.
    """
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    supabase = get_supabase_admin()

    result = supabase.table("kb_documents").select("id").eq("id", doc_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    supabase.table("kb_documents").update({"is_active": False}).eq("id", doc_id).execute()
    logger.info(f"[kb] Soft-deleted document {doc_id}")

    return {"message": f"Document {doc_id} deactivated", "doc_id": doc_id}
