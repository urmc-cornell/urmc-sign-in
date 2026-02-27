from supabase import create_client
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


def get_client(env: str = "production"):
    """Return a fresh Supabase client for the given environment."""
    if env == "staging":
        if not _staging_url or not _staging_key:
            raise Exception("Staging Supabase credentials not configured. Add STAGING_SUPABASE_URL and STAGING_SUPABASE_SERVICE_KEY to your .env file.")
        return create_client(_staging_url, _staging_key)
    return create_client(_prod_url, _prod_key)


def get_supabase_url(env: str = "production"):
    """Return the Supabase URL for the given environment (for constructing public URLs)."""
    if env == "staging":
        return STAGING_SUPABASE_URL
    return PROD_SUPABASE_URL
