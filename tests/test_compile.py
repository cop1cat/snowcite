"""write_document end-to-end — renders the right template and bibliography file
for each backend. We don't test actual PDF compilation here (that's a smoke-test
and would need tectonic/typst installed); we verify the write step."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.compile import (
    _pdf_page_count,
    compile_pdf,
    estimate_pages,
    write_document,
)
from snowcite.tools.review import set_review_status


async def _seed_approved(paper: Paper) -> None:
    await persist_papers([paper])
    await set_review_status([1], "approved", reason="test", reviewed_by="auto_high")


@pytest.mark.asyncio
async def test_write_document_latex_produces_tex_and_bib(tmp_project: Path):
    await _seed_approved(
        Paper(source="openalex", source_id="1", title="T", doi="10.1/a", year=2024)
    )

    result = await write_document(
        sections=[{"title": "Intro", "content": "Hello"}],
        title="Review",
        author="Alice",
        backend="latex",
        standard="plain",
        output_dir=str(tmp_project),
    )

    doc = Path(result["doc_path"])
    bib = Path(result["bib_path"])
    assert doc.suffix == ".tex"
    assert bib.suffix == ".bib"
    assert doc.exists() and bib.exists()

    tex = doc.read_text()
    assert "Review" in tex
    assert "Alice" in tex
    assert r"\section{Intro}" in tex
    assert "babel" in tex
    # bib has an entry
    assert bib.read_text().strip()


@pytest.mark.asyncio
async def test_write_document_typst_produces_typ_and_yml(tmp_project: Path):
    await _seed_approved(
        Paper(source="openalex", source_id="1", title="T", doi="10.1/a", year=2024)
    )

    result = await write_document(
        sections=[{"title": "Введение", "content": "Привет"}],
        title="Обзор",
        author="Иван",
        backend="typst",
        standard="plain",
        language="ru",
        output_dir=str(tmp_project),
    )

    doc = Path(result["doc_path"])
    bib = Path(result["bib_path"])
    assert doc.suffix == ".typ"
    assert bib.suffix == ".yml"

    typ = doc.read_text()
    assert "Обзор" in typ
    assert "Иван" in typ
    assert "= Введение" in typ
    assert 'lang: "ru"' in typ

    yml = bib.read_text()
    assert ":" in yml  # Hayagriva is YAML


@pytest.mark.asyncio
async def test_write_document_includes_bib_only_for_approved(tmp_project: Path):
    # Seed one approved and one rejected — only approved should appear in bib.
    await persist_papers(
        [
            Paper(source="openalex", source_id="1", title="Keeper", doi="10.1/a"),
            Paper(source="openalex", source_id="2", title="Dropped", doi="10.1/b"),
        ]
    )
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")
    await set_review_status([2], "rejected", reason="r", reviewed_by="auto_high")

    result = await write_document(
        sections=[],
        title="X",
        author="Y",
        backend="latex",
        output_dir=str(tmp_project),
    )
    bib = Path(result["bib_path"]).read_text()
    assert "Keeper" in bib
    assert "Dropped" not in bib


@pytest.mark.asyncio
async def test_write_document_rewrites_numeric_cites_latex(tmp_project: Path):
    # Regression: sections arrive with `[N]` paper-id citations; the bib has
    # `@article{smith2024foo,...}`. write_document must rewrite `[1]` into
    # `\cite{smith2024foo}` so the PDF actually finds the reference.
    await _seed_approved(
        Paper(
            source="openalex",
            source_id="1",
            title="Foo Bar Baz",
            authors=["John Smith"],
            year=2024,
            doi="10.1/x",
        )
    )

    result = await write_document(
        sections=[{"title": "Intro", "content": "As shown in [1], the method works."}],
        title="R",
        author="A",
        backend="latex",
        output_dir=str(tmp_project),
    )
    tex = Path(result["doc_path"]).read_text()
    bib = Path(result["bib_path"]).read_text()
    assert "\\cite{smith2024foo}" in tex
    assert "[1]" not in tex  # rewriter must have replaced the numeric ref
    assert "@article{smith2024foo," in bib


@pytest.mark.asyncio
async def test_write_document_rewrites_numeric_cites_typst(tmp_project: Path):
    await _seed_approved(
        Paper(
            source="openalex",
            source_id="1",
            title="Foo Bar",
            authors=["Jane Doe"],
            year=2023,
            doi="10.1/y",
        )
    )

    result = await write_document(
        sections=[{"title": "Раздел", "content": "См. [1]."}],
        title="Обзор",
        author="Иван",
        backend="typst",
        output_dir=str(tmp_project),
    )
    typ = Path(result["doc_path"]).read_text()
    yml = Path(result["bib_path"]).read_text()
    assert "@doe2023foo" in typ
    assert "doe2023foo:" in yml


@pytest.mark.asyncio
async def test_compile_pdf_unknown_extension_errors(tmp_project: Path):
    bogus = tmp_project / "foo.bogus"
    bogus.write_text("hi")
    r = await compile_pdf(str(bogus))
    assert r["success"] is False
    assert "unknown source extension" in r["log"]


def test_pdf_page_count_from_pages_count():
    # Synthetic PDF-ish bytes — `/Type /Pages ... /Count N` is what we parse.
    pdf = b"%PDF-1.7\n... /Type /Pages /Kids [...] /Count 7 ...\n%%EOF"
    assert _pdf_page_count(pdf) == 7


def test_pdf_page_count_takes_max_when_multiple_pages_trees():
    # Nested Pages trees: root carries the total, intermediate nodes sum
    # subsets. Taking max gives the total regardless of tree shape.
    pdf = b"/Type /Pages /Count 3 ... /Type /Pages /Count 12 ..."
    assert _pdf_page_count(pdf) == 12


def test_pdf_page_count_fallback_counts_page_entries():
    # No /Pages /Count — fall back to counting individual /Type /Page refs.
    pdf = b"/Type /Page\n/Type /Page\n/Type /Page\n/Type /Catalog"
    assert _pdf_page_count(pdf) == 3


@pytest.mark.asyncio
async def test_estimate_pages_no_sections_returns_gracefully(tmp_project: Path):
    r = await estimate_pages()
    assert r["pages"] is None
    assert r["sections_rendered"] == 0
    assert r["compile_success"] is False
    assert "no sections" in r["log"]


@pytest.mark.asyncio
async def test_compile_pdf_missing_file_errors(tmp_project: Path):
    r = await compile_pdf(str(tmp_project / "nope.tex"))
    assert r["success"] is False
    assert "file not found" in r["log"]
