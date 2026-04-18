"""Persistence layer — the single DB write path for papers.

Centralised here so `search_papers`, `expand_citations`, and `import_bibtex`
share one insert + dedup implementation. Tool modules call this, never each
other's internals.
"""

import json
from typing import Any, TypedDict

import aiosqlite

from snowcite.db import get_connection
from snowcite.dedup import find_title_match, normalize_title
from snowcite.sources.base import Paper


class PersistResult(TypedDict):
    saved: int
    duplicates: int
    new_ids: list[int]
    new_titles: list[str]


async def persist_papers(papers: list[Paper]) -> PersistResult:
    """Insert papers with DOI uniqueness + fuzzy-title dedup.

    Returns `{saved, duplicates, new_ids, new_titles}`. `new_ids` and
    `new_titles` are aligned — the i-th title belongs to the i-th id.
    """
    if not papers:
        return {"saved": 0, "duplicates": 0, "new_ids": [], "new_titles": []}

    duplicates = 0
    new_ids: list[int] = []
    new_titles: list[str] = []
    async with get_connection() as conn:
        # Fuzzy-title check runs against ALL existing titles, not just no-DOI
        # ones: a no-DOI paper arriving for a paper already in DB with a DOI
        # is still a duplicate.
        cur = await conn.execute("SELECT title_normalized FROM papers")
        existing_norms = [r[0] for r in await cur.fetchall()]

        for p in papers:
            norm = normalize_title(p.title)
            if not p.doi and find_title_match(norm, existing_norms) is not None:
                duplicates += 1
                continue
            try:
                cur = await conn.execute(
                    """
                    INSERT INTO papers
                        (source, source_id, doi, title, title_normalized,
                         authors_json, year, venue, abstract, pdf_url,
                         bibtex, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p.source,
                        p.source_id,
                        p.doi,
                        p.title,
                        norm,
                        json.dumps(p.authors),
                        p.year,
                        p.venue,
                        p.abstract,
                        p.pdf_url,
                        p.bibtex,
                        json.dumps(p.metadata),
                    ),
                )
                new_ids.append(cur.lastrowid)
                new_titles.append(p.title)
                await conn.execute(
                    "INSERT INTO reviews (paper_id, status) VALUES (?, 'unreviewed')",
                    (cur.lastrowid,),
                )
                existing_norms.append(norm)
            except aiosqlite.IntegrityError:
                duplicates += 1
        if new_ids:
            await conn.execute("UPDATE review_summary SET stale = 1 WHERE id = 1")
        await conn.commit()
    return {
        "saved": len(new_ids),
        "duplicates": duplicates,
        "new_ids": new_ids,
        "new_titles": new_titles,
    }


# ─── Shared readers ─────────────────────────────────────────────────────────


class ApprovedPaper(TypedDict):
    """Shape returned by `load_approved_papers`. Includes everything callers
    across compile/export/rendering need; filter at the use site."""

    id: int
    source: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    abstract: str | None
    bibtex: str | None


async def load_approved_papers() -> list[ApprovedPaper]:
    """Fetch every approved paper with everything needed for bibliography +
    table rendering, ordered deterministically."""
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT p.id, p.source, p.title, p.authors_json, p.year, p.venue,
                   p.doi, p.abstract, p.bibtex
            FROM papers p JOIN reviews r ON r.paper_id = p.id
            WHERE r.status = 'approved'
            ORDER BY p.year, p.id
            """
        )
        rows = await cur.fetchall()
    out: list[ApprovedPaper] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "source": r["source"],
                "title": r["title"],
                "authors": json.loads(r["authors_json"] or "[]"),
                "year": r["year"],
                "venue": r["venue"],
                "doi": r["doi"],
                "abstract": r["abstract"],
                "bibtex": r["bibtex"],
            }
        )
    return out


async def load_papers_by_ids(paper_ids: list[int]) -> list[dict[str, Any]]:
    """Fetch a subset of papers by id, with abstracts. Used when building
    context bundles for review subagents and regeneration prompts."""
    if not paper_ids:
        return []
    placeholders = ",".join("?" * len(paper_ids))
    async with get_connection() as conn:
        cur = await conn.execute(
            f"""
            SELECT id, title, authors_json, year, venue, doi, abstract
            FROM papers WHERE id IN ({placeholders})
            ORDER BY year, id
            """,  # noqa: S608 — placeholder count bound from paper_ids
            paper_ids,
        )
        rows = await cur.fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "authors": json.loads(r["authors_json"] or "[]"),
            "year": r["year"],
            "venue": r["venue"],
            "doi": r["doi"],
            "abstract": r["abstract"],
        }
        for r in rows
    ]


async def resolve_cluster_paper_ids(cluster: str) -> list[int] | dict[str, Any]:
    """Look up paper_ids for a cluster in the current review_summary.

    Returns a list of ints on success, or an error dict with `available` list
    when the cluster name isn't found. Used by `bulk_reclassify` and
    `get_papers_for_writing` to de-duplicate their cluster-resolve logic.
    """
    async with get_connection() as conn:
        cur = await conn.execute("SELECT clusters_json FROM review_summary WHERE id = 1")
        row = await cur.fetchone()
    if not row:
        return {"error": "no review_summary — run save_review_summary first"}
    clusters_data = json.loads(row["clusters_json"])
    match = next((c for c in clusters_data if c.get("topic", "").lower() == cluster.lower()), None)
    if match is None:
        return {
            "error": f"cluster {cluster!r} not found",
            "available": [c.get("topic") for c in clusters_data],
        }
    return match.get("paper_ids") or []
