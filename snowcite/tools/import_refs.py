"""Import references from BibTeX and RIS files.

We parse a deliberately-narrow subset of both formats (enough for reference
manager exports from Mendeley, EndNote, Zotero-via-BibTeX, etc.) and route
the resulting papers through `snowcite.persistence.persist_papers` — same
DB write path as `search_papers`.

Papers missing an abstract get best-effort enrichment via OpenAlex / Semantic
Scholar lookups by DOI — `get_unreviewed_papers` assumes an abstract for
borderline decisions, so we try to fill it in before review starts.
"""

import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from snowcite.app import mcp
from snowcite.dedup import normalize_doi
from snowcite.logging import log
from snowcite.persistence import persist_papers
from snowcite.settings import settings
from snowcite.sources._http import http_get
from snowcite.sources.base import Paper


_OPENALEX_BASE = "https://api.openalex.org"
_SS_BASE = "https://api.semanticscholar.org/graph/v1"


def _ss_headers() -> dict[str, str]:
    if settings.semantic_scholar_api_key:
        return {"x-api-key": settings.semantic_scholar_api_key}
    return {}


# ─── BibTeX parsing ─────────────────────────────────────────────────────────

# A BibTeX entry looks like `@type{key, field = {value}, ...}`. We split on
# `@` at the start of a line so entries can span multiple lines freely.
_ENTRY_SPLIT_RE = re.compile(r"(?m)^@")
_HEAD_RE = re.compile(r"^(?P<type>[A-Za-z]+)\s*\{\s*(?P<key>[^,\s]+)\s*,", re.DOTALL)


def _strip_braces(value: str) -> str:
    """Remove matching {}/"" wrappers and leftover whitespace/newlines."""
    min_wrapped_len = 2  # one opening + one closing char
    v = value.strip().rstrip(",").strip()
    while len(v) >= min_wrapped_len and (
        (v[0] == "{" and v[-1] == "}") or (v[0] == '"' and v[-1] == '"')
    ):
        v = v[1:-1].strip()
    return re.sub(r"\s+", " ", v)


