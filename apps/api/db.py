import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row, "autocommit": True},
    open=False,
)

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        lens TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        input_ref TEXT NOT NULL,
        result_json JSONB,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS job_events (
        id SERIAL PRIMARY KEY,
        job_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        detail TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS receipts (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        sha256 TEXT,
        content_json JSONB,
        blob_base64 TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS model_calls (
        id SERIAL PRIMARY KEY,
        job_id TEXT,
        role TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_tokens INT DEFAULT 0,
        completion_tokens INT DEFAULT 0,
        latency_ms INT DEFAULT 0,
        outcome TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        access_token TEXT UNIQUE NOT NULL,
        template TEXT NOT NULL DEFAULT 'municipal_billing',
        title TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days')
    )""",
    """CREATE TABLE IF NOT EXISTS evidence_items (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        job_id TEXT,
        claim_ref TEXT NOT NULL,
        summary TEXT NOT NULL,
        receipt_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS clocks (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        label TEXT NOT NULL,
        due_date DATE NOT NULL,
        state TEXT NOT NULL DEFAULT 'upcoming',
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
)


def init_db() -> None:
    if pool.closed:
        pool.open(wait=True)
    with pool.connection() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)


def add_event(job_id: str, event_type: str, detail: str) -> None:
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO job_events (job_id, event_type, detail) VALUES (%s, %s, %s)",
            (job_id, event_type, detail),
        )


def claim_next_job() -> dict | None:
    with pool.connection() as conn:
        with conn.transaction():
            row = conn.execute(
                """SELECT * FROM jobs
                   WHERE status = 'queued'
                   ORDER BY created_at ASC
                   LIMIT 1
                   FOR UPDATE SKIP LOCKED"""
            ).fetchone()
            if row:
                row = conn.execute(
                    "UPDATE jobs SET status = 'running' WHERE id = %s RETURNING *",
                    (row["id"],),
                ).fetchone()
            return row