"""Research-artifact persistence, MCP tools, writing-pipeline integration."""

from pathlib import Path

import pytest

from snowcite.artifacts import (
    citation_label,
    list_artifacts as _list_artifacts,
    load_artifact,
    load_artifacts_by_ids,
    save_artifact,
    set_included,
)
from snowcite.persistence import persist_papers
from snowcite.rendering import (
    include_code,
    primary_sources_appendix,
)
from snowcite.sources.base import Paper
from snowcite.tools.artifacts import (
    add_artifact_inline,
    delete_artifact,
    get_artifact,
    import_artifact,
    list_artifacts,
    set_artifact_included,
)
from snowcite.tools.review_quality import prepare_section_for_review
from snowcite.tools.writing import (
    approve_outline,
    generate_primary_sources_appendix,
    include_code_artifact,
    regenerate_section_brief,
    save_outline,
    save_section,
)


# ─── Persistence ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(tmp_project: Path):
    aid = await save_artifact(
        type="interview",
        label="P03 transcript",
        content="Q: ... A: ...",
        summary="First pilot interview",
        metadata={"participant": "P03"},
    )
    record = await load_artifact(aid)
    assert record is not None
    assert record["type"] == "interview"
    assert record["label"] == "P03 transcript"
    assert record["content"] == "Q: ... A: ..."
    assert record["metadata"]["participant"] == "P03"
    assert record["included"] is True


@pytest.mark.asyncio
async def test_list_filters_by_type_and_included(tmp_project: Path):
    await save_artifact(type="interview", label="i1", content="x")
    await save_artifact(type="code", label="c1", content="def f(): pass")
    cid = await save_artifact(type="code", label="c2", content="# notes")
    await set_included(cid, False)

    interviews = await _list_artifacts(type="interview")
    assert len(interviews) == 1

    code_all = await _list_artifacts(type="code")
    assert len(code_all) == 2

    code_included = await _list_artifacts(type="code", included_only=True)
    assert len(code_included) == 1
    assert code_included[0]["label"] == "c1"


@pytest.mark.asyncio
async def test_load_artifacts_by_ids_preserves_order(tmp_project: Path):
    a = await save_artifact(type="note", label="a", content="first")
    b = await save_artifact(type="note", label="b", content="second")
    c = await save_artifact(type="note", label="c", content="third")

    records = await load_artifacts_by_ids([c, a, b])
    # Function orders by id ascending, not by input order.
    assert [r["id"] for r in records] == sorted([a, b, c])


def test_citation_label_format():
    assert citation_label({"id": 3, "type": "interview"}) == "[I:3]"  # type: ignore[arg-type]
    assert citation_label({"id": 7, "type": "code"}) == "[C:7]"  # type: ignore[arg-type]
    assert citation_label({"id": 2, "type": "dataset"}) == "[DS:2]"  # type: ignore[arg-type]


# ─── MCP tools ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_artifact_reads_file(tmp_project: Path):
    src = tmp_project / "transcript.md"
    src.write_text("# Interview P01\n\nQ: ...\nA: ...", encoding="utf-8")

    r = await import_artifact(path=str(src), type="interview", label="P01", summary="Pilot")
    assert "id" in r
    assert r["chars"] > 0
    assert r["citation_label"].startswith("[I:")


@pytest.mark.asyncio
async def test_import_artifact_missing_file_errors(tmp_project: Path):
    r = await import_artifact(path=str(tmp_project / "nope.txt"), type="note", label="missing")
    assert "error" in r


@pytest.mark.asyncio
async def test_add_artifact_inline(tmp_project: Path):
    r = await add_artifact_inline(type="note", label="Idea 1", content="Research idea")
    assert "id" in r
    fetched = await get_artifact(r["id"])
    assert fetched is not None
    assert fetched["content"] == "Research idea"


@pytest.mark.asyncio
async def test_list_artifacts_omits_content(tmp_project: Path):
    await add_artifact_inline(type="note", label="n1", content="long body")
    rows = await list_artifacts()
    assert len(rows) == 1
    # Content omitted from listings for context hygiene.
    assert "content" not in rows[0]
    assert rows[0]["chars"] == len("long body")


@pytest.mark.asyncio
async def test_set_included_excludes_from_list(tmp_project: Path):
    r = await add_artifact_inline(type="note", label="temp", content="x")
    await set_artifact_included(r["id"], False)
    visible = await list_artifacts(included_only=True)
    assert visible == []


@pytest.mark.asyncio
async def test_delete_artifact(tmp_project: Path):
    r = await add_artifact_inline(type="note", label="drop me", content="x")
    out = await delete_artifact(r["id"])
    assert out["deleted"] is True
    assert await get_artifact(r["id"]) is None


