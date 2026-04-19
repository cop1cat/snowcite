"""Review tools — criteria, status, progress, summary."""

import json
import re
from typing import Any

import aiosqlite

from snowcite.app import mcp
from snowcite.db import get_connection
from snowcite.persistence import resolve_cluster_paper_ids
from snowcite.tools.common import paper_row_to_dict
from snowcite.types import ReviewedBy, Source, Status


# Same cite-ref shape recognised by bibliography.rewrite_cite_refs. Duplicated
# intentionally — counting cites in stored content shouldn't reach across to
# the document-render module.
_CITE_REF_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def _count_cites(content: str) -> int:
    """Count citation refs in a section body. `[1, 2]` counts as two cites."""
    total = 0
    for match in _CITE_REF_RE.finditer(content):
        total += len(re.split(r"[,;]", match.group(1)))
    return total


async def _get_live_counts(conn: aiosqlite.Connection) -> dict[str, int]:
    cur = await conn.execute("SELECT COUNT(*) FROM papers")
    total = (await cur.fetchone())[0]
    counts = {"total": total, "approved": 0, "maybe": 0, "rejected": 0, "unreviewed": 0}
    cur = await conn.execute("SELECT status, COUNT(*) FROM reviews GROUP BY status")
    for row in await cur.fetchall():
        counts[row[0]] = row[1]
    return counts


async def _mark_summary_stale(conn: aiosqlite.Connection) -> None:
    await conn.execute("UPDATE review_summary SET stale = 1 WHERE id = 1")


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
    include_abstracts: bool = False,
) -> list[dict[str, Any]]:
    """Batch of unreviewed papers for pre-filtering.

    By default (include_abstracts=False) returns compact records — title / year / venue /
    authors / doi. This keeps the context lean on large reviews. For borderline cases,
    pull the full abstract via `get_paper_details(paper_id)`.
    """
    # Two static query variants avoid a dynamic f-string (and the S608 lint).
    if include_abstracts:
        query = """
            SELECT p.id, p.source, p.title, p.year, p.venue, p.abstract,
                   p.authors_json, p.doi
            FROM papers p
            JOIN reviews r ON r.paper_id = p.id
            WHERE r.status = 'unreviewed'
        """
    else:
        query = """
            SELECT p.id, p.source, p.title, p.year, p.venue, NULL AS abstract,
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
    out = [paper_row_to_dict(r) for r in rows]
    if not include_abstracts:
        for d in out:
            d.pop("abstract", None)
    return out


# ─── Confidence pass ────────────────────────────────────────────────────────


@mcp.tool()
async def get_low_confidence_reviews(
    status: Status | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Auto-classified papers that Claude flagged as low-confidence.

    Use this on a second pass: after the main review loop, walk these with the user
    to confirm or flip them. They're the auto-review's blind spots.
    Returns title/year/authors/current-status + reason, without abstracts — fetch
    those via `get_paper_details` for borderline ones.
    """
    query = """
        SELECT p.id, p.source, p.title, p.year, p.venue, p.authors_json, p.doi,
               r.status, r.reason, r.reviewed_at
        FROM papers p
        JOIN reviews r ON r.paper_id = p.id
        WHERE r.reviewed_by = 'auto_low'
    """
    params: list[Any] = []
    if status is not None:
        query += " AND r.status = ?"
        params.append(status)
    query += " ORDER BY r.reviewed_at DESC LIMIT ?"
    params.append(limit)

    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
    return [paper_row_to_dict(r) for r in rows]


