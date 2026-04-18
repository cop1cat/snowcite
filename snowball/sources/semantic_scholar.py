"""Semantic Scholar Graph API client."""

import httpx

from snowball.dedup import normalize_doi
from snowball.settings import settings
from snowball.sources.base import Paper

BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = (
    "title,abstract,year,authors.name,venue,externalIds,"
    "openAccessPdf,citationStyles,publicationTypes"
)
RELATED_FIELDS = "title,abstract,year,authors,venue,externalIds,openAccessPdf"


def _headers() -> dict[str, str]:
    if settings.semantic_scholar_api_key:
        return {"x-api-key": settings.semantic_scholar_api_key}
    return {}


def _to_paper(item: dict) -> Paper:
    external = item.get("externalIds") or {}
    citation_styles = item.get("citationStyles") or {}
    pdf = item.get("openAccessPdf") or {}
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BASE_URL}/paper/search",
            params=params,
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data") or []
    return [_to_paper(i) for i in items if i.get("paperId") and i.get("title")]


async def get_related(
    paper_id: str,
    direction: str,
    limit: int = 20,
) -> list[Paper]:
    """Fetch references or citations for a Semantic Scholar paper ID."""
    endpoint = f"{BASE_URL}/paper/{paper_id}/{direction}"
    params: dict[str, str | int] = {
        "fields": RELATED_FIELDS,
        "limit": min(limit, 1000),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(endpoint, params=params, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data") or []
    out: list[Paper] = []
    for item in items:
        paper_data = item.get("citedPaper" if direction == "references" else "citingPaper")
        if paper_data and paper_data.get("paperId") and paper_data.get("title"):
            out.append(_to_paper(paper_data))
    return out[:limit]


async def resolve_by_doi(doi: str) -> str | None:
    """Resolve a DOI to a Semantic Scholar paper ID."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{BASE_URL}/paper/DOI:{doi}",
            params={"fields": "paperId"},
            headers=_headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("paperId")
