"""
Simple KB reader — walks the Knowledge Base directory and returns file contents.
Supports .txt, .md (plain text), .pdf (via PyMuPDF), .docx (via python-docx).
xlsx is skipped (too tabular to be useful as raw context).
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve KB path relative to this file: backend/ -> ../../Knowledge Base/kb
_BACKEND_DIR = Path(__file__).parent.parent
_KB_DIR = _BACKEND_DIR.parent / "Knowledge Base" / "kb"


def list_kb_files() -> list[dict]:
    """Return a list of all KB files with their paths and categories."""
    files = []
    if not _KB_DIR.exists():
        logger.warning(f"KB directory not found: {_KB_DIR}")
        return files

    for path in sorted(_KB_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".pdf", ".docx"}:
            category = path.parent.name if path.parent != _KB_DIR else "root"
            files.append({
                "path": str(path),
                "name": path.name,
                "category": category,
                "suffix": path.suffix.lower(),
            })
    return files


def read_kb_file(filepath: str) -> str:
    """Read a single KB file and return its text content."""
    path = Path(filepath)
    if not path.exists():
        return f"[File not found: {filepath}]"

    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[Error reading {path.name}: {e}]"

    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            text = "\n\n".join(page.get_text() for page in doc)
            doc.close()
            return text or f"[Empty PDF: {path.name}]"
        except Exception as e:
            return f"[Error reading PDF {path.name}: {e}]"

    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            return f"[Error reading DOCX {path.name}: {e}]"

    return f"[Unsupported format: {suffix}]"


def load_kb_context(categories: list[str] | None = None, max_chars_per_file: int = 4000) -> str:
    """
    Load KB content into a single string.
    Optionally filter by category (e.g. ["team_cvs", "methodology"]).
    Truncates each file to max_chars_per_file to keep token count manageable.
    """
    files = list_kb_files()
    if categories:
        files = [f for f in files if f["category"] in categories]

    parts = []
    for f in files:
        content = read_kb_file(f["path"])
        if content.startswith("["):
            continue  # skip errors
        content = content[:max_chars_per_file]
        parts.append(f"=== {f['category'].upper()}: {f['name']} ===\n{content}\n")

    return "\n".join(parts) if parts else "[No KB content loaded]"