# ─── Status ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def set_review_status(
    paper_ids: list[int],
    status: Status,
    reason: str,
    note: str | None = None,
    reviewed_by: ReviewedBy = "auto_high",
) -> dict[str, int]:
    """Batch-set review status with required reason (PRISMA trail). Marks summary stale.

    Use `reviewed_by`:
    - `"auto_high"` — clear match or clear off-topic, you're confident.
    - `"auto_low"` — weaker signal (extrapolation, partial keyword match). The
      user should sanity-check these. Fetch with `get_low_confidence_reviews()`
      during a second pass, or surface them proactively.
    - `"user"` — the user decided.
    """
    updated = 0
    skipped: list[int] = []
    async with get_connection() as conn:
        for idx, pid in enumerate(paper_ids):
            # Per-paper SAVEPOINT so a mid-batch failure rolls back that paper
            # alone — `reviews` and `review_history` always move together.
            # Use the loop index, not the paper id, so savepoint names are always
            # valid SQL identifiers regardless of what ids the caller passes.
            savepoint = f"rsp_{idx}"
            await conn.execute(f"SAVEPOINT {savepoint}")
            try:
                cur = await conn.execute("SELECT status FROM reviews WHERE paper_id = ?", (pid,))
                row = await cur.fetchone()
                old_status = row["status"] if row else None

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
                await conn.execute(
                    """
                    INSERT INTO review_history
                        (paper_id, old_status, new_status, reason, reviewed_by)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (pid, old_status, status, reason, reviewed_by),
                )
            except aiosqlite.IntegrityError:
                await conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                skipped.append(pid)
                continue
            await conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            updated += 1
        if updated > 0:
            await _mark_summary_stale(conn)
        await conn.commit()
    result: dict[str, Any] = {"updated": updated}
    if skipped:
        result["skipped_invalid_ids"] = skipped
    return result


# ─── Undo / bulk ops ────────────────────────────────────────────────────────


@mcp.tool()
async def bulk_reclassify(
    new_status: Status,
    reason: str,
    current_status: Status | None = None,
    source: Source | None = None,
    cluster: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    reviewed_by: ReviewedBy = "auto_high",
    limit: int | None = None,
) -> dict[str, Any]:
    """Reclassify every paper matching the filter. Writes audit entries per paper.

    Filter is AND-joined — provide any subset of:
    - `current_status`: reclassify only papers currently at this status
    - `source`: only papers from this source
    - `cluster`: papers listed in this cluster of the current review_summary
    - `year_from`, `year_to`: publication-year window
    - `limit`: cap the number of papers touched (safety rail)

    Use case: you narrowed the scope and want to move an entire
    "attacks-classic" cluster from `approved` to `maybe` in one shot.
    """
    # Resolve cluster → paper_ids via review_summary (shared helper).
    cluster_ids: list[int] | None = None
    if cluster is not None:
        resolved = await resolve_cluster_paper_ids(cluster)
        if isinstance(resolved, dict):
            return {"updated": 0, **resolved}
        cluster_ids = resolved
        if not cluster_ids:
            return {"updated": 0, "note": f"cluster {cluster!r} is empty"}

    # Build the selector query.
    query = "SELECT p.id FROM papers p JOIN reviews r ON r.paper_id = p.id WHERE 1=1"
    params: list[Any] = []
    if current_status is not None:
        query += " AND r.status = ?"
        params.append(current_status)
    if source is not None:
        query += " AND p.source = ?"
        params.append(source)
    if year_from is not None:
        query += " AND p.year >= ?"
        params.append(year_from)
    if year_to is not None:
        query += " AND p.year <= ?"
        params.append(year_to)
    if cluster_ids is not None:
        placeholders = ",".join("?" * len(cluster_ids))
        query += f" AND p.id IN ({placeholders})"
        params.extend(cluster_ids)
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        target_ids = [r["id"] for r in await cur.fetchall()]

    if not target_ids:
        return {"updated": 0, "note": "filter matched no papers"}

    # Reuse set_review_status to get the history audit trail for free.
    return await set_review_status(
        paper_ids=target_ids,
        status=new_status,
        reason=reason,
        reviewed_by=reviewed_by,
    )


@mcp.tool()
async def undo_last_review_action() -> dict[str, Any]:
    """Revert the most recent `set_review_status` entry in review_history.

    Restores the paper to its `old_status` (typically "unreviewed" if the
    action was the first classification). The history row itself is removed so
    a subsequent undo walks further back.

    Useful when Claude mis-classifies a borderline paper as auto_high and the
    user catches it. Does not undo bulk operations — call multiple times.
    """
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, paper_id, old_status, new_status, reason, reviewed_by
            FROM review_history ORDER BY id DESC LIMIT 1
            """
        )
        row = await cur.fetchone()
        if row is None:
            return {"undone": False, "reason": "review_history is empty"}

        # Remove the history entry *before* reverting the review row, so that
        # the revert doesn't trigger an extra history insert via set_review_status.
        await conn.execute("DELETE FROM review_history WHERE id = ?", (row["id"],))

        if row["old_status"] is None:
            # First-ever classification of this paper — revert to the initial row
            # that `save_papers` creates, which defaults to 'unreviewed'.
            await conn.execute(
                """
                UPDATE reviews
                SET status = 'unreviewed', reason = NULL, note = NULL,
                    reviewed_by = NULL, reviewed_at = CURRENT_TIMESTAMP
                WHERE paper_id = ?
                """,
                (row["paper_id"],),
            )
            reverted_to = "unreviewed"
        else:
            await conn.execute(
                """
                UPDATE reviews
                SET status = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE paper_id = ?
                """,
                (row["old_status"], row["paper_id"]),
            )
            reverted_to = row["old_status"]

        await _mark_summary_stale(conn)
        await conn.commit()

    return {
        "undone": True,
        "paper_id": row["paper_id"],
        "reverted_to": reverted_to,
        "was": row["new_status"],
    }


