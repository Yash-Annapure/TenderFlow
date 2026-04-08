"""
Embedding wrapper using OpenAI text-embedding-3-small (512-dim vectors).

All KB chunks and retrieval queries go through this module.
The client is instantiated once and reused — never recreated per call.
"""

import logging
from functools import lru_cache
from openai import OpenAI
from config.settings import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 512
OPENAI_BATCH_LIMIT = 512  # max texts per request


@lru_cache()
def _get_client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of document chunks for storage in the KB.
    Handles batching automatically.
    """
    if not texts:
        return []

    client = _get_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), OPENAI_BATCH_LIMIT):
        batch = texts[i : i + OPENAI_BATCH_LIMIT]
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
            dimensions=EMBEDDING_DIMS,
        )
        all_embeddings.extend([item.embedding for item in response.data])
        logger.debug(f"Embedded batch {i // OPENAI_BATCH_LIMIT + 1}: {len(batch)} chunks")

    return all_embeddings


def embed_query(query: str) -> list[float]:
    """Embed a single retrieval query."""
    client = _get_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[query],
        dimensions=EMBEDDING_DIMS,
    )
    return response.data[0].embedding


def embed_queries(queries: list[str]) -> list[list[float]]:
    """Embed multiple retrieval queries in one API call."""
    if not queries:
        return []
    client = _get_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=queries,
        dimensions=EMBEDDING_DIMS,
    )
    return [item.embedding for item in response.data]
