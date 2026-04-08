"""
Supabase client singletons.

Two clients are provided:
  - get_supabase()       — anon key, safe for read operations and authenticated user calls
  - get_supabase_admin() — service role key, used only for ingest/admin write operations

Never use the admin client in routes that handle untrusted user input.
"""

from functools import lru_cache
from supabase import create_client, Client
from config.settings import settings


@lru_cache()
def get_supabase() -> Client:
    """Anon-key client for standard reads and user-scoped writes."""
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@lru_cache()
def get_supabase_admin() -> Client:
    """Service-role client — admin ingest operations only."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