# ─── Progress ───────────────────────────────────────────────────────────────


@mcp.tool()
async def get_review_progress() -> dict[str, Any]:
    """Progress snapshot against the project's targets.

    Always returns review counts (total / approved / maybe / rejected /
    unreviewed). When the project has target metrics set in `init_project`
    (sources min/max, words, citation density) this tool also returns how
    far the current state is from those targets plus a `warnings` list for
    anything below its floor.

    Writing metrics (words, citations, density) come from `section_content`
    rows; they're zero when no sections are written yet.
    """
    async with get_connection() as conn:
        counts = await _get_live_counts(conn)

        cur = await conn.execute(
            """
            SELECT target_sources_min, target_sources_max, target_words,
                   citation_density_target
            FROM project_metadata WHERE id = 1
            """
        )
        meta = await cur.fetchone()
        targets = {k: meta[k] for k in meta.keys() if meta[k] is not None} if meta else {}

        cur = await conn.execute("SELECT content FROM section_content")
        section_rows = await cur.fetchall()

    total_words = 0
    total_cites = 0
    for row in section_rows:
        content = row["content"] or ""
        total_words += len(content.split())
        total_cites += _count_cites(content)

    density = round(total_cites * 100 / total_words, 2) if total_words else 0.0

    approved = counts.get("approved", 0)
    warnings: list[str] = []

    if targets.get("target_sources_min") and approved < targets["target_sources_min"]:
        warnings.append(
            f"approved sources ({approved}) below target floor "
            f"({targets['target_sources_min']}) — need {targets['target_sources_min'] - approved} more"
        )
    if (
        targets.get("citation_density_target")
        and total_words > 0
        and density < targets["citation_density_target"]
    ):
        warnings.append(
            f"citation density ({density} per 100 words) below target "
            f"({targets['citation_density_target']}) — undercited"
        )

    return {
        "counts": counts,
        "writing": {
            "words": total_words,
            "citations": total_cites,
            "citation_density_per_100_words": density,
            "sections_with_content": len(section_rows),
        },
        "targets": targets,
        "warnings": warnings,
    }


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
        warnings.append(
            "Summary is marked stale (papers added or statuses changed since last update)"
        )
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
        resolved = await resolve_cluster_paper_ids(cluster)
        if isinstance(resolved, dict):
            return [resolved]
        paper_ids = resolved

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
    return [paper_row_to_dict(r) for r in rows]