# ─── Writing-pipeline integration ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_prepare_section_for_review_includes_artifacts(tmp_project: Path):
    # One paper, two artifacts (one excluded), one section tying them together.
    await persist_papers([Paper(source="arxiv", source_id="1", title="T", abstract="x")])
    aid_active = await save_artifact(type="interview", label="P01", content="Q: ...")
    aid_excluded = await save_artifact(type="interview", label="P02", content="Q: ...")
    await set_included(aid_excluded, False)

    await save_outline(
        [
            {
                "name": "findings",
                "target_words": 300,
                "paper_ids": [1],
                "artifact_ids": [aid_active, aid_excluded],
            }
        ]
    )
    await approve_outline()
    await save_section("findings", "Draft text referencing [I:1].")

    r = await prepare_section_for_review("findings")
    assert len(r["assigned_artifacts"]) == 1, "excluded artifact must be filtered out"
    assert r["assigned_artifacts"][0]["id"] == aid_active
    assert r["assigned_artifacts"][0]["content"] == "Q: ..."


@pytest.mark.asyncio
async def test_regenerate_section_brief_bundles_artifacts(tmp_project: Path):
    aid = await save_artifact(type="code", label="auth.py", content="def login():\n    ...")
    await save_outline(
        [{"name": "methods", "target_words": 200, "paper_ids": [], "artifact_ids": [aid]}]
    )
    await approve_outline()
    await save_section("methods", "Current draft.")

    r = await regenerate_section_brief("methods", feedback="add a code excerpt")
    assert len(r["assigned_artifacts"]) == 1
    assert "citation_label" in r["instructions"]


# ─── Rendering helpers ──────────────────────────────────────────────────────


def test_include_code_typst_uses_raw_read_when_path_set():
    artifact = {
        "id": 1,
        "type": "code",
        "label": "auth.py",
        "source_path": "/abs/path/auth.py",
        "content": "ignored when path is set",
        "summary": None,
        "metadata": {"language": "python"},
        "included": True,
        "created_at": "",
    }
    out = include_code(artifact, "typst")  # type: ignore[arg-type]
    assert 'raw(read("/abs/path/auth.py")' in out
    assert 'lang: "python"' in out


def test_include_code_latex_uses_lstinputlisting():
    artifact = {
        "id": 1,
        "type": "code",
        "label": "auth.py",
        "source_path": "/abs/path/auth.py",
        "content": "",
        "summary": None,
        "metadata": {},
        "included": True,
        "created_at": "",
    }
    out = include_code(artifact, "latex")  # type: ignore[arg-type]
    assert r"\lstinputlisting" in out
    assert "/abs/path/auth.py" in out


def test_primary_sources_appendix_skips_excluded_and_empty():
    assert primary_sources_appendix([], "typst") == ""
    items = [
        {
            "id": 1,
            "type": "interview",
            "label": "P01",
            "source_path": None,
            "content": "",
            "summary": "Pilot",
            "metadata": {},
            "included": True,
            "created_at": "",
        },
        {
            "id": 2,
            "type": "note",
            "label": "n1",
            "source_path": None,
            "content": "",
            "summary": None,
            "metadata": {},
            "included": False,
            "created_at": "",
        },
    ]
    out = primary_sources_appendix(items, "typst")  # type: ignore[arg-type]
    assert "[I:1]" in out
    assert "P01" in out
    assert "n1" not in out  # excluded record skipped
    assert "Pilot" in out


# ─── MCP tools for rendering ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_include_code_artifact_typst(tmp_project: Path):
    src = tmp_project / "auth.py"
    src.write_text("print('hi')", encoding="utf-8")
    r = await import_artifact(
        path=str(src), type="code", label="auth", metadata={"language": "python"}
    )
    out = await include_code_artifact(r["id"], backend="typst")
    assert "snippet" in out
    assert 'lang: "python"' in out["snippet"]


@pytest.mark.asyncio
async def test_include_code_artifact_rejects_non_code(tmp_project: Path):
    r = await add_artifact_inline(type="note", label="n", content="x")
    out = await include_code_artifact(r["id"])
    assert "error" in out


@pytest.mark.asyncio
async def test_generate_primary_sources_appendix_entries_count(tmp_project: Path):
    await add_artifact_inline(type="interview", label="P01", content="...")
    await add_artifact_inline(type="note", label="Idea", content="...")
    out = await generate_primary_sources_appendix(backend="typst")
    assert out["entries"] == 2
    assert "P01" in out["snippet"]
