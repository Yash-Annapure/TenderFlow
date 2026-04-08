"""
Central configuration — all secrets and tunable parameters read from .env.
Never import raw os.environ elsewhere; always use `from config.settings import settings`.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str

    # ── OpenAI (embeddings) ───────────────────────────────────────────────────
    openai_api_key: str

    # ── Supabase ──────────────────────────────────────────────────────────────
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    # Transaction-mode pooler URL required for langgraph-checkpoint-postgres
    supabase_db_url: str

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Retrieval ─────────────────────────────────────────────────────────────
    retrieval_top_k_default: int = 6
    retrieval_top_k_cv: int = 3
    retrieval_threshold: float = 0.60

    # ── HITL ──────────────────────────────────────────────────────────────────
    max_hitl_iterations: int = 3

    # ── Output ────────────────────────────────────────────────────────────────
    default_output_format: str = "docx"

    # ── Paths ─────────────────────────────────────────────────────────────────
    kb_seed_dir: str = "../Knowledge Base/kb"
    uploads_dir: str = "./uploads"
    outputs_dir: str = "./outputs"

    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_key: str = "change-me-before-demo"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
