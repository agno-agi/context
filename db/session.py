"""
Database Session
================

Two SQL engines, split by role:

- `get_sql_engine()` — read/write, scoped to the `crm` schema.
  A SQLAlchemy write guard rejects writes against `public` or `ai` (agno's schema).
- `get_readonly_engine()` — read-only at the Postgres level
  (`default_transaction_read_only=on`); can't be bypassed by prompt tricks.

Plus `get_postgres_db()` — agno's own persistence (sessions, memory, evals).
"""

import re
from functools import lru_cache

from agno.db.postgres import PostgresDb
from sqlalchemy import Engine, create_engine, event, text

from db.schema import SCHEMA
from db.url import db_url


@lru_cache(maxsize=1)
def get_sql_engine() -> Engine:
    """Read/write engine for the `crm` schema."""
    bootstrap = create_engine(db_url)
    with bootstrap.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    bootstrap.dispose()

    engine = create_engine(
        db_url,
        connect_args={"options": f"-c search_path={SCHEMA},public"},
        pool_size=10,
        max_overflow=20,
    )
    event.listen(engine, "before_cursor_execute", _guard_foreign_schema_writes)
    return engine


@lru_cache(maxsize=1)
def get_readonly_engine() -> Engine:
    """Read-only engine for the `crm` schema."""
    return create_engine(
        db_url,
        connect_args={
            "options": f"-c default_transaction_read_only=on -c search_path={SCHEMA},public",
        },
        pool_size=10,
        max_overflow=20,
    )


def get_postgres_db() -> PostgresDb:
    """Agno persistence: agent sessions, memory, eval results."""
    return PostgresDb(id="context-db", db_url=db_url)


# Write guard for get_sql_engine — a heuristic belt, NOT the primary defense. The
# real confinement is the connection's search_path=crm,public, so an unqualified
# write lands in `crm`. This regex backs that up by rejecting:
#   1. writes explicitly qualified to public.* / ai.* (agno's schema), and
#   2. statements that would subvert the search_path confinement — repointing
#      search_path, switching/altering roles, or GRANT/REVOKE/COPY.
# Each is anchored to a statement boundary (start-of-string or after `;`) so a
# value like INSERT ... VALUES ('grant me access') can't false-trigger. Not
# exhaustive (DO blocks, dynamic SQL); the full fix is a least-privilege DB role,
# not applied here because the compose/Railway role owns its database. See docs/SECURITY.md.
_FOREIGN_SCHEMA_WRITE_RE = re.compile(
    r"""(?ix)
    (?:create|alter|drop)\s+
    (?:or\s+replace\s+)?
    (?:(?:temp|temporary|unlogged|materialized)\s+)?
    (?:table|view|index|sequence|function|procedure|trigger|type)\s+
    (?:if\s+(?:not\s+)?exists\s+)?
    "?(?:public|ai)"?\s*\.
    |
    insert\s+into\s+"?(?:public|ai)"?\s*\.
    |
    update\s+"?(?:public|ai)"?\s*\.
    |
    delete\s+from\s+"?(?:public|ai)"?\s*\.
    |
    truncate\s+(?:table\s+)?"?(?:public|ai)"?\s*\.
    |
    # search_path / role manipulation and privilege grants — anchored to a
    # statement boundary so they only match real leading statements.
    (?:\A|;)\s*(?:set|reset)\s+(?:local\s+|session\s+)?(?:role|search_path)\b
    |
    (?:\A|;)\s*(?:alter|create|drop)\s+(?:role|user)\b
    |
    (?:\A|;)\s*(?:grant|revoke)\b
    |
    (?:\A|;)\s*copy\b
    """,
)


def _guard_foreign_schema_writes(conn, cursor, statement, parameters, context, executemany) -> None:
    """Reject DDL/DML targeting foreign schemas (public/ai) on the read/write engine."""
    if _FOREIGN_SCHEMA_WRITE_RE.search(statement):
        raise RuntimeError(
            "Cannot write to the public or ai schema from the crm engine; writes must target the crm schema."
        )
