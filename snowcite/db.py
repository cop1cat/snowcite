import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from snowcite.projects import get_db_path


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    doi TEXT,
    title TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    authors_json TEXT NOT NULL,
    year INTEGER,
    venue TEXT,
    abstract TEXT,
    pdf_url TEXT,
    bibtex TEXT,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi
    ON papers(doi) WHERE doi IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_papers_title_norm
    ON papers(title_normalized);

CREATE TABLE IF NOT EXISTS reviews (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('approved','maybe','rejected','unreviewed')),
    reason TEXT,
    note TEXT,
    reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_by TEXT CHECK (reviewed_by IN ('auto_high','auto_low','user'))
);

CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);
CREATE INDEX IF NOT EXISTS idx_reviews_reviewed_by ON reviews(reviewed_by);

CREATE TABLE IF NOT EXISTS review_criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criteria_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS citations (
    source_paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    cited_paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK (direction IN ('references','citations')),
    PRIMARY KEY (source_paper_id, cited_paper_id, direction)
);

CREATE TABLE IF NOT EXISTS review_summary (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    summary TEXT NOT NULL,
    clusters_json TEXT NOT NULL,
    counts_snapshot_json TEXT NOT NULL,
    stale INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outline (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sections_json TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skeleton (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sections_json TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS section_content (
    name TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    word_count INTEGER,
    version INTEGER DEFAULT 1,
    polished INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    reason TEXT,
    reviewed_by TEXT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_history_paper ON review_history(paper_id);
CREATE INDEX IF NOT EXISTS idx_review_history_changed_at ON review_history(changed_at);

-- User-supplied research materials: interviews, code, documents, notes, datasets.
-- Cited inline alongside `papers` when the outline assigns them to a section; do
-- not land in the main bibliography — a separate Primary-sources appendix lists
-- them.
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('interview','code','document','note','dataset')),
    label TEXT NOT NULL,
    source_path TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    metadata_json TEXT DEFAULT '{}',
    included INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(type);
CREATE INDEX IF NOT EXISTS idx_artifacts_included ON artifacts(included);

CREATE TABLE IF NOT EXISTS project_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    author TEXT,
    supervisor TEXT,
    institution TEXT,
    department TEXT,
    year INTEGER,
    work_type TEXT,
    target_length TEXT,
    language TEXT DEFAULT 'en',
    discipline TEXT,
    standard TEXT DEFAULT 'plain',
    methodology TEXT,
    backend TEXT DEFAULT 'typst' CHECK (backend IN ('typst','latex')),
    review_strictness TEXT DEFAULT 'standard'
        CHECK (review_strictness IN ('lenient','standard','phd_committee')),
    deadline TEXT,
    extra_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


# Paths whose schema we've already applied this process + an asyncio.Lock per
# path to serialize init/migration under concurrent `get_connection()` callers.
_initialized: set[Path] = set()
_init_locks: dict[Path, asyncio.Lock] = {}


def _lock_for(path: Path) -> asyncio.Lock:
    lock = _init_locks.get(path)
    if lock is None:
        lock = asyncio.Lock()
        _init_locks[path] = lock
    return lock


async def _migrate_reviews_confidence(conn: aiosqlite.Connection) -> None:
    """T27: broaden `reviewed_by` from {auto,user} to {auto_high,auto_low,user}.

    SQLite CHECK constraints are baked into the table's stored DDL and don't
    update on `CREATE TABLE IF NOT EXISTS`. For pre-T27 databases we rebuild
    the table and remap `auto` → `auto_high` (the only sane default — pre-T27
    auto decisions were implicitly "high confidence").
    """
    cur = await conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='reviews'")
    row = await cur.fetchone()
    if row is None:
        return  # fresh DB
    if row[0] and "auto_high" in row[0]:
        return  # already migrated

    await conn.executescript(
        """
        CREATE TABLE reviews_new (
            paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('approved','maybe','rejected','unreviewed')),
            reason TEXT,
            note TEXT,
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT CHECK (reviewed_by IN ('auto_high','auto_low','user'))
        );
        INSERT INTO reviews_new
            SELECT paper_id, status, reason, note, reviewed_at,
                   CASE reviewed_by WHEN 'auto' THEN 'auto_high' ELSE reviewed_by END
            FROM reviews;
        DROP TABLE reviews;
        ALTER TABLE reviews_new RENAME TO reviews;
        CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);
        CREATE INDEX IF NOT EXISTS idx_reviews_reviewed_by ON reviews(reviewed_by);
        """
    )


async def init_db(db_path: Path | None = None) -> None:
    """Create schema in the active project's DB (or at `db_path` if given).

    Idempotent. Concurrent callers for the same path are serialized via a
    per-path `asyncio.Lock` so migrations can't race.
    """
    path = db_path if db_path is not None else get_db_path()
    resolved = path.resolve()

    async with _lock_for(resolved):
        if resolved in _initialized:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(path) as conn:
            await _migrate_reviews_confidence(conn)
            await conn.executescript(SCHEMA)
            await conn.commit()
        _initialized.add(resolved)


@asynccontextmanager
async def get_connection() -> AsyncIterator[aiosqlite.Connection]:
    """Async connection to the active project's DB.

    Raises `NoProjectError` if no `.snowcite/` exists in cwd or any parent.
    Applies schema lazily on first access per process (per path).
    """
    path = get_db_path()
    if path.resolve() not in _initialized:
        await init_db(path)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = aiosqlite.Row
        yield conn
