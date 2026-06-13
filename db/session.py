"""
Database Session
================

Two SQL engines, split by role:

- `get_sql_engine()` — read/write, scoped to the `context` schema.
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
    """Read/write engine for the `context` schema."""
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
    event.listen(engine, "before_cursor_execute", _guard_non_context_writes)
    return engine


@lru_cache(maxsize=1)
def get_readonly_engine() -> Engine:
    """Read-only engine for the `context` schema."""
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


# Write guard for get_sql_engine: catches the write shapes agents actually
# produce against public.* / ai.*. Not exhaustive (misses COPY, GRANT, DO
# blocks); search_path + database grants are the primary defense.
_NON_CONTEXT_WRITE_RE = re.compile(
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
    """,
)


def _guard_non_context_writes(conn, cursor, statement, parameters, context, executemany) -> None:
    """Reject DDL/DML targeting non-context schemas on the read/write engine."""
    if _NON_CONTEXT_WRITE_RE.search(statement):
        raise RuntimeError(
            "Cannot write to the public or ai schema from the context engine; writes must target the context schema."
        )
