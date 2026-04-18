"""Search and persistence tools."""

import asyncio
from typing import Any

import aiosqlite

from snowcite.app import mcp
from snowcite.db import get_connection
from snowcite.dedup import find_title_match, normalize_title
from snowcite.logging import log
from snowcite.persistence import PersistResult, persist_papers
from snowcite.projects import NoProjectError
from snowcite.sources import arxiv_client, crossref, openalex, pubmed, semantic_scholar
from snowcite.sources.base import Paper
from snowcite.tools.common import paper_row_to_dict
from snowcite.types import Direction, Source, Status


def _truncate_abstract(abstract: str | None, max_chars: int) -> str | None:
    """Return abstract clipped to max_chars. max_chars=0 drops the field entirely."""
    if abstract is None or max_chars == 0:
        return None
    if len(abstract) <= max_chars:
        return abstract
    return abstract[: max_chars - 1].rstrip() + "…"


def _compact_paper(p: Paper, abstract_max_chars: int) -> dict[str, Any]:
    """Compact Paper → dict, respecting abstract truncation policy."""
    data = p.model_dump()
    data["abstract"] = _truncate_abstract(p.abstract, abstract_max_chars)
    return data


_SOURCE_FNS = {
    "arxiv": arxiv_client.search,
    "semantic_scholar": semantic_scholar.search,
    "openalex": openalex.search,
    "crossref": crossref.search,
    "pubmed": pubmed.search,
}

# STEM disciplines get arXiv; everyone else gets universal sources only.
_STEM_DISCIPLINES = frozenset(
    {"cs", "computer_science", "physics", "math", "stats", "econ", "q-bio", "q-fin"}
)
_MEDICAL_DISCIPLINES = frozenset({"medicine", "biology", "psychiatry", "nursing", "pharmacy"})

# Universal sources run for every discipline.
_UNIVERSAL_SOURCES: list[Source] = ["semantic_scholar", "openalex", "crossref"]


def _sources_for_discipline(discipline: str | None) -> list[Source]:
    """Pick a reasonable default set of sources based on the user's discipline."""
    base: list[Source] = list(_UNIVERSAL_SOURCES)
    if discipline is None:
        # Unknown — keep the pre-T7 default so existing behaviour holds.
        return ["arxiv", *base]
    d = discipline.lower()
    if d in _STEM_DISCIPLINES:
        base.insert(0, "arxiv")
    if d in _MEDICAL_DISCIPLINES:
        base.append("pubmed")
    return base


async def _discipline_from_metadata() -> str | None:
    """Cheap read of project_metadata.discipline. None when no project is active.

    Catches only "no active project" / "schema not initialised" / IO errors —
    programmer errors (AttributeError etc.) surface normally.
    """
    try:
        async with get_connection() as conn:
            cur = await conn.execute("SELECT discipline FROM project_metadata WHERE id = 1")
            row = await cur.fetchone()
    except (NoProjectError, aiosqlite.Error, OSError):
        return None
    return row["discipline"] if row else None


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
    auto_save: bool = True,
    abstract_max_chars: int = 0,
) -> dict[str, Any]:
    """Search arXiv / Semantic Scholar / OpenAlex in parallel, dedup by DOI/title.

    By default (auto_save=True) persists new papers to the DB and returns a compact
    summary {saved, duplicates, new_ids, titles} — abstracts never enter the chat
    context, which keeps review sessions lean and avoids false-positive safety triggers
    when harmful-sounding abstracts accumulate.

    Set auto_save=False for preview mode; then the response includes the full paper list
    (with abstracts trimmed to abstract_max_chars; 0 drops the field entirely).

    A single source failure is logged and does not abort the search.
    """
    chosen = sources or _sources_for_discipline(await _discipline_from_metadata())
    coros = [_SOURCE_FNS[s](query, limit, year_from, year_to) for s in chosen]
    results = await asyncio.gather(*coros, return_exceptions=True)

    all_papers: list[Paper] = []
    failed_sources: list[str] = []
    for source_name, res in zip(chosen, results, strict=True):
        if isinstance(res, Exception):
            log.warning("%s search failed: %r", source_name, res)
            failed_sources.append(source_name)
            continue
        all_papers.extend(res)

    deduped = _dedup_within_batch(all_papers)

    if auto_save:
        persisted: PersistResult = await persist_papers(deduped)
        result: dict[str, Any] = {
            "saved": persisted["saved"],
            "duplicates": persisted["duplicates"],
            "new_ids": persisted["new_ids"],
            "titles": persisted["new_titles"],
        }
    else:
        papers_out = [_compact_paper(p, abstract_max_chars) for p in deduped]
        result = {"papers": papers_out, "count": len(papers_out)}
    if failed_sources:
        result["failed_sources"] = failed_sources
    return result


