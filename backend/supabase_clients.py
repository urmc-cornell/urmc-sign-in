from supabase import create_client
from supabase.lib.client_options import ClientOptions
import os
from dotenv import load_dotenv
from pathlib import Path

# Explicitly load .env from project root
load_dotenv(Path(__file__).parent.parent / '.env', override=True)

_prod_url = os.getenv("SUPABASE_URL")
_prod_key = os.getenv("SUPABASE_SERVICE_KEY")
_staging_url = os.getenv("STAGING_SUPABASE_URL")
_staging_key = os.getenv("STAGING_SUPABASE_SERVICE_KEY")

PROD_SUPABASE_URL = _prod_url
STAGING_SUPABASE_URL = _staging_url

DEFAULT_STORAGE_TIMEOUT = 60  # seconds (up from library default of 20)


def get_client(env: str = "production", storage_timeout: int = DEFAULT_STORAGE_TIMEOUT):
    """Return a fresh Supabase client for the given environment."""
    options = ClientOptions(storage_client_timeout=storage_timeout)
    if env == "staging":
        if not _staging_url or not _staging_key:
            raise Exception("Staging Supabase credentials not configured. Add STAGING_SUPABASE_URL and STAGING_SUPABASE_SERVICE_KEY to your .env file.")
        return create_client(_staging_url, _staging_key, options)
    return create_client(_prod_url, _prod_key, options)


def get_supabase_url(env: str = "production"):
    """Return the Supabase URL for the given environment (for constructing public URLs)."""
    if env == "staging":
        return STAGING_SUPABASE_URL
    return PROD_SUPABASE_URL
