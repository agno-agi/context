"""
Database Schema
===============

@context manages context using a set of tables: projects, meetings, reminders, notes, contacts, updates.

Every table is declared once, in TABLES. From that one list we generate:

1. The `CREATE TABLE` DDL applied at startup (`create_tables`).
2. Usage instructions so the agent knows the tables (`agent_instructions`).

To add a table, edit TABLES — the DDL and the agent instructions update automatically.
"""

from dataclasses import dataclass

from sqlalchemy import text

# Database schema the context tables live in.
SCHEMA = "context"


@dataclass
class Column:
    name: str
    type: str  # SQL type: "TEXT", "TIMESTAMPTZ", "TEXT[]", …
    modifiers: str = ""  # e.g. "NOT NULL DEFAULT 'pending'"
    hint: str = ""  # shown to the agent, e.g. enum values


@dataclass
class Table:
    name: str
    description: str  # one line, shown to the agent
    columns: list[Column]  # the table's own columns; id + ALWAYS_INCLUDED_COLUMNS are added around them
    agent_visible: bool = True  # False hides the table from the agent (e.g. the updates queue)


# Appended to every table after its own columns (`id SERIAL PRIMARY KEY` is always added as the first column).
ALWAYS_INCLUDED_COLUMNS = [
    "user_id TEXT NOT NULL",
    "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
]

TABLES = [
    Table(
        name="projects",
        description="ongoing work the owner is driving or watching",
        columns=[
            Column("name", "TEXT", "NOT NULL"),
            Column("status", "TEXT", hint="active/paused/done"),
            Column("notes", "TEXT"),
            Column("tags", "TEXT[]", "NOT NULL DEFAULT '{}'"),
        ],
    ),
    Table(
        name="meetings",
        description="calls and meetings on the calendar",
        columns=[
            Column("title", "TEXT", "NOT NULL"),
            Column("starts_at", "TIMESTAMPTZ"),
            Column("attendees", "TEXT[]", "NOT NULL DEFAULT '{}'", hint="names or emails"),
            Column("notes", "TEXT"),
            Column("tags", "TEXT[]", "NOT NULL DEFAULT '{}'"),
        ],
    ),
    Table(
        name="reminders",
        description="follow-ups with a due date",
        columns=[
            Column("title", "TEXT", "NOT NULL"),
            Column("notes", "TEXT"),
            Column("due_at", "TIMESTAMPTZ"),
            Column("status", "TEXT", "NOT NULL DEFAULT 'pending'", hint="pending/done/dropped"),
            Column("tags", "TEXT[]", "NOT NULL DEFAULT '{}'"),
        ],
    ),
    Table(
        name="notes",
        description="free-form notes",
        columns=[
            Column("title", "TEXT", "NOT NULL"),
            Column("body", "TEXT", "NOT NULL DEFAULT ''"),
            Column("tags", "TEXT[]", "NOT NULL DEFAULT '{}'"),
            Column("source_url", "TEXT"),
        ],
    ),
    Table(
        name="contacts",
        description="people",
        columns=[
            Column("name", "TEXT", "NOT NULL"),
            Column("role", "TEXT", hint="job title"),
            Column("emails", "TEXT[]", "NOT NULL DEFAULT '{}'"),
            Column("phone", "TEXT"),
            Column("company", "TEXT"),
            Column("tags", "TEXT[]", "NOT NULL DEFAULT '{}'"),
            Column("notes", "TEXT"),
        ],
    ),
    Table(
        name="updates",
        description="inbound queue (managed by submit_update / rundown / acknowledge)",
        agent_visible=False,
        columns=[
            Column("title", "TEXT", "NOT NULL"),
            Column("body", "TEXT", "NOT NULL DEFAULT ''"),
            Column("from_person", "TEXT"),
            Column("source", "TEXT"),
            Column("source_url", "TEXT"),
            Column("work_status", "TEXT", "NOT NULL DEFAULT 'done'", hint="done/in_progress/blocked"),
            Column("ack_status", "TEXT", "NOT NULL DEFAULT 'new'", hint="new/briefed/acknowledged"),
            Column("briefed_at", "TIMESTAMPTZ"),
            Column("acknowledged_at", "TIMESTAMPTZ"),
            Column("tags", "TEXT[]", "NOT NULL DEFAULT '{}'"),
        ],
    ),
]


def create_tables() -> None:
    """Create the schema and tables managed by @context. Runs at startup; reruns are safe."""
    from db.session import get_sql_engine  # imported here to avoid a circular import

    statements = [f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"]
    for table in TABLES:
        columns = (
            ["id SERIAL PRIMARY KEY"]
            + [" ".join(filter(None, (c.name, c.type, c.modifiers))) for c in table.columns]
            + ALWAYS_INCLUDED_COLUMNS
        )
        body = ",\n    ".join(columns)
        statements.append(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.{table.name} (\n    {body}\n)")

    with get_sql_engine().begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def agent_instructions() -> str:
    """Markdown list of the agent-visible tables, spliced into the agent's instructions.

    Contains no `{...}` placeholders, so it's safe to `.replace` into
    instruction strings.
    """
    lines = []
    for table in TABLES:
        if not table.agent_visible:
            continue
        labels = []
        for c in table.columns:
            label = c.name if c.type == "TEXT" else f"{c.name} {c.type}"
            labels.append(f"`{label}` ({c.hint})" if c.hint else f"`{label}`")
        lines.append(f"- `{SCHEMA}.{table.name}` — {table.description}: {', '.join(labels)}")
    return "\n".join(lines)
