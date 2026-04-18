"""write_document end-to-end — renders the right template and bibliography file
for each backend. We don't test actual PDF compilation here (that's a smoke-test
and would need tectonic/typst installed); we verify the write step."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.compile import compile_pdf, write_document
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
async def test_compile_pdf_unknown_extension_errors(tmp_project: Path):
    bogus = tmp_project / "foo.bogus"
    bogus.write_text("hi")
    r = await compile_pdf(str(bogus))
    assert r["success"] is False
    assert "unknown source extension" in r["log"]


@pytest.mark.asyncio
async def test_compile_pdf_missing_file_errors(tmp_project: Path):
    r = await compile_pdf(str(tmp_project / "nope.tex"))
    assert r["success"] is False
    assert "file not found" in r["log"]
