"""PubMed client via NCBI E-utilities.

E-utilities flow: `esearch` returns PMIDs matching a query, `esummary` fetches
metadata for those PMIDs. Two round-trips per search; both sit behind the shared
retry/backoff helper so rate limiting is consistent with the other sources.

Docs: https://www.ncbi.nlm.nih.gov/books/NBK25500/
"""

from typing import Any

from pydantic import ValidationError

from snowcite.dedup import normalize_doi
from snowcite.logging import log
from snowcite.sources._http import http_get
from snowcite.sources.base import Paper


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _year_from_pubdate(pubdate: str | None) -> int | None:
    """PubMed pubdate strings: '2023 May 12', '2023 Spring', '2023' etc."""
    if not pubdate:
        return None
    head = pubdate.strip().split(" ", 1)[0]
    return int(head) if head.isdigit() else None


def _doi_from_article_ids(article_ids: list[dict[str, Any]]) -> str | None:
    for aid in article_ids:
        if aid.get("idtype") == "doi":
            return aid.get("value")
    return None


def _to_paper(pmid: str, summary: dict[str, Any]) -> Paper | None:
    try:
        authors = [a["name"] for a in summary.get("authors") or [] if a.get("name")]
        return Paper(
            source="pubmed",
            source_id=pmid,
            doi=normalize_doi(_doi_from_article_ids(summary.get("articleids") or [])),
            title=(summary.get("title") or "").strip(),
            authors=authors,
            year=_year_from_pubdate(summary.get("pubdate")),
            venue=summary.get("fulljournalname") or summary.get("source"),
            abstract=None,  # esummary doesn't include abstracts; efetch would
            pdf_url=None,
            bibtex=None,
            metadata={"pmid": pmid, "pub_types": summary.get("pubtype")},
        )
    except (ValidationError, KeyError, TypeError) as e:
        log.warning("pubmed: skipping corrupt record (pmid=%s): %s", pmid, e)
        return None


async def search(
    query: str,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[Paper]:
    """Two-step: esearch → esummary.

    Abstracts require a third call (efetch with rettype=abstract) and come back as
    XML rather than JSON. That's a larger dependency and a separate pass; we skip
    it here and let the abstract stay None. For borderline papers the user can
    augment via a manual enrichment step later.
    """
    # Step 1 — esearch returns PMIDs matching the query.
    esearch_params: dict[str, str | int] = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": min(limit, 100),
    }
    # PubMed date filter via `mindate`/`maxdate` + `datetype=pdat` (publication).
    if year_from or year_to:
        esearch_params["mindate"] = str(year_from) if year_from else "1800"
        esearch_params["maxdate"] = str(year_to) if year_to else "3000"
        esearch_params["datetype"] = "pdat"

    resp = await http_get("pubmed", f"{BASE_URL}/esearch.fcgi", params=esearch_params)
    resp.raise_for_status()
    pmids = ((resp.json().get("esearchresult") or {}).get("idlist")) or []
    if not pmids:
        return []

    # Step 2 — esummary returns structured metadata for all PMIDs in one call.
    esum_params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
    resp = await http_get("pubmed", f"{BASE_URL}/esummary.fcgi", params=esum_params)
    resp.raise_for_status()
    result = (resp.json().get("result")) or {}

    out: list[Paper] = []
    for pmid in pmids:
        summary = result.get(pmid)
        if not summary:
            continue
        p = _to_paper(pmid, summary)
        if p is not None:
            out.append(p)
    return out
