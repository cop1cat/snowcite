"""T21: parse BibTeX and RIS files into Paper objects. Enrichment via HTTP is
not exercised here — the parser side is the interesting contract."""

from pathlib import Path

import pytest

from snowcite.tools.import_refs import (
    _authors_from_bibtex,
    _parse_bibtex_fields,
    _strip_braces,
    import_bibtex,
    import_ris,
    parse_bibtex,
    parse_ris,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def test_strip_braces_balances_wrappers():
    assert _strip_braces("  {hello}  ") == "hello"
    assert _strip_braces('"world",') == "world"
    assert _strip_braces("  bareword  ") == "bareword"
    assert _strip_braces("{{double braces}}") == "double braces"


def test_authors_split_on_and():
    assert _authors_from_bibtex("Smith, J. and Doe, A. B. and Kim, Y.") == [
        "Smith, J.",
        "Doe, A. B.",
        "Kim, Y.",
    ]


def test_parse_bibtex_fields_braces_and_quotes():
    body = 'title = {A {nested} title}, year = "2024", author = {Jane Doe}'
    fields = _parse_bibtex_fields(body)
    assert fields["title"] == "A {nested} title"
    assert fields["year"] == "2024"
    assert fields["author"] == "Jane Doe"


# ─── BibTeX parser ──────────────────────────────────────────────────────────


def test_parse_bibtex_basic_entry():
    src = """
@article{doe2024,
  title = {Adversarial attacks on language models},
  author = {Doe, Jane and Smith, John},
  year = {2024},
  journal = {ICML},
  doi = {10.1/abc},
  abstract = {This is an abstract.}
}
"""
    papers = parse_bibtex(src)
    assert len(papers) == 1
    p = papers[0]
    assert p.title == "Adversarial attacks on language models"
    assert p.authors == ["Doe, Jane", "Smith, John"]
    assert p.year == 2024
    assert p.venue == "ICML"
    assert p.doi == "10.1/abc"
    assert p.abstract == "This is an abstract."


def test_parse_bibtex_no_doi_uses_cite_key_in_source_id():
    src = "@misc{foo2020bar, title = {T}, year = {2020}}"
    papers = parse_bibtex(src)
    assert papers[0].source_id == "bibtex:foo2020bar"


def test_parse_bibtex_multiple_entries():
    src = """
@article{a, title = {First}, year = {2020}}
@article{b, title = {Second}, year = {2021}}
@misc{c, title = {Third}}
"""
    papers = parse_bibtex(src)
    assert {p.title for p in papers} == {"First", "Second", "Third"}


def test_parse_bibtex_ignores_string_and_comment():
    src = """
@string{j = {Some Journal}}
@comment{this is a comment}
@article{real, title = {Real Paper}, year = {2020}}
"""
    papers = parse_bibtex(src)
    assert len(papers) == 1
    assert papers[0].title == "Real Paper"


def test_parse_bibtex_handles_missing_year_gracefully():
    src = "@article{nodate, title = {T}, year = {n.d.}}"
    papers = parse_bibtex(src)
    assert papers[0].year is None


# ─── RIS parser ─────────────────────────────────────────────────────────────


def test_parse_ris_basic_record():
    src = """TY  - JOUR
TI  - RIS paper title
AU  - Smith, Jane
AU  - Doe, John
PY  - 2023
JO  - Nature
DO  - 10.1/xyz
AB  - RIS abstract text.
ER  -
"""
    papers = parse_ris(src)
    assert len(papers) == 1
    p = papers[0]
    assert p.title == "RIS paper title"
    assert p.authors == ["Smith, Jane", "Doe, John"]
    assert p.year == 2023
    assert p.venue == "Nature"
    assert p.doi == "10.1/xyz"
    assert p.abstract == "RIS abstract text."


def test_parse_ris_multiple_records():
    src = """TY  - JOUR
TI  - First
PY  - 2020
ER  -
TY  - JOUR
TI  - Second
PY  - 2021
ER  -
"""
    papers = parse_ris(src)
    assert [p.title for p in papers] == ["First", "Second"]


def test_parse_ris_year_tolerates_month():
    src = "TI  - Title\nPY  - 2024/May\nER  -\n"
    papers = parse_ris(src)
    assert papers[0].year == 2024


def test_parse_ris_skips_record_without_title():
    src = "TY  - JOUR\nAU  - X\nER  -\nTI  - Good\nER  -\n"
    papers = parse_ris(src)
    assert len(papers) == 1
    assert papers[0].title == "Good"


# ─── End-to-end (persistence, no network) ───────────────────────────────────


@pytest.mark.asyncio
async def test_import_bibtex_persists_to_db(tmp_project: Path):
    bib = tmp_project / "refs.bib"
    bib.write_text(
        """
@article{doe2024,
  title = {Paper},
  author = {Doe, Jane},
  year = {2024},
  doi = {10.1/zzz},
  abstract = {Already has an abstract.}
}
""",
        encoding="utf-8",
    )
    result = await import_bibtex(str(bib), enrich_abstracts=False)
    assert result["parsed"] == 1
    assert result["saved"] == 1
    assert result["without_abstract"] == 0


@pytest.mark.asyncio
async def test_import_ris_persists_to_db(tmp_project: Path):
    ris = tmp_project / "refs.ris"
    ris.write_text(
        "TY  - JOUR\nTI  - RIS Import\nAU  - Author\nPY  - 2023\nDO  - 10.9/rrr\nER  -\n",
        encoding="utf-8",
    )
    result = await import_ris(str(ris), enrich_abstracts=False)
    assert result["parsed"] == 1
    assert result["saved"] == 1
    # No abstract supplied, enrichment disabled → counted as missing.
    assert result["without_abstract"] == 1


@pytest.mark.asyncio
async def test_import_bibtex_missing_file_returns_error(tmp_project: Path):
    r = await import_bibtex(str(tmp_project / "does_not_exist.bib"), enrich_abstracts=False)
    assert "error" in r
