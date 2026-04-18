"""Review tools — criteria, status, progress, summary."""

import json
from typing import Any

from snowball.app import mcp
from snowball.db import get_connection
from snowball.types import ReviewedBy, Source, Status


async def _get_live_counts(conn: Any) -> dict[str, int]:
    cur = await conn.execute("SELECT COUNT(*) FROM papers")
    total = (await cur.fetchone())[0]
    counts = {"total": total, "approved": 0, "maybe": 0, "rejected": 0, "unreviewed": 0}
    cur = await conn.execute(
        "SELECT status, COUNT(*) FROM reviews GROUP BY status"
    )
    for row in await cur.fetchall():
        counts[row[0]] = row[1]
    return counts


async def _mark_summary_stale(conn: Any) -> None:
    await conn.execute(
        "UPDATE review_summary SET stale = 1 WHERE id = 1"
    )


# ─── Criteria ───────────────────────────────────────────────────────────────

@mcp.tool()
async def set_review_criteria(criteria_text: str) -> dict[str, int]:
    """Store inclusion/exclusion criteria (and optionally user-defined categories). Returns {id}."""
    async with get_connection() as conn:
        cur = await conn.execute(
            "INSERT INTO review_criteria (criteria_text) VALUES (?)",
            (criteria_text,),
        )
        await conn.commit()
        return {"id": cur.lastrowid}


@mcp.tool()
async def get_review_criteria() -> dict[str, Any] | None:
    """Latest criteria. Claude must call this before each review batch (drift guard)."""
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT id, criteria_text, created_at FROM review_criteria ORDER BY id DESC LIMIT 1"
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return dict(row)


# ─── Unreviewed batch ───────────────────────────────────────────────────────

@mcp.tool()
async def get_unreviewed_papers(
    limit: int = 20,
    source: Source | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict[str, Any]]:
    """Batch of unreviewed papers for pre-filtering."""
    query = """
        SELECT p.id, p.source, p.title, p.year, p.venue, p.abstract,
               p.authors_json, p.doi
        FROM papers p
        JOIN reviews r ON r.paper_id = p.id
        WHERE r.status = 'unreviewed'
    """
    params: list[Any] = []
    if source is not None:
        query += " AND p.source = ?"
        params.append(source)
    if year_from is not None:
        query += " AND p.year >= ?"
        params.append(year_from)
    if year_to is not None:
        query += " AND p.year <= ?"
        params.append(year_to)
    query += " ORDER BY p.id LIMIT ?"
    params.append(limit)

    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["authors"] = json.loads(d.pop("authors_json"))
        out.append(d)
    return out


# ─── Status ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def set_review_status(
    paper_ids: list[int],
    status: Status,
    reason: str,
    note: str | None = None,
    reviewed_by: ReviewedBy = "auto",
) -> dict[str, int]:
    """Batch-set review status with required reason (PRISMA trail). Marks summary as stale."""
    updated = 0
    async with get_connection() as conn:
        for pid in paper_ids:
            await conn.execute(
                """
                INSERT INTO reviews (paper_id, status, reason, note, reviewed_by, reviewed_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(paper_id) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    note = excluded.note,
                    reviewed_by = excluded.reviewed_by,
                    reviewed_at = CURRENT_TIMESTAMP
                """,
                (pid, status, reason, note, reviewed_by),
            )
            updated += 1
        await _mark_summary_stale(conn)
        await conn.commit()
    return {"updated": updated}


# ─── Progress ───────────────────────────────────────────────────────────────

@mcp.tool()
async def get_review_progress() -> dict[str, int]:
    """Counts: {total, approved, maybe, rejected, unreviewed}."""
    async with get_connection() as conn:
        return await _get_live_counts(conn)


# ─── Summary ────────────────────────────────────────────────────────────────

@mcp.tool()
async def save_review_summary(
    summary: str,
    clusters: list[dict[str, Any]],
) -> dict[str, str]:
    """UPSERT singleton review summary (≤500 words). Called after each review batch."""
    async with get_connection() as conn:
        counts = await _get_live_counts(conn)
        await conn.execute(
            """
            INSERT INTO review_summary (id, summary, clusters_json, counts_snapshot_json, stale, updated_at)
            VALUES (1, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                summary = excluded.summary,
                clusters_json = excluded.clusters_json,
                counts_snapshot_json = excluded.counts_snapshot_json,
                stale = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (summary, json.dumps(clusters), json.dumps(counts)),
        )
        await conn.commit()
    return {"status": "saved"}


@mcp.tool()
async def get_review_summary() -> dict[str, Any] | None:
    """Rolling summary + clusters + live counts + stale check.

    Returns None if no summary exists yet (first batch).
    Includes 'warnings' list if counts diverge from snapshot.
    """
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT summary, clusters_json, counts_snapshot_json, stale, updated_at "
            "FROM review_summary WHERE id = 1"
        )
        row = await cur.fetchone()
        if row is None:
            return None

        live_counts = await _get_live_counts(conn)

    snapshot = json.loads(row["counts_snapshot_json"])
    warnings: list[str] = []
    if row["stale"]:
        warnings.append("Summary is marked stale (papers added or statuses changed since last update)")
    for key in ("approved", "maybe", "rejected", "unreviewed"):
        snap_val = snapshot.get(key, 0)
        live_val = live_counts.get(key, 0)
        if snap_val != live_val:
            warnings.append(f"{key}: snapshot={snap_val}, actual={live_val}")

    return {
        "summary": row["summary"],
        "clusters": json.loads(row["clusters_json"]),
        "counts_snapshot": snapshot,
        "counts_live": live_counts,
        "stale": bool(row["stale"]),
        "updated_at": row["updated_at"],
        "warnings": warnings,
    }


# ─── Papers for writing ────────────────────────────────────────────────────

@mcp.tool()
async def get_papers_for_writing(
    cluster: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Approved papers with abstracts, optionally filtered by cluster topic.

    When cluster is given, filters to paper IDs listed in the matching cluster
    from the review summary. Without cluster, returns all approved papers.
    """
    paper_ids: list[int] | None = None
    if cluster:
        async with get_connection() as conn:
            cur = await conn.execute(
                "SELECT clusters_json FROM review_summary WHERE id = 1"
            )
            row = await cur.fetchone()
        if row:
            clusters = json.loads(row["clusters_json"])
            for c in clusters:
                if c.get("topic", "").lower() == cluster.lower():
                    paper_ids = c.get("paper_ids", [])
                    break
        if paper_ids is None:
            return []

    query = """
        SELECT p.id, p.source, p.doi, p.title, p.year, p.venue, p.abstract,
               p.authors_json, p.bibtex
        FROM papers p
        JOIN reviews r ON r.paper_id = p.id
        WHERE r.status = 'approved'
    """
    params: list[Any] = []
    if paper_ids is not None:
        placeholders = ",".join("?" * len(paper_ids))
        query += f" AND p.id IN ({placeholders})"
        params.extend(paper_ids)
    query += " ORDER BY p.year, p.id LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["authors"] = json.loads(d.pop("authors_json"))
        out.append(d)
    return out