@mcp.tool()
async def save_papers(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """Insert papers with DOI uniqueness + fuzzy-title fallback dedup.

    Returns {saved, duplicates, new_ids, new_titles}. Prefer
    `search_papers(auto_save=True)`; this tool exists for manual re-insertion
    or imported data.
    """
    validated = [Paper.model_validate(p) for p in papers]
    return dict(await persist_papers(validated))


# ─── Read tools ─────────────────────────────────────────────────────────────


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
    """Fetch saved papers with optional filters. Joins review status."""
    query = """
        SELECT p.*, r.status AS review_status, r.reason AS review_reason,
               r.note AS review_note, r.reviewed_by, r.reviewed_at
        FROM papers p
        LEFT JOIN reviews r ON r.paper_id = p.id
        WHERE 1=1
    """
    params: list[Any] = []
    if status is not None:
        query += " AND r.status = ?"
        params.append(status)
    if source is not None:
        query += " AND p.source = ?"
        params.append(source)
    if year_from is not None:
        query += " AND p.year >= ?"
        params.append(year_from)
    if year_to is not None:
        query += " AND p.year <= ?"
        params.append(year_to)
    if search:
        query += " AND (p.title LIKE ? OR p.abstract LIKE ?)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    query += " ORDER BY p.id LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
    return [paper_row_to_dict(r) for r in rows]


@mcp.tool()
async def get_paper_details(paper_id: int) -> dict[str, Any]:
    """Full paper record by id, including review status and citation counts."""
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT p.*, r.status AS review_status, r.reason AS review_reason,
                   r.note AS review_note, r.reviewed_by, r.reviewed_at
            FROM papers p
            LEFT JOIN reviews r ON r.paper_id = p.id
            WHERE p.id = ?
            """,
            (paper_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return {"error": f"paper {paper_id} not found"}
        paper = paper_row_to_dict(row)

        cur = await conn.execute(
            "SELECT COUNT(*) FROM citations WHERE source_paper_id = ? AND direction = 'references'",
            (paper_id,),
        )
        paper["references_count"] = (await cur.fetchone())[0]

        cur = await conn.execute(
            "SELECT COUNT(*) FROM citations WHERE source_paper_id = ? AND direction = 'citations'",
            (paper_id,),
        )
        paper["citations_count"] = (await cur.fetchone())[0]
    return paper


@mcp.tool()
async def expand_citations(
    paper_id: int,
    direction: Direction,
    limit: int = 20,
    auto_save: bool = True,
    abstract_max_chars: int = 0,
) -> dict[str, Any]:
    """Fetch references or citations for one paper; by default persist new ones.

    Uses Semantic Scholar API. For arXiv / OpenAlex papers without a Semantic Scholar
    id, falls back to DOI lookup.

    With auto_save=True (default), new papers land in `unreviewed` and the response is
    {saved, duplicates, new_ids, titles}. With auto_save=False, returns full paper list
    with abstracts trimmed to abstract_max_chars (0 = omitted).
    """
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT source, source_id, doi FROM papers WHERE id = ?",
            (paper_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return {"error": f"paper {paper_id} not found"}

    source, source_id, doi = row["source"], row["source_id"], row["doi"]

    ss_id: str | None = None
    if source == "semantic_scholar":
        ss_id = source_id
    elif doi:
        ss_id = await semantic_scholar.resolve_by_doi(doi)

    if ss_id is None:
        return {
            "error": (
                f"Cannot resolve paper {paper_id} (source={source}) to a Semantic "
                f"Scholar id. No DOI available."
            )
        }

    related = await semantic_scholar.get_related(ss_id, direction, limit)

    if auto_save:
        persisted = await persist_papers(related)
        return {
            "saved": persisted["saved"],
            "duplicates": persisted["duplicates"],
            "new_ids": persisted["new_ids"],
            "titles": persisted["new_titles"],
        }
    return {
        "papers": [_compact_paper(p, abstract_max_chars) for p in related],
        "count": len(related),
    }
