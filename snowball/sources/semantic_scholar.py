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
