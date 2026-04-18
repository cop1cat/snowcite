"""Semantic Scholar Graph API client."""

from typing import Any

from pydantic import ValidationError

from snowcite.dedup import normalize_doi
from snowcite.logging import log
from snowcite.settings import settings
from snowcite.sources._http import http_get
from snowcite.sources.base import Paper


BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = (
    "title,abstract,year,authors.name,venue,externalIds,"
    "openAccessPdf,citationStyles,publicationTypes"
)
RELATED_FIELDS = "title,abstract,year,authors,venue,externalIds,openAccessPdf"
HTTP_NOT_FOUND = 404


def _headers() -> dict[str, str]:
    if settings.semantic_scholar_api_key:
        return {"x-api-key": settings.semantic_scholar_api_key}
    return {}


def _to_paper(item: dict[str, Any]) -> Paper | None:
    """Build Paper from raw API item; return None on corrupt/invalid records."""
    external = item.get("externalIds") or {}
    citation_styles = item.get("citationStyles") or {}
    pdf = item.get("openAccessPdf") or {}
    try:
        return Paper(
            source="semantic_scholar",
            source_id=item["paperId"],
            doi=normalize_doi(external.get("DOI")),
            title=(item.get("title") or "").strip(),
            authors=[a["name"] for a in (item.get("authors") or []) if a.get("name")],
            year=item.get("year"),
            venue=item.get("venue") or None,
            abstract=item.get("abstract"),
            pdf_url=pdf.get("url"),
            bibtex=citation_styles.get("bibtex"),
            metadata={
                "external_ids": external,
                "publication_types": item.get("publicationTypes"),
            },
        )
    except (ValidationError, KeyError, TypeError) as e:
        log.warning(
            "semantic_scholar: skipping corrupt record (paperId=%r): %s",
            item.get("paperId"),
            e,
        )
        return None


async def search(
    query: str,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[Paper]:
    params: dict[str, str | int] = {
        "query": query,
        "limit": min(limit, 100),
        "fields": FIELDS,
    }
    if year_from or year_to:
        params["year"] = f"{year_from or ''}-{year_to or ''}"
    resp = await http_get(
        "semantic_scholar",
        f"{BASE_URL}/paper/search",
        params=params,
        headers=_headers(),
    )
    resp.raise_for_status()
    items = (resp.json().get("data")) or []
    out: list[Paper] = []
    for i in items:
        if not (i.get("paperId") and i.get("title")):
            continue
        p = _to_paper(i)
        if p is not None:
            out.append(p)
    return out


async def get_related(
    paper_id: str,
    direction: str,
    limit: int = 20,
) -> list[Paper]:
    """Fetch references or citations for a Semantic Scholar paper ID."""
    params: dict[str, str | int] = {
        "fields": RELATED_FIELDS,
        "limit": min(limit, 1000),
    }
    resp = await http_get(
        "semantic_scholar",
        f"{BASE_URL}/paper/{paper_id}/{direction}",
        params=params,
        headers=_headers(),
    )
    resp.raise_for_status()
    items = (resp.json().get("data")) or []
    out: list[Paper] = []
    for item in items:
        paper_data = item.get("citedPaper" if direction == "references" else "citingPaper")
        if not (paper_data and paper_data.get("paperId") and paper_data.get("title")):
            continue
        p = _to_paper(paper_data)
        if p is not None:
            out.append(p)
    return out[:limit]


async def resolve_by_doi(doi: str) -> str | None:
    """Resolve a DOI to a Semantic Scholar paper ID."""
    resp = await http_get(
        "semantic_scholar",
        f"{BASE_URL}/paper/DOI:{doi}",
        params={"fields": "paperId"},
        headers=_headers(),
        timeout=15.0,
    )
    if resp.status_code == HTTP_NOT_FOUND:
        return None
    resp.raise_for_status()
    return resp.json().get("paperId")
