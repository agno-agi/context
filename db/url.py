"""
Database URL
============
"""

from os import getenv
from urllib.parse import quote


def build_db_url() -> str:
    """Build database URL from environment variables.

    Supports three formats (checked in order):
    1. DATABASE_PUBLIC_URL — Railway's public proxy URL (for local scripts)
    2. DATABASE_URL — Railway's internal URL (for deployed services)
    3. DB_* env vars — explicit config (docker compose default)
    """
    # Railway URLs (postgresql:// -> postgresql+psycopg://)
    for var in ("DATABASE_PUBLIC_URL", "DATABASE_URL"):
        url = getenv(var)
        if url and url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)

    # Explicit config
    driver = getenv("DB_DRIVER", "postgresql+psycopg")
    user = getenv("DB_USER", "context")
    password = quote(getenv("DB_PASS", "context"), safe="")
    host = getenv("DB_HOST", "localhost")
    port = getenv("DB_PORT", "5432")
    database = getenv("DB_DATABASE", "context")

    return f"{driver}://{user}:{password}@{host}:{port}/{database}"


db_url = build_db_url()
