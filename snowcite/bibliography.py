"""Bibliography generation — BibTeX (for LaTeX) and Hayagriva YAML (for Typst).

The same paper metadata flows into both formats. BibTeX is the classic; Hayagriva
is Typst's native bibliography format (https://github.com/typst/hayagriva), which
Typst's `#bibliography()` function accepts alongside `.bib`.
"""

import re
import unicodedata
from typing import Any


# ─── Shared helpers ─────────────────────────────────────────────────────────


def make_cite_key(authors: list[str], year: int | None, title: str) -> str:
    """Deterministic cite key: authorSurnameYearFirstTitleWord, lowercase."""
    first_author = authors[0].split()[-1] if authors else "unknown"
    first_author = re.sub(r"[^\w]", "", first_author)
    first_word = re.sub(r"[^\w]", "", title.split(maxsplit=1)[0]) if title else "untitled"
    return f"{first_author}{year or 'nd'}{first_word}".lower()


def disambiguate_key(key: str, used_keys: set[str]) -> str:
    """If `key` collides with `used_keys`, suffix a/b/c... until unique."""
    if key not in used_keys:
        used_keys.add(key)
        return key
    base = key
    suffix = ord("a")
    while key in used_keys:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    used_keys.add(key)
    return key


# ─── BibTeX ─────────────────────────────────────────────────────────────────

_LATEX_ESCAPES = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]


def escape_latex(text: str) -> str:
    """Escape special LaTeX characters. Public — shared with rendering/tables."""
    nfkd = unicodedata.normalize("NFKD", text)
    for ch, repl in _LATEX_ESCAPES:
        nfkd = nfkd.replace(ch, repl)
    return nfkd


_RAW_BIBTEX_KEY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)")


def extract_bibtex_key(entry: str) -> str | None:
    """Pull the cite key out of a raw BibTeX entry — `@article{key, ...}` → `key`.

    Used so pre-existing entries register their key in `used_keys`, preventing
    silent collisions when a generated key later lands on the same name.
    """
    m = _RAW_BIBTEX_KEY_RE.match(entry.strip())
    return m.group(1) if m else None


def generate_bibtex(
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None = None,
    doi: str | None = None,
    source: str | None = None,
    used_keys: set[str] | None = None,
) -> str:
    """Build a single BibTeX entry. Mutates `used_keys` if provided (for disambiguation)."""
    key = make_cite_key(authors, year, title)
    if used_keys is not None:
        key = disambiguate_key(key, used_keys)

    entry_type = "article"
    if source == "arxiv" or (venue and "arxiv" in venue.lower()):
        entry_type = "misc"

    lines = [f"@{entry_type}{{{key},"]
    lines.append(f"  title = {{{escape_latex(title)}}},")
    if authors:
        lines.append(f"  author = {{{' and '.join(escape_latex(a) for a in authors)}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if venue:
        field = "journal" if entry_type == "article" else "howpublished"
        lines.append(f"  {field} = {{{escape_latex(venue)}}},")
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    lines.append("}")
    return "\n".join(lines)


# ─── Hayagriva YAML (Typst) ─────────────────────────────────────────────────

# Hayagriva is Typst's native bibliography format. Docs:
# https://github.com/typst/hayagriva/blob/main/docs/file-format.md
#
# We produce a trivially-valid quoted subset — no need for PyYAML at runtime.


def _yaml_quote(s: str) -> str:
    """Double-quote a YAML string, escaping double-quotes and backslashes."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def generate_hayagriva_entry(
    cite_key: str,
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None = None,
    doi: str | None = None,
    source: str | None = None,
) -> str:
    """Return a Hayagriva YAML fragment for one entry (starts with `<key>:`).

    Joining fragments with "\\n\\n" produces a valid Hayagriva file.
    """
    # arXiv / arxiv-venue → `web` (Hayagriva has no native preprint type).
    entry_type = "article"
    if source == "arxiv" or (venue and "arxiv" in venue.lower()):
        entry_type = "web"

    lines = [f"{cite_key}:"]
    lines.append(f"  type: {entry_type}")
    lines.append(f"  title: {_yaml_quote(title)}")
    if authors:
        lines.append("  author:")
        lines.extend(f"    - {_yaml_quote(a)}" for a in authors)
    if year:
        lines.append(f'  date: "{year}"')
    if venue:
        lines.append("  parent:")
        lines.append("    type: periodical")
        lines.append(f"    title: {_yaml_quote(venue)}")
    if doi:
        lines.append("  serial-number:")
        lines.append(f"    doi: {_yaml_quote(doi)}")
    return "\n".join(lines)


def build_bibtex_document(entries: list[dict[str, Any]]) -> str:
    """Join per-paper BibTeX into a full .bib document.

    Each entry dict needs: title, authors, year, venue, doi, source. Entries
    carrying a pre-existing `bibtex` string (from the source API) are used
    verbatim; their cite keys are registered up-front so generated keys
    produced later can't collide with them.
    """
    # Pass 1 — claim every pre-existing cite key so later disambiguation sees them.
    used: set[str] = set()
    for e in entries:
        raw = e.get("bibtex")
        if raw:
            key = extract_bibtex_key(raw)
            if key:
                used.add(key)

    # Pass 2 — emit entries. Generated bibtex disambiguates against `used`.
    out: list[str] = []
    for e in entries:
        if e.get("bibtex"):
            out.append(e["bibtex"])
            continue
        out.append(
            generate_bibtex(
                title=e["title"],
                authors=e.get("authors") or [],
                year=e.get("year"),
                venue=e.get("venue"),
                doi=e.get("doi"),
                source=e.get("source"),
                used_keys=used,
            )
        )
    return "\n\n".join(out)


def generate_hayagriva(entries: list[dict[str, Any]]) -> str:
    """Build a full Hayagriva YAML document from a list of paper dicts.

    Each dict needs: title, authors, year, venue, doi, source. Cite keys are
    generated and disambiguated the same way as for BibTeX.
    """
    used_keys: set[str] = set()
    fragments: list[str] = []
    for e in entries:
        key = disambiguate_key(
            make_cite_key(e.get("authors") or [], e.get("year"), e.get("title") or ""),
            used_keys,
        )
        fragments.append(
            generate_hayagriva_entry(
                cite_key=key,
                title=e.get("title") or "",
                authors=e.get("authors") or [],
                year=e.get("year"),
                venue=e.get("venue"),
                doi=e.get("doi"),
                source=e.get("source"),
            )
        )
    return "\n\n".join(fragments) + "\n"
