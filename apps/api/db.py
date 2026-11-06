import hashlib
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
        access_token_hash TEXT NOT NULL,
        rule_set TEXT NOT NULL DEFAULT 'municipal_billing',
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days')
    )""",
    """CREATE TABLE IF NOT EXISTS evidence_items (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        seq INT NOT NULL,
        kind TEXT NOT NULL,
        source_job_id TEXT,
        summary TEXT NOT NULL,
        derived_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS case_receipts (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        source_receipt_id TEXT,
        kind TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        content_json JSONB,
        blob_base64 TEXT,
        bytes BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS clocks (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        name TEXT NOT NULL,
        starts_at TIMESTAMPTZ,
        due_at DATE NOT NULL,
        state TEXT NOT NULL DEFAULT 'upcoming',
        rule_ref TEXT,
        source_evidence_id TEXT,
        met_at TIMESTAMPTZ,
        late BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        text TEXT NOT NULL,
        due_at DATE,
        state TEXT NOT NULL DEFAULT 'open',
        is_next BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS packs (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        version INT NOT NULL,
        pdf_path TEXT,
        zip_path TEXT,
        evidence_seq_max INT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_detail TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (case_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS replies (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed',
        raw_text TEXT NOT NULL,
        extraction_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        confirmation_json JSONB,
        evidence_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS case_events (
        id BIGSERIAL PRIMARY KEY,
        case_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        detail TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
)


def init_db() -> None:
    if pool.closed:
        pool.open(wait=True)
    with pool.connection() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        _migrate_case_tables(conn)


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            """SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s""",
            (table, column),
        ).fetchone()
    )


def _migrate_case_tables(conn) -> None:
    conn.execute(
        "ALTER TABLE packs ADD COLUMN IF NOT EXISTS snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    conn.execute("ALTER TABLE packs ADD COLUMN IF NOT EXISTS error_detail TEXT")
    conn.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS access_token_hash TEXT")
    conn.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS rule_set TEXT")
    conn.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")

    if _column_exists(conn, "cases", "access_token"):
        legacy_tokens = conn.execute(
            "SELECT id, access_token FROM cases WHERE access_token_hash IS NULL"
        ).fetchall()
        for case in legacy_tokens:
            token_hash = hashlib.sha256(case["access_token"].encode("utf-8")).hexdigest()
            conn.execute(
                "UPDATE cases SET access_token_hash = %s WHERE id = %s",
                (token_hash, case["id"]),
            )
        conn.execute("ALTER TABLE cases DROP COLUMN access_token")

    if _column_exists(conn, "cases", "template"):
        conn.execute(
            """UPDATE cases SET rule_set = COALESCE(NULLIF(rule_set, ''), template, 'municipal_billing')
               WHERE rule_set IS NULL OR rule_set = ''"""
        )
    conn.execute(
        "UPDATE cases SET rule_set = 'municipal_billing' WHERE rule_set IS NULL OR rule_set = ''"
    )
    conn.execute("ALTER TABLE cases ALTER COLUMN access_token_hash SET NOT NULL")
    conn.execute("ALTER TABLE cases ALTER COLUMN rule_set SET DEFAULT 'municipal_billing'")
    conn.execute("ALTER TABLE cases ALTER COLUMN rule_set SET NOT NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS cases_access_token_hash_idx ON cases (access_token_hash)"
    )

    conn.execute("ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS seq INT")
    conn.execute("ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS kind TEXT")
    conn.execute("ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS source_job_id TEXT")
    conn.execute(
        "ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS derived_facts JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    if _column_exists(conn, "evidence_items", "job_id"):
        conn.execute(
            "UPDATE evidence_items SET source_job_id = job_id WHERE source_job_id IS NULL"
        )
    if _column_exists(conn, "evidence_items", "claim_ref"):
        conn.execute("ALTER TABLE evidence_items ALTER COLUMN claim_ref DROP NOT NULL")
    conn.execute(
        """WITH next_seq AS (
               SELECT case_id, COALESCE(MAX(seq), 0) AS max_seq
               FROM evidence_items GROUP BY case_id
           ), unnumbered AS (
               SELECT evidence.id,
                      next_seq.max_seq + ROW_NUMBER() OVER (
                          PARTITION BY evidence.case_id ORDER BY evidence.created_at, evidence.id
                      ) AS seq
               FROM evidence_items AS evidence
               JOIN next_seq ON next_seq.case_id = evidence.case_id
               WHERE evidence.seq IS NULL
           )
           UPDATE evidence_items AS evidence SET seq = unnumbered.seq
           FROM unnumbered WHERE evidence.id = unnumbered.id"""
    )
    if _column_exists(conn, "evidence_items", "job_id"):
        conn.execute(
            """UPDATE evidence_items AS evidence
               SET kind = CASE WHEN jobs.lens IN ('link', 'bill', 'letter', 'reply') THEN jobs.lens ELSE 'note' END
               FROM jobs WHERE evidence.source_job_id = jobs.id AND evidence.kind IS NULL"""
        )
    conn.execute("UPDATE evidence_items SET kind = 'note' WHERE kind IS NULL")
    conn.execute("ALTER TABLE evidence_items ALTER COLUMN seq SET NOT NULL")
    conn.execute("ALTER TABLE evidence_items ALTER COLUMN kind SET NOT NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS evidence_items_case_seq_idx ON evidence_items (case_id, seq)"
    )

    for sql in (
        "ALTER TABLE clocks ADD COLUMN IF NOT EXISTS name TEXT",
        "ALTER TABLE clocks ADD COLUMN IF NOT EXISTS starts_at TIMESTAMPTZ",
        "ALTER TABLE clocks ADD COLUMN IF NOT EXISTS due_at DATE",
        "ALTER TABLE clocks ADD COLUMN IF NOT EXISTS rule_ref TEXT",
        "ALTER TABLE clocks ADD COLUMN IF NOT EXISTS source_evidence_id TEXT",
        "ALTER TABLE clocks ADD COLUMN IF NOT EXISTS met_at TIMESTAMPTZ",
        "ALTER TABLE clocks ADD COLUMN IF NOT EXISTS late BOOLEAN NOT NULL DEFAULT FALSE",
    ):
        conn.execute(sql)
    if _column_exists(conn, "clocks", "label"):
        conn.execute("ALTER TABLE clocks ALTER COLUMN label DROP NOT NULL")
        conn.execute("UPDATE clocks SET name = label WHERE name IS NULL")
    if _column_exists(conn, "clocks", "due_date"):
        conn.execute("ALTER TABLE clocks ALTER COLUMN due_date DROP NOT NULL")
        conn.execute("UPDATE clocks SET due_at = due_date WHERE due_at IS NULL")
    conn.execute("UPDATE clocks SET name = 'Deadline' WHERE name IS NULL")
    conn.execute("ALTER TABLE clocks ALTER COLUMN name SET NOT NULL")
    conn.execute("ALTER TABLE clocks ALTER COLUMN due_at SET NOT NULL")


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