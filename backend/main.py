"""
TenderFlow — simple LangGraph agent entry point.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env from the same directory as this file
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("TenderFlow starting up")
    try:
        from agents.graph import get_graph
        get_graph()
        logger.info("LangGraph graph compiled OK")
    except Exception as e:
        logger.warning(f"Graph warm-up failed: {e}")
    yield
    logger.info("TenderFlow shutting down")


app = FastAPI(
    title="TenderFlow",
    description="AI-powered tender response agent — ISTARI @ Q-Hack 2026",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routers import tender as tender_router  # noqa: E402
app.include_router(tender_router.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "TenderFlow", "version": "0.1.0"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TenderFlow backend")
    parser.add_argument("--debug", action="store_true", help="Launch Gradio debug UI instead of the API server")
    parser.add_argument("--port", type=int, default=7860, help="Port for debug UI (default: 7860)")
    args = parser.parse_args()

    if args.debug:
        import importlib.util
        _ui_path = Path(__file__).parent.parent / "debug_ui" / "app.py"
        _spec = importlib.util.spec_from_file_location("debug_ui.app", _ui_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mod.launch(port=args.port)
    else:
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
