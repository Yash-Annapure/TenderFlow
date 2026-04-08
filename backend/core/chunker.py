"""
Text chunking — paragraph-boundary-aware recursive splitting.

Settings (from design doc):
  chunk_size    = 600 characters  (fits under Claude context limits with room for metadata)
  chunk_overlap = 80 characters   (preserves cross-chunk sentence continuity)

Chunks shorter than MIN_CHUNK_LEN are discarded — they rarely carry retrievable signal.
"""

import logging
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

MIN_CHUNK_LEN = 50

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=600,
    chunk_overlap=80,
    length_function=len,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def chunk_text(text: str) -> list[str]:
    """
    Split text into embedding-ready chunks.
    Filters out chunks that are too short to be useful.
    """
    if not text or not text.strip():
        return []

    raw_chunks = _splitter.split_text(text)
    chunks = [c.strip() for c in raw_chunks if len(c.strip()) >= MIN_CHUNK_LEN]

    logger.debug(f"Chunked {len(text)} chars → {len(chunks)} chunks")
    return chunks
