"""Generate BibTeX entries from paper metadata when the API didn't provide one."""

import re
import unicodedata


def _make_cite_key(authors: list[str], year: int | None, title: str) -> str:
    first_author = authors[0].split()[-1] if authors else "unknown"
    first_author = re.sub(r"[^\w]", "", first_author)
    first_word = re.sub(r"[^\w]", "", title.split()[0]) if title else "untitled"
    return f"{first_author}{year or 'nd'}{first_word}".lower()


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


def _escape_latex(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    for ch, repl in _LATEX_ESCAPES:
        nfkd = nfkd.replace(ch, repl)
    return nfkd


def generate_bibtex(
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None = None,
    doi: str | None = None,
    source: str | None = None,
    used_keys: set[str] | None = None,
) -> str:
    key = _make_cite_key(authors, year, title)
    if used_keys is not None:
        base_key = key
        suffix = ord("a")
        while key in used_keys:
            key = f"{base_key}{chr(suffix)}"
            suffix += 1
        used_keys.add(key)
    entry_type = "article"
    if source == "arxiv" or (venue and "arxiv" in venue.lower()):
        entry_type = "misc"

    lines = [f"@{entry_type}{{{key},"]
    lines.append(f"  title = {{{_escape_latex(title)}}},")
    if authors:
        lines.append(f"  author = {{{' and '.join(_escape_latex(a) for a in authors)}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if venue:
        field = "journal" if entry_type == "article" else "howpublished"
        lines.append(f"  {field} = {{{_escape_latex(venue)}}},")
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    lines.append("}")
    return "\n".join(lines)
