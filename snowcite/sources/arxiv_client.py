"""arXiv client. The `arxiv` lib is sync; we run it in a worker thread."""

import asyncio

import arxiv

from snowcite.dedup import normalize_doi
from snowcite.sources.base import Paper


def _to_paper(result: arxiv.Result) -> Paper:
    arxiv_id = result.entry_id.rsplit("/", 1)[-1]
    return Paper(
        source="arxiv",
        source_id=arxiv_id,
        doi=normalize_doi(result.doi),
        title=result.title.strip(),
        authors=[a.name for a in result.authors],
        year=result.published.year if result.published else None,
        venue=result.journal_ref,
        abstract=result.summary.strip() if result.summary else None,
        pdf_url=result.pdf_url,
        bibtex=None,
        metadata={
            "primary_category": result.primary_category,
            "categories": result.categories,
            "comment": result.comment,
        },
    )


def _search_sync(
    query: str,
    limit: int,
    year_from: int | None,
    year_to: int | None,
) -> list[Paper]:
    # New client per call: arxiv.Client holds mutable paging state, unsafe to share.
    client = arxiv.Client(page_size=50, delay_seconds=3.0, num_retries=3)
    search = arxiv.Search(
        query=query,
        max_results=limit * 3 if (year_from or year_to) else limit,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    out: list[Paper] = []
    for result in client.results(search):
        if result.published:
            y = result.published.year
            if year_from and y < year_from:
                continue
            if year_to and y > year_to:
                continue
        out.append(_to_paper(result))
        if len(out) >= limit:
            break
    return out


async def search(
    query: str,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[Paper]:
    return await asyncio.to_thread(_search_sync, query, limit, year_from, year_to)
