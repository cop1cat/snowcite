"""Bibliography generation — BibTeX (for LaTeX) and Hayagriva YAML (for Typst).

The same paper metadata flows into both formats. BibTeX is the classic; Hayagriva
is Typst's native bibliography format (https://github.com/typst/hayagriva), which
Typst's `#bibliography()` function accepts alongside `.bib`.
"""

import re
import unicodedata
from typing import Any

from snowcite.logging import log


# ─── Shared helpers ─────────────────────────────────────────────────────────

# Stop-words skipped when title-word fallback is needed for the cite-key prefix.
# Kept intentionally short — any noun-like word is preferable to "anon".
_TITLE_STOPWORDS = frozenset(
    {"a", "an", "the", "on", "of", "in", "to", "for", "and", "or", "is", "at", "by"}
)


def _title_fallback_word(title: str) -> str:
    """Pick the first non-trivial word from a title for use as a cite-key prefix.

    Returns "anon" only when the title has no usable words at all — preferable
    to the old "unknown" sentinel, which produced keys like `unknown2024foo`
    that looked like bugs in the output.
    """
    if not title:
        return "anon"
    for raw in title.split():
        word = re.sub(r"[^\w]", "", raw).lower()
        if word and word not in _TITLE_STOPWORDS and not word.isdigit():
            return word
    return "anon"


def make_cite_key(authors: list[str], year: int | None, title: str) -> str:
    """Deterministic cite key: authorSurnameYearFirstTitleWord, lowercase.

    When `authors` is empty (common for papers saved via WebSearch without
    structured author metadata) we fall back to the first meaningful title
    word rather than the legacy "unknown" sentinel — keeps keys recognisable
    when eyeballing the .bib / .yml.
    """
    if authors:
        first_author = re.sub(r"[^\w]", "", authors[0].split()[-1])
    else:
        first_author = _title_fallback_word(title)
        log.warning(
            "make_cite_key: no authors for title %r — falling back to title word %r",
            title,
            first_author,
        )
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


def assign_cite_keys(entries: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """Assign a stable, disambiguated cite key to each entry.

    Single source of truth for cite keys: both `build_bibtex_document` /
    `generate_hayagriva` and the in-text citation rewriter in `write_document`
    consume this so text refs and bibliography stay in sync.

    Entries carrying a pre-existing `bibtex` string keep whatever key that raw
    entry declares. Generated keys disambiguate against the pre-existing ones.
    Returned order matches input order.
    """
    used: set[str] = set()

    # Pass 1 — claim keys from pre-existing raw BibTeX so generated keys below
    # can't silently collide with them.
    for e in entries:
        raw = e.get("bibtex")
        if raw:
            k = extract_bibtex_key(raw)
            if k:
                used.add(k)

    assigned: list[tuple[dict[str, Any], str]] = []
    for e in entries:
        raw = e.get("bibtex")
        if raw:
            key = extract_bibtex_key(raw)
            if key is None:
                # Raw entry without a parseable key — generate one for it so
                # the rewriter still has something to point at.
                key = disambiguate_key(
                    make_cite_key(
                        e.get("authors") or [], e.get("year"), e.get("title") or ""
                    ),
                    used,
                )
        else:
            key = disambiguate_key(
                make_cite_key(e.get("authors") or [], e.get("year"), e.get("title") or ""),
                used,
            )
        assigned.append((e, key))
    return assigned


def build_cite_key_map(entries: list[dict[str, Any]]) -> dict[int, str]:
    """Return `{entry["id"]: cite_key}` for entries that carry an `id` field.

    Used by `write_document` to rewrite `[N]`-style paper-id citations into
    the cite keys the bibliography actually publishes.
    """
    return {e["id"]: k for e, k in assign_cite_keys(entries) if "id" in e}


def build_bibtex_document(entries: list[dict[str, Any]]) -> str:
    """Join per-paper BibTeX into a full .bib document.

    Each entry dict needs: title, authors, year, venue, doi, source. Entries
    carrying a pre-existing `bibtex` string (from the source API) are used
    verbatim; their cite keys are registered up-front so generated keys
    produced later can't collide with them.
    """
    out: list[str] = []
    for e, key in assign_cite_keys(entries):
        raw = e.get("bibtex")
        if raw:
            out.append(raw)
            continue
        # The key is already chosen; regenerate the BibTeX with it injected.
        # We reuse generate_bibtex but bypass its own disambiguation — passing
        # an empty `used_keys` set is safe because `key` is already unique.
        entry = generate_bibtex(
            title=e["title"],
            authors=e.get("authors") or [],
            year=e.get("year"),
            venue=e.get("venue"),
            doi=e.get("doi"),
            source=e.get("source"),
        )
        # Force the pre-assigned key so output matches assign_cite_keys.
        entry = re.sub(r"^(@[A-Za-z]+\{)[^,]+,", rf"\1{key},", entry, count=1)
        out.append(entry)
    return "\n\n".join(out)


def generate_hayagriva(entries: list[dict[str, Any]]) -> str:
    """Build a full Hayagriva YAML document from a list of paper dicts.

    Each dict needs: title, authors, year, venue, doi, source. Cite keys come
    from `assign_cite_keys` — same source the BibTeX path uses.
    """
    fragments: list[str] = []
    for e, key in assign_cite_keys(entries):
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


# ─── In-text citation rewriter ──────────────────────────────────────────────

# Matches `[N]`, `[N, M]`, `[N; M]`, `[N,M,K]` — bracketed groups of one or
# more comma/semicolon-separated integers. Conservative: won't match `[foo]`,
# `[@key]`, `[N-M]` or prose containing numbers mid-sentence.
_CITE_REF_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def rewrite_cite_refs(content: str, id_to_key: dict[int, str], backend: str) -> str:
    """Rewrite `[N]` paper-id citations in text to backend-native cite syntax.

    Paper IDs are the DB row ids returned by `save_papers` / visible in
    `get_unreviewed_papers`. Claude writes text using those (e.g. "...shown
    in [61, 62]..."), this function resolves them to the real cite keys.

    - LaTeX backend → `\\cite{key1,key2}` (biblatex/natbib grouping).
    - Typst backend → `@key1 @key2` (numeric styles collapse consecutive refs).

    Unknown ids are left as-is with a warning logged — so the output compiles
    but the reviewer can spot orphans in the rendered PDF.
    """

    def _replace(match: re.Match[str]) -> str:
        raw_ids = [int(x.strip()) for x in re.split(r"[,;]", match.group(1))]
        keys: list[str] = []
        for pid in raw_ids:
            k = id_to_key.get(pid)
            if k is None:
                log.warning(
                    "rewrite_cite_refs: paper id %d not in approved set — left as [%d]",
                    pid,
                    pid,
                )
                return match.group(0)
            keys.append(k)
        if backend == "latex":
            return "\\cite{" + ",".join(keys) + "}"
        # Typst: space-join so consecutive `@k` refs survive intact; numeric
        # CSL styles (ieee, gost-r-705-2008-numeric) collapse them into
        # "[1, 2]" at render time.
        return " ".join(f"@{k}" for k in keys)

    return _CITE_REF_RE.sub(_replace, content)
