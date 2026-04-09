"""
Re-enrichment script — populate metadata for KB docs ingested without enrichment.

Finds kb_documents with missing/empty kb_enrichments, re-runs Claude tool-use
enrichment using stored raw_text, then updates kb_enrichments + kb_chunks
denormalized fields (sector_tags, tender_type_tags, regulatory_frameworks).

Does NOT re-chunk or re-embed — existing vectors are preserved.

Usage:
    cd backend
    .venv/Scripts/python scripts/re_enrich.py           # process all unenriched docs
    .venv/Scripts/python scripts/re_enrich.py --dry-run # preview only
    .venv/Scripts/python scripts/re_enrich.py --doc-id <uuid>  # single doc
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


def find_unenriched_docs(supabase, doc_id: str | None = None) -> list[dict]:
    query = (
        supabase.table("kb_documents")
        .select("id, filename, doc_type, source_name, raw_text")
        .eq("is_active", True)
    )
    if doc_id:
        query = query.eq("id", doc_id)

    all_docs = query.execute().data or []
    if not all_docs:
        return []

    ids = [d["id"] for d in all_docs]
    enrichments = (
        supabase.table("kb_enrichments")
        .select("document_id, schema_json")
        .in_("document_id", ids)
        .execute()
        .data or []
    )

    enriched_ids = {
        e["document_id"]
        for e in enrichments
        if e.get("schema_json") and len(e["schema_json"]) > 0
    }

    return [d for d in all_docs if d["id"] not in enriched_ids]


def re_enrich_one(supabase, doc: dict) -> bool:
    from tools.ingest_tool import _enrich_document
    from enrichment.model_router import get_model_for_doc_type

    doc_id = doc["id"]
    doc_type = doc["doc_type"]
    filename = doc["filename"]
    raw_text = doc.get("raw_text") or ""

    if not raw_text.strip():
        logger.warning(f"  [{filename}] raw_text empty — skipping")
        return False

    logger.info(f"  [{filename}] enriching as {doc_type} ({len(raw_text)} chars)")

    try:
        enrichment = _enrich_document(raw_text, doc_type)
    except Exception as e:
        logger.error(f"  [{filename}] enrichment call failed: {e}")
        return False

    if not enrichment:
        logger.warning(f"  [{filename}] enrichment returned empty — skipping")
        return False

    model = get_model_for_doc_type(doc_type)

    # Upsert kb_enrichments
    try:
        existing = (
            supabase.table("kb_enrichments")
            .select("id")
            .eq("document_id", doc_id)
            .execute()
            .data or []
        )
        if existing:
            supabase.table("kb_enrichments").update(
                {"schema_json": enrichment, "model_used": model}
            ).eq("document_id", doc_id).execute()
        else:
            supabase.table("kb_enrichments").insert(
                {"document_id": doc_id, "schema_json": enrichment, "model_used": model}
            ).execute()
    except Exception as e:
        logger.error(f"  [{filename}] kb_enrichments upsert failed: {e}")
        return False

    # Update denormalized chunk fields
    sector_tags = enrichment.get("sector_tags", [])
    tender_type_tags = (
        enrichment.get("tender_type_tags")
        or enrichment.get("best_fit_tender_types", [])
    )
    authority_type = enrichment.get("authority_type")
    regulatory_frameworks = (
        enrichment.get("regulatory_frameworks_invoked")
        or enrichment.get("regulatory_frameworks_known", [])
    )

    try:
        payload = {
            "sector_tags": sector_tags,
            "tender_type_tags": tender_type_tags,
            "regulatory_frameworks": regulatory_frameworks,
        }
        if authority_type:
            payload["authority_type"] = authority_type
        supabase.table("kb_chunks").update(payload).eq("document_id", doc_id).execute()
        logger.info(f"  [{filename}] done — sector_tags={sector_tags[:3]}")
    except Exception as e:
        logger.error(f"  [{filename}] kb_chunks update failed: {e}")
        return False

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--doc-id", type=str, default=None)
    args = parser.parse_args()

    from core.supabase_client import get_supabase_admin
    supabase = get_supabase_admin()

    docs = find_unenriched_docs(supabase, doc_id=args.doc_id)
    if not docs:
        logger.info("All documents already enriched. Nothing to do.")
        return

    logger.info(f"Found {len(docs)} unenriched document(s):")
    for d in docs:
        logger.info(f"  [{d['doc_type']}] {d['filename']}")

    if args.dry_run:
        logger.info("\nDRY RUN — remove --dry-run to process.")
        return

    success = failed = 0
    for i, doc in enumerate(docs):
        if re_enrich_one(supabase, doc):
            success += 1
        else:
            failed += 1
        if i < len(docs) - 1:
            time.sleep(3)  # rate limit buffer

    logger.info(f"\nDone — {success} succeeded, {failed} failed.")


if __name__ == "__main__":
    main()
