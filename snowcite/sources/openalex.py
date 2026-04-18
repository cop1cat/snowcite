"""OpenAlex client. Abstracts come as inverted index — we reconstruct plaintext."""

from typing import Any

from pydantic import ValidationError

from snowcite.dedup import normalize_doi
from snowcite.logging import log
from snowcite.settings import settings
from snowcite.sources._http import http_get
from snowcite.sources.base import Paper


BASE_URL = "https://api.openalex.org"


def _abstract_from_inverted(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


def _strip_openalex_id(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _to_paper(item: dict[str, Any]) -> Paper | None:
    """Build Paper from raw API item; return None on corrupt/invalid records."""
    primary = item.get("primary_location") or {}
    source = primary.get("source") or {}
    pdf_url = primary.get("pdf_url") or (item.get("open_access") or {}).get("oa_url")
    try:
        return Paper(
            source="openalex",
            source_id=_strip_openalex_id(item["id"]),
            doi=normalize_doi(item.get("doi")),
            title=(item.get("title") or item.get("display_name") or "").strip(),
            authors=[
                a["author"]["display_name"]
                for a in (item.get("authorships") or [])
                if a.get("author", {}).get("display_name")
            ],
            year=item.get("publication_year"),
            venue=source.get("display_name"),
            abstract=_abstract_from_inverted(item.get("abstract_inverted_index")),
            pdf_url=pdf_url,
            bibtex=None,
            metadata={
                "type": item.get("type"),
                "cited_by_count": item.get("cited_by_count"),
                "referenced_works": item.get("referenced_works"),
            },
        )
    except (ValidationError, KeyError, TypeError) as e:
        log.warning("openalex: skipping corrupt record (id=%r): %s", item.get("id"), e)
        return None


async def search(
    query: str,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[Paper]:
    params: dict[str, str | int] = {
        "search": query,
        "per-page": min(limit, 200),
    }
    filters: list[str] = []
    if year_from:
        filters.append(f"publication_year:>{year_from - 1}")
    if year_to:
        filters.append(f"publication_year:<{year_to + 1}")
    if filters:
        params["filter"] = ",".join(filters)
    if settings.openalex_email:
        params["mailto"] = settings.openalex_email

    resp = await http_get("openalex", f"{BASE_URL}/works", params=params)
    resp.raise_for_status()
    items = (resp.json().get("results")) or []
    out: list[Paper] = []
    for i in items:
        if not (i.get("id") and (i.get("title") or i.get("display_name"))):
            continue
        p = _to_paper(i)
        if p is not None:
            out.append(p)
    return out
