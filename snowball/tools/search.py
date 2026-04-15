"""Search and persistence tools."""

import asyncio
import json
import sys
from typing import Any

import aiosqlite

from snowball.app import mcp
from snowball.dedup import find_title_match, normalize_title
from snowball.db import get_connection
from snowball.sources import arxiv_client, openalex, semantic_scholar
from snowball.sources.base import Paper
from snowball.types import Direction, Source, Status

_SOURCE_FNS = {
    "arxiv": arxiv_client.search,
    "semantic_scholar": semantic_scholar.search,
    "openalex": openalex.search,
}

_DEFAULT_SOURCES: list[Source] = ["arxiv", "semantic_scholar", "openalex"]


def _richness(p: Paper) -> int:
    """Score paper by populated key fields — used to pick best of duplicates."""
    return sum(bool(x) for x in (p.doi, p.abstract, p.bibtex, p.venue, p.pdf_url))


def _dedup_within_batch(papers: list[Paper]) -> list[Paper]:
    """Inter-source dedup: prefer richer record on DOI or title collision."""
    by_doi: dict[str, Paper] = {}
    no_doi: list[Paper] = []
    for p in papers:
        if p.doi:
            existing = by_doi.get(p.doi)
            if existing is None or _richness(p) > _richness(existing):
                by_doi[p.doi] = p
        else:
            no_doi.append(p)

    merged = list(by_doi.values())
    merged_norms = [normalize_title(p.title) for p in merged]
    for p in no_doi:
        norm = normalize_title(p.title)
        idx = find_title_match(norm, merged_norms)
        if idx is None:
            merged.append(p)
            merged_norms.append(norm)
        elif _richness(p) > _richness(merged[idx]):
            merged[idx] = p
            merged_norms[idx] = norm
    return merged


@mcp.tool()
async def search_papers(
    query: str,
    sources: list[Source] | None = None,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict[str, Any]]:
    """Search arXiv / Semantic Scholar / OpenAlex in parallel, dedup by DOI/title.

    Returns papers as dicts. Does NOT save — call save_papers explicitly.
    A single source failure is logged and does not abort the search.
    """
    chosen = sources or _DEFAULT_SOURCES
    coros = [_SOURCE_FNS[s](query, limit, year_from, year_to) for s in chosen]
    results = await asyncio.gather(*coros, return_exceptions=True)

    all_papers: list[Paper] = []
    for source_name, res in zip(chosen, results):
        if isinstance(res, Exception):
            print(f"warning: {source_name} failed: {res!r}", file=sys.stderr)
            continue
        all_papers.extend(res)

    deduped = _dedup_within_batch(all_papers)
    return [p.model_dump() for p in deduped]


@mcp.tool()
async def save_papers(papers: list[dict[str, Any]]) -> dict[str, int]:
    """INSERT papers with DOI uniqueness + fuzzy-title fallback dedup.

    Returns {saved, duplicates}.
    """
    validated = [Paper.model_validate(p) for p in papers]
    if not validated:
        return {"saved": 0, "duplicates": 0}

    saved = 0
    duplicates = 0
    async with get_connection() as conn:
        # Fuzzy-title check runs against ALL existing titles, not just no-DOI ones:
        # a no-DOI paper arriving for a paper already in DB with DOI is still a duplicate.
        cur = await conn.execute("SELECT title_normalized FROM papers")
        existing_norms = [r[0] for r in await cur.fetchall()]

        for p in validated:
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
                        p.source, p.source_id, p.doi, p.title, norm,
                        json.dumps(p.authors), p.year, p.venue, p.abstract,
                        p.pdf_url, p.bibtex, json.dumps(p.metadata),
                    ),
                )
                await conn.execute(
                    "INSERT INTO reviews (paper_id, status) VALUES (?, 'unreviewed')",
                    (cur.lastrowid,),
                )
                saved += 1
                existing_norms.append(norm)
            except aiosqlite.IntegrityError:
                duplicates += 1
        await conn.commit()
    return {"saved": saved, "duplicates": duplicates}


# ─── Stubs for later phases ─────────────────────────────────────────────────

@mcp.tool()
async def get_saved_papers(
    status: Status | None = None,
    source: Source | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch saved papers with optional filters."""
    raise NotImplementedError("Phase 3")


@mcp.tool()
async def get_paper_details(paper_id: int) -> dict[str, Any]:
    """Full paper record by id."""
    raise NotImplementedError("Phase 3")


@mcp.tool()
async def expand_citations(
    paper_id: int,
    direction: Direction,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch references or citations for one paper. arXiv falls back to Semantic Scholar by DOI."""
    raise NotImplementedError("Phase 4")
