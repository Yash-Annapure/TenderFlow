"""
Embedding wrapper using Voyage AI voyage-3-lite (512-dim vectors).

All KB chunks and retrieval queries go through this module.
The client is instantiated once and reused — never recreated per call.
"""

import logging
from functools import lru_cache
import voyageai
from config.settings import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "voyage-3-lite"
VOYAGE_BATCH_LIMIT = 128  # voyageai hard limit per request


@lru_cache()
def _get_client() -> voyageai.Client:
    return voyageai.Client(api_key=settings.voyage_api_key)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of document chunks for storage in the KB.
    Handles batching automatically.
    """
    if not texts:
        return []

    client = _get_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), VOYAGE_BATCH_LIMIT):
        batch = texts[i : i + VOYAGE_BATCH_LIMIT]
        result = client.embed(batch, model=EMBEDDING_MODEL, input_type="document")
        all_embeddings.extend(result.embeddings)
        logger.debug(f"Embedded batch {i // VOYAGE_BATCH_LIMIT + 1}: {len(batch)} chunks")

    return all_embeddings


def embed_query(query: str) -> list[float]:
    """
    Embed a single retrieval query.
    Uses input_type='query' which voyage optimises differently from documents.
    """
    client = _get_client()
    result = client.embed([query], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]