def _parse_bibtex_fields(body: str) -> dict[str, str]:  # noqa: PLR0912
    """Very small BibTeX field parser — balances braces, handles quoted values.

    Not a full grammar; skips `@string`/`@comment` pseudo-entries by virtue of
    being called only on `@article`/`@misc`/etc. bodies. The branch count here
    is inherent to the state machine (brace / quote / bareword / separator).
    """
    fields: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        # Find next field name.
        m = re.match(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*", body[i:])
        if not m:
            break
        name = m.group(1).lower()
        i += m.end()
        # Parse value: either {...} with nesting, "..." or barewords.
        if i >= n:
            break
        if body[i] == "{":
            depth = 0
            start = i
            while i < n:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            fields[name] = _strip_braces(body[start:i])
        elif body[i] == '"':
            start = i + 1
            i += 1
            while i < n and body[i] != '"':
                i += 1
            fields[name] = _strip_braces(body[start:i])
            if i < n:
                i += 1  # consume closing quote
        else:
            start = i
            while i < n and body[i] not in (",", "}"):
                i += 1
            fields[name] = _strip_braces(body[start:i])
        # Skip trailing comma.
        while i < n and body[i] in (",", " ", "\n", "\t"):
            i += 1
    return fields


def _authors_from_bibtex(raw: str) -> list[str]:
    """Split `A and B and C` into a list. Last-first form is preserved as-is."""
    if not raw:
        return []
    return [a.strip() for a in re.split(r"\s+and\s+", raw) if a.strip()]


def parse_bibtex(text: str) -> list[Paper]:
    """Parse a BibTeX file and return Paper objects with `source="crossref"`.

    Records without a DOI get a synthetic `source_id` from the cite key so they
    still persist; otherwise the DOI is authoritative.
    """
    papers: list[Paper] = []
    chunks = _ENTRY_SPLIT_RE.split(text)
    for chunk in chunks:
        if not chunk.strip():
            continue
        head = _HEAD_RE.match(chunk)
        if not head:
            continue
        entry_type = head.group("type").lower()
        if entry_type in ("string", "comment", "preamble"):
            continue
        cite_key = head.group("key")
        # Find the balanced closing brace for the entry body.
        body_start = head.end()
        depth = 1
        i = body_start
        while i < len(chunk) and depth > 0:
            if chunk[i] == "{":
                depth += 1
            elif chunk[i] == "}":
                depth -= 1
            i += 1
        body = chunk[body_start : i - 1]

        fields = _parse_bibtex_fields(body)
        doi = normalize_doi(fields.get("doi"))
        try:
            p = Paper(
                source="crossref",  # generic "not from a snowcite search" bucket
                source_id=doi or f"bibtex:{cite_key}",
                doi=doi,
                title=fields.get("title", "").strip(),
                authors=_authors_from_bibtex(fields.get("author", "")),
                year=int(fields["year"]) if fields.get("year", "").isdigit() else None,
                venue=fields.get("journal")
                or fields.get("booktitle")
                or fields.get("howpublished"),
                abstract=fields.get("abstract"),
                metadata={"import_source": "bibtex", "cite_key": cite_key, "type": entry_type},
            )
            papers.append(p)
        except (ValidationError, ValueError, KeyError) as e:
            log.warning("bibtex: skipping entry %r: %s", cite_key, e)
    return papers


# ─── RIS parsing ────────────────────────────────────────────────────────────

# RIS records are line-oriented: `XX  - value`. Records end with `ER  -` (no value).
_RIS_LINE_RE = re.compile(r"^([A-Z][A-Z0-9])  -\s*(.*)$")


def parse_ris(text: str) -> list[Paper]:
    papers: list[Paper] = []
    current: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = _RIS_LINE_RE.match(line)
        if not m:
            continue
        tag, value = m.group(1), m.group(2).strip()
        if tag == "ER":
            if current:
                paper = _ris_to_paper(current)
                if paper is not None:
                    papers.append(paper)
            current = {}
            continue
        current.setdefault(tag, []).append(value)
    return papers


def _ris_to_paper(record: dict[str, list[str]]) -> Paper | None:
    """Map a parsed RIS record → Paper. Returns None on unusable records."""
    # Title: TI is primary; T1 is an alias for journal articles.
    title = (record.get("TI") or record.get("T1") or [""])[0]
    if not title.strip():
        return None
    # Authors live under AU / A1 (multiple lines allowed).
    authors = []
    for tag in ("AU", "A1", "A2", "A3"):
        authors.extend(record.get(tag, []))
    # DOI under DO; year under PY / Y1 (may include month, take the first 4 digits).
    doi = normalize_doi((record.get("DO") or [None])[0])
    year_raw = (record.get("PY") or record.get("Y1") or [""])[0]
    year_match = re.match(r"\d{4}", year_raw)
    year = int(year_match.group(0)) if year_match else None
    venue = (
        record.get("JO") or record.get("JF") or record.get("T2") or record.get("BT") or [None]
    )[0]
    abstract = (record.get("AB") or record.get("N2") or [None])[0]
    try:
        return Paper(
            source="crossref",
            source_id=doi or f"ris:{title[:60]}",
            doi=doi,
            title=title.strip(),
            authors=[a.strip() for a in authors if a.strip()],
            year=year,
            venue=venue,
            abstract=abstract,
            metadata={"import_source": "ris"},
        )
    except (ValidationError, ValueError, KeyError) as e:
        log.warning("ris: skipping record with title %r: %s", title[:40], e)
        return None


# ─── Enrichment ─────────────────────────────────────────────────────────────


async def _openalex_abstract_by_doi(doi: str) -> str | None:
    """One DOI → one abstract via OpenAlex `/works/doi:...`."""
    try:
        resp = await http_get("openalex", f"{_OPENALEX_BASE}/works/doi:{doi}", timeout=10.0)
        if resp.status_code != httpx.codes.OK:
            return None
        inv = resp.json().get("abstract_inverted_index")
    except httpx.HTTPError:
        return None
    if not inv:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


async def _ss_abstract_by_doi(doi: str) -> str | None:
    try:
        resp = await http_get(
            "semantic_scholar",
            f"{_SS_BASE}/paper/DOI:{doi}",
            params={"fields": "abstract"},
            headers=_ss_headers(),
            timeout=10.0,
        )
        if resp.status_code != httpx.codes.OK:
            return None
        return resp.json().get("abstract")
    except httpx.HTTPError:
        return None


async def _enrich_abstracts(papers: list[Paper]) -> list[Paper]:
    """For papers with a DOI and no abstract, try OpenAlex then Semantic Scholar."""
    enriched: list[Paper] = []
    for p in papers:
        if p.abstract or not p.doi:
            enriched.append(p)
            continue
        abs_text = await _openalex_abstract_by_doi(p.doi) or await _ss_abstract_by_doi(p.doi)
        if abs_text:
            enriched.append(p.model_copy(update={"abstract": abs_text}))
        else:
            enriched.append(p)
    return enriched


# ─── Public MCP tools ───────────────────────────────────────────────────────


async def _import_core(papers: list[Paper], enrich: bool) -> dict[str, Any]:
    if enrich:
        papers = await _enrich_abstracts(papers)
    persisted = await persist_papers(papers)
    no_abstract = sum(1 for p in papers if not p.abstract)
    return {
        "parsed": len(papers),
        "saved": persisted["saved"],
        "duplicates": persisted["duplicates"],
        "new_ids": persisted["new_ids"],
        "without_abstract": no_abstract,
        "note": (
            "Papers without abstracts still land in `unreviewed` but will be sparse "
            "during review. Fetch a full snowball via `expand_citations(new_id)` or "
            "re-run the source search to enrich."
        )
        if no_abstract
        else None,
    }


@mcp.tool()
async def import_bibtex(file_path: str, enrich_abstracts: bool = True) -> dict[str, Any]:
    """Import papers from a BibTeX file. DOI dedup + optional abstract enrichment.

    If `enrich_abstracts=True` (default), papers without an abstract get one fetched
    from OpenAlex or Semantic Scholar by DOI. Skip enrichment if you're offline or
    want the import to stay fast — you can always enrich later via snowball.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return {"error": f"file not found: {file_path}"}
    text = path.read_text(encoding="utf-8")
    papers = parse_bibtex(text)
    return await _import_core(papers, enrich_abstracts)


@mcp.tool()
async def import_ris(file_path: str, enrich_abstracts: bool = True) -> dict[str, Any]:
    """Import papers from a RIS file (Mendeley / EndNote / Zotero RIS export).

    See `import_bibtex` for the enrichment contract.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return {"error": f"file not found: {file_path}"}
    text = path.read_text(encoding="utf-8")
    papers = parse_ris(text)
    return await _import_core(papers, enrich_abstracts)
