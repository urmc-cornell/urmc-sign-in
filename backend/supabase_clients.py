from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

# Production client
_prod_client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# Staging client (initialized only if env vars are set)
_staging_url = os.getenv("STAGING_SUPABASE_URL")
_staging_key = os.getenv("STAGING_SUPABASE_SERVICE_KEY")
_staging_client = create_client(_staging_url, _staging_key) if _staging_url and _staging_key else None

PROD_SUPABASE_URL = os.getenv("SUPABASE_URL")
STAGING_SUPABASE_URL = _staging_url


def get_client(env: str = "production"):
    """Return the Supabase client for the given environment."""
    if env == "staging":
        if not _staging_client:
            raise Exception("Staging Supabase credentials not configured. Add STAGING_SUPABASE_URL and STAGING_SUPABASE_SERVICE_KEY to your .env file.")
        return _staging_client
    return _prod_client


def get_supabase_url(env: str = "production"):
    """Return the Supabase URL for the given environment (for constructing public URLs)."""
    if env == "staging":
        return STAGING_SUPABASE_URL
    return PROD_SUPABASE_URL
