"""
Reset script — wipes all tender job data and LangGraph checkpoints.
Run before a clean demo or test run:

    cd backend
    .venv/Scripts/python scripts/reset_jobs.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.supabase_client import get_supabase_admin
from config.settings import settings
import psycopg

TABLES_TO_CLEAR = [
    "tender_jobs",
]

# LangGraph checkpoint tables (created by PostgresSaver.setup())
CHECKPOINT_TABLES = [
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
]


def reset():
    supabase = get_supabase_admin()

    # Clear Supabase tables
    for table in TABLES_TO_CLEAR:
        try:
            supabase.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
            print(f"  ✓ Cleared {table}")
        except Exception as e:
            print(f"  ✗ Failed to clear {table}: {e}")

    # Clear LangGraph checkpoint tables via direct psycopg
    try:
        with psycopg.connect(settings.supabase_db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                for table in CHECKPOINT_TABLES:
                    try:
                        cur.execute(f"TRUNCATE TABLE {table} CASCADE")
                        print(f"  ✓ Truncated {table}")
                    except Exception as e:
                        print(f"  ✗ {table}: {e}")
    except Exception as e:
        print(f"  ✗ DB connection failed: {e}")

    # Remove any leftover output DOCX files
    import shutil
    from pathlib import Path
    for folder in ["outputs", "uploads"]:
        p = Path(__file__).parent.parent / folder
        if p.exists():
            for f in p.iterdir():
                if f.is_file():
                    f.unlink()
            print(f"  ✓ Cleared {folder}/")

    print("\nDone — fresh start ready.")


if __name__ == "__main__":
    print("Resetting tender jobs and LangGraph checkpoints...\n")
    reset()
