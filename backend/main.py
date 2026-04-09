"""
TenderFlow — FastAPI application entry point.

Mount order:
  /ingest   — document ingestion pipeline
  /tender   — agent job management + file download (tender.py)
  /tender   — HITL review/submit (hitl.py, same prefix, different paths)
  /kb       — knowledge base management

CORS is open for development. Tighten origins before any public deployment.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import ingest, hitl, kb, tender
from config.settings import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialise the LangGraph checkpointer on startup so the first request
    doesn't pay the setup cost.
    """
    logger.info("TenderFlow starting up")
    os.makedirs(settings.uploads_dir, exist_ok=True)
    os.makedirs(settings.outputs_dir, exist_ok=True)

    # Warm up the graph + run checkpointer.setup() (idempotent)
    try:
        from agents.graph import get_graph
        get_graph()
        logger.info("LangGraph compiled and checkpointer ready")
    except Exception as e:
        logger.warning(f"Graph warm-up failed (will retry on first request): {e}")

    yield

    logger.info("TenderFlow shutting down")


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="TenderFlow",
    description="AI-powered tender response agent — ISTARI @ Q-Hack 2026",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — open for hackathon demo; restrict origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(ingest.router)
app.include_router(tender.router)
app.include_router(hitl.router)   # Same /tender prefix, different paths (/review, /submit)
app.include_router(kb.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "TenderFlow", "version": "0.1.0"}

if __name__ == "__main__":
    import uvicorn
    # When run directly (e.g. `python main.py`), start the uvicorn server
    # to provide output and run the application.
    logger.info("Starting uvicorn server directly from main.py...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
