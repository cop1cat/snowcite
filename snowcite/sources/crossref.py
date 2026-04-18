"""Crossref Works API client — universal scholarly metadata, keyed by DOI.

Docs: https://api.crossref.org. Polite pool via `mailto=` query param, same
convention as OpenAlex. Honors Retry-After on 429 via sources/_http.
"""

from typing import Any

from pydantic import ValidationError

from snowcite.dedup import normalize_doi
from snowcite.logging import log
from snowcite.settings import settings
from snowcite.sources._http import http_get
from snowcite.sources.base import Paper


BASE_URL = "https://api.crossref.org"


def _to_paper(item: dict[str, Any]) -> Paper | None:
    """Build Paper from a Crossref /works item; return None on corrupt records.

    Crossref title/subtitle/container-title are all arrays — take the first.
    Year lives under issued.date-parts[0][0].
    """
    try:
        titles = item.get("title") or []
        if not titles:
            return None
        year = None
        issued = item.get("issued") or {}
        parts = issued.get("date-parts") or []
        if parts and parts[0]:
            year = parts[0][0]

        authors = []
        for a in item.get("author") or []:
            given = a.get("given", "")
            family = a.get("family", "")
            full = (f"{given} {family}".strip()) or a.get("name") or None
            if full:
                authors.append(full)

        container = item.get("container-title") or []
        venue = container[0] if container else None

        return Paper(
            source="crossref",
            source_id=item["DOI"],  # DOI as the Crossref primary key
            doi=normalize_doi(item.get("DOI")),
            title=titles[0].strip(),
            authors=authors,
            year=year,
            venue=venue,
            abstract=item.get("abstract"),  # sometimes contains JATS XML — best-effort
            pdf_url=None,
            bibtex=None,
            metadata={
                "type": item.get("type"),
                "publisher": item.get("publisher"),
                "subject": item.get("subject"),
            },
        )
    except (ValidationError, KeyError, TypeError) as e:
        log.warning("crossref: skipping corrupt record (DOI=%r): %s", item.get("DOI"), e)
        return None


async def search(
    query: str,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[Paper]:
    params: dict[str, str | int] = {"query": query, "rows": min(limit, 100)}
    filters: list[str] = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}")
    if year_to:
        filters.append(f"until-pub-date:{year_to}")
    if filters:
        params["filter"] = ",".join(filters)
    if settings.openalex_email:
        # Crossref respects the same polite-pool convention as OpenAlex.
        params["mailto"] = settings.openalex_email

    resp = await http_get("crossref", f"{BASE_URL}/works", params=params)
    resp.raise_for_status()
    items = (resp.json().get("message") or {}).get("items") or []
    out: list[Paper] = []
    for i in items:
        if not i.get("DOI"):
            continue
        p = _to_paper(i)
        if p is not None:
            out.append(p)
    return out
