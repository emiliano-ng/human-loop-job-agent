"""SQLite cache of scored postings."""

import sqlite3
import hashlib
import json
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "job_agent_cache.db"


def _description_hash(description: str) -> str:
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scored_postings (
                source TEXT NOT NULL,
                company TEXT NOT NULL,
                posting_id TEXT NOT NULL,
                description_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                location TEXT,
                url TEXT NOT NULL,
                fit_score INTEGER NOT NULL,
                rationale TEXT,
                hard_flags_json TEXT,
                skill_ids_json TEXT,
                project_ids_json TEXT,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_scored_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (source, company, posting_id)
            )
            """
        )
        conn.commit()


def get_cached(source: str, company: str, posting_id: str, description: str):
    """Returns the cached row dict if this exact posting (by content hash) was already scored, else None."""
    desc_hash = _description_hash(description)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM scored_postings
            WHERE source = ? AND company = ? AND posting_id = ? AND description_hash = ?
            """,
            (source, company, posting_id, desc_hash),
        ).fetchone()
    return dict(row) if row else None


def save_scored(posting, scored):
    """Persists a scored posting for later runs."""
    desc_hash = _description_hash(posting.description)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO scored_postings
                (source, company, posting_id, description_hash, title, location, url,
                 fit_score, rationale, hard_flags_json, skill_ids_json, project_ids_json,
                 last_scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source, company, posting_id) DO UPDATE SET
                description_hash = excluded.description_hash,
                title = excluded.title,
                location = excluded.location,
                url = excluded.url,
                fit_score = excluded.fit_score,
                rationale = excluded.rationale,
                hard_flags_json = excluded.hard_flags_json,
                skill_ids_json = excluded.skill_ids_json,
                project_ids_json = excluded.project_ids_json,
                last_scored_at = datetime('now')
            """,
            (
                posting.source, posting.company, posting.posting_id, desc_hash,
                posting.title, posting.location, posting.url,
                scored.fit_score, scored.rationale,
                json.dumps(scored.hard_flags), json.dumps(scored.skill_ids), json.dumps(scored.project_ids),
            ),
        )
        conn.commit()


def get_cached_by_url(url: str):
    """Look up a previously-scored posting by its URL, for the `draft` command."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM scored_postings WHERE url = ?", (url,)).fetchone()
    return dict(row) if row else None


def all_cached(min_score: int = 0):
    """For the `list` command: everything cached above a score threshold, freshest first."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM scored_postings
            WHERE fit_score >= ?
            ORDER BY fit_score DESC, last_scored_at DESC
            """,
            (min_score,),
        ).fetchall()
    return [dict(r) for r in rows]
