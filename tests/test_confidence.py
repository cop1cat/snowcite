"""T27: auto_high / auto_low confidence grades + migration from legacy 'auto'."""

import sqlite3
from pathlib import Path

import pytest

from snowcite.db import _initialized, init_db
from snowcite.persistence import persist_papers
from snowcite.projects import create_project_dir
from snowcite.sources.base import Paper
from snowcite.tools.review import (
    get_low_confidence_reviews,
    get_unreviewed_papers,
    set_review_status,
)


@pytest.mark.asyncio
async def test_set_review_status_accepts_high_and_low(tmp_project: Path):
    await persist_papers(
        [
            Paper(source="arxiv", source_id="a", title="Paper A"),
            Paper(source="arxiv", source_id="b", title="Paper B"),
        ]
    )

    await set_review_status([1], "approved", reason="match X", reviewed_by="auto_high")
    await set_review_status([2], "rejected", reason="off-topic", reviewed_by="auto_low")

    unrevd = await get_unreviewed_papers(limit=10)
    assert len(unrevd) == 0  # both were reviewed


@pytest.mark.asyncio
async def test_get_low_confidence_reviews_filters_correctly(tmp_project: Path):
    await persist_papers(
        [
            Paper(source="arxiv", source_id="a", title="High-confidence approve"),
            Paper(source="arxiv", source_id="b", title="Low-confidence approve"),
            Paper(source="arxiv", source_id="c", title="User-confirmed"),
        ]
    )
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")
    await set_review_status([2], "approved", reason="r", reviewed_by="auto_low")
    await set_review_status([3], "rejected", reason="r", reviewed_by="user")

    low = await get_low_confidence_reviews()
    assert len(low) == 1
    assert low[0]["title"] == "Low-confidence approve"


@pytest.mark.asyncio
async def test_low_confidence_filter_by_status(tmp_project: Path):
    await persist_papers(
        [
            Paper(source="arxiv", source_id="a", title="Low approve"),
            Paper(source="arxiv", source_id="b", title="Low reject"),
        ]
    )
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_low")
    await set_review_status([2], "rejected", reason="r", reviewed_by="auto_low")

    low_rej = await get_low_confidence_reviews(status="rejected")
    assert len(low_rej) == 1
    assert low_rej[0]["title"] == "Low reject"


@pytest.mark.asyncio
async def test_migration_legacy_auto_becomes_auto_high(tmp_path: Path, monkeypatch):
    """Simulate a pre-T27 DB created with the old CHECK constraint."""
    create_project_dir(tmp_path)
    monkeypatch.setenv("SNOWCITE_PROJECT_ROOT", str(tmp_path))
    _initialized.clear()

    db_path = tmp_path / ".snowcite" / "papers.db"

    # Build legacy schema directly — pre-T27 CHECK allows only 'auto' | 'user'.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, source_id TEXT,
            doi TEXT, title TEXT NOT NULL,
            title_normalized TEXT NOT NULL,
            authors_json TEXT NOT NULL,
            year INTEGER, venue TEXT, abstract TEXT,
            pdf_url TEXT, bibtex TEXT, metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE reviews (
            paper_id INTEGER PRIMARY KEY REFERENCES papers(id),
            status TEXT NOT NULL CHECK (status IN ('approved','maybe','rejected','unreviewed')),
            reason TEXT, note TEXT,
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT CHECK (reviewed_by IN ('auto','user'))
        );
        INSERT INTO papers (source, source_id, title, title_normalized, authors_json)
            VALUES ('arxiv', 'x1', 'Legacy', 'legacy', '[]');
        INSERT INTO reviews (paper_id, status, reason, reviewed_by)
            VALUES (1, 'approved', 'old', 'auto');
        """
    )
    conn.commit()
    conn.close()

    # Run migration via init_db.
    await init_db(db_path)

    # Legacy 'auto' should now be 'auto_high'.
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT reviewed_by FROM reviews WHERE paper_id=1").fetchone()
    conn.close()
    assert row[0] == "auto_high"


@pytest.mark.asyncio
async def test_migration_is_idempotent(tmp_project: Path):
    """Running init_db twice on an already-migrated DB should be a no-op."""
    await init_db()  # second call — db already has new CHECK
    await init_db()  # third call
    # If this didn't raise, we're good. Table integrity by inserting a row:
    await persist_papers([Paper(source="arxiv", source_id="z", title="Z")])
    await set_review_status([1], "approved", reason="x", reviewed_by="auto_high")
