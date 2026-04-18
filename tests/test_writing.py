"""T10: draft-first writing pipeline + PRISMA + overview table."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.review import set_review_status
from snowcite.tools.writing import (
    approve_outline,
    approve_skeleton,
    check_section_drift,
    generate_overview_table,
    generate_prisma_flow,
    get_outline,
    get_section,
    get_skeleton,
    list_sections,
    polish_document,
    polish_section,
    save_outline,
    save_section,
    save_skeleton,
)


# ─── Outline ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outline_save_get_approve(tmp_project: Path):
    sections = [
        {"name": "intro", "target_words": 400, "paper_ids": [1, 2]},
        {"name": "methods", "target_words": 800, "paper_ids": [3]},
    ]
    r = await save_outline(sections)
    assert r["saved"] and r["approved"] is False

    got = await get_outline()
    assert len(got["sections"]) == 2
    assert got["approved"] == 0

    r = await approve_outline()
    assert r["approved"] is True

    got = await get_outline()
    assert got["approved"] == 1


@pytest.mark.asyncio
async def test_approve_outline_without_save(tmp_project: Path):
    r = await approve_outline()
    assert r["approved"] is False
    assert "error" in r


@pytest.mark.asyncio
async def test_save_outline_resets_approval(tmp_project: Path):
    await save_outline([{"name": "a", "target_words": 100}])
    await approve_outline()
    # Re-saving outline should unset approval (user needs to re-approve).
    await save_outline([{"name": "b", "target_words": 100}])
    got = await get_outline()
    assert got["approved"] == 0


# ─── Skeleton ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skeleton_save_get_approve(tmp_project: Path):
    await save_outline([{"name": "intro", "target_words": 100}])
    await approve_outline()
    r = await save_skeleton([{"name": "intro", "draft": "Hello"}])
    assert r["saved"]
    got = await get_skeleton()
    assert len(got["sections"]) == 1
    await approve_skeleton()
    got = await get_skeleton()
    assert got["approved"] == 1


@pytest.mark.asyncio
async def test_skeleton_warns_when_names_diverge_from_outline(tmp_project: Path):
    await save_outline(
        [{"name": "intro", "target_words": 100}, {"name": "methods", "target_words": 100}]
    )
    await approve_outline()
    r = await save_skeleton([{"name": "intro", "draft": "x"}, {"name": "extra", "draft": "y"}])
    warnings = r.get("warnings") or []
    assert any("missing outline sections" in w for w in warnings)
    assert any("sections not in outline" in w for w in warnings)


@pytest.mark.asyncio
async def test_skeleton_warns_when_outline_unapproved(tmp_project: Path):
    await save_outline([{"name": "a", "target_words": 100}])
    r = await save_skeleton([{"name": "a", "draft": "..."}])
    assert any("not yet approved" in w for w in r.get("warnings", []))


# ─── Section content + drift ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_section_save_and_version_bump(tmp_project: Path):
    r1 = await save_section("intro", "one two three four five")
    assert r1["version"] == 1
    assert r1["word_count"] == 5

    r2 = await save_section("intro", "totally different")
    assert r2["version"] == 2

    got = await get_section("intro")
    assert got["content"] == "totally different"
    assert got["version"] == 2


@pytest.mark.asyncio
async def test_list_sections_shows_metadata_only(tmp_project: Path):
    await save_section("intro", "a b c")
    await save_section("methods", "one two three four")
    rows = await list_sections()
    assert {r["name"] for r in rows} == {"intro", "methods"}
    # No content body in the listing.
    assert all("content" not in r for r in rows)


@pytest.mark.asyncio
async def test_check_section_drift_no_outline(tmp_project: Path):
    r = await check_section_drift("intro", "hello world")
    assert r["has_drift"] is True
    assert any(w["kind"] == "no_outline" for w in r["warnings"])


@pytest.mark.asyncio
async def test_check_section_drift_unknown_section(tmp_project: Path):
    await save_outline([{"name": "intro", "target_words": 200}])
    await approve_outline()
    r = await check_section_drift("methods", "some content")
    assert any(w["kind"] == "unknown_section" for w in r["warnings"])


@pytest.mark.asyncio
async def test_check_section_drift_within_tolerance(tmp_project: Path):
    await save_outline([{"name": "intro", "target_words": 500}])
    await approve_outline()
    # 500 ±30% → up to ±150 words, so 450 or 600 is fine.
    content = " ".join(["word"] * 500)
    r = await check_section_drift("intro", content)
    assert r["has_drift"] is False


@pytest.mark.asyncio
async def test_check_section_drift_outside_tolerance(tmp_project: Path):
    await save_outline([{"name": "intro", "target_words": 500}])
    await approve_outline()
    content = " ".join(["word"] * 200)  # way under target
    r = await check_section_drift("intro", content)
    assert r["has_drift"] is True
    assert any(w["kind"] == "word_count" for w in r["warnings"])


@pytest.mark.asyncio
async def test_check_section_drift_small_section_uses_absolute_floor(tmp_project: Path):
    # Target 100, 30% = 30 words — but absolute floor is 100 words, so a
    # 150-word section is still within tolerance.
    await save_outline([{"name": "short", "target_words": 100}])
    await approve_outline()
    content = " ".join(["w"] * 150)
    r = await check_section_drift("short", content)
    assert r["has_drift"] is False


# ─── Polish ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_polish_section_sets_polished_flag(tmp_project: Path):
    await save_section("intro", "draft text")
    r = await polish_section("intro", "polished text, nicer")
    assert r["polished"] is True
    got = await get_section("intro")
    assert got["polished"] == 1
    assert got["content"] == "polished text, nicer"


@pytest.mark.asyncio
async def test_polish_section_missing_returns_error(tmp_project: Path):
    r = await polish_section("nope", "text")
    assert "error" in r


@pytest.mark.asyncio
async def test_polish_document_updates_existing_skips_missing(tmp_project: Path):
    await save_section("a", "aaa")
    await save_section("b", "bbb")
    r = await polish_document(
        [
            {"name": "a", "content": "polished a"},
            {"name": "b", "content": "polished b"},
            {"name": "ghost", "content": "never created"},
        ]
    )
    assert set(r["updated"]) == {"a", "b"}
    assert r["missing"] == ["ghost"]


# ─── PRISMA flow ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prisma_flow_reflects_review_history(tmp_project: Path):
    await persist_papers(
        [Paper(source="arxiv", source_id=str(i), title=f"p{i}") for i in range(1, 5)]
    )
    await set_review_status([1, 2], "approved", reason="r", reviewed_by="auto_high")
    await set_review_status([3], "rejected", reason="off-topic", reviewed_by="auto_high")
    await set_review_status([4], "rejected", reason="off-topic", reviewed_by="auto_high")

    r = await generate_prisma_flow(backend="typst")
    counts = r["counts"]
    assert counts["identified"] == 4
    assert counts["screened"] == 4
    assert counts["included"] == 2
    assert counts["excluded_total"] == 2
    assert r["snippet"].startswith("#figure")


@pytest.mark.asyncio
async def test_prisma_flow_latex_backend(tmp_project: Path):
    r = await generate_prisma_flow(backend="latex")
    assert r["backend"] == "latex"
    assert r["snippet"].startswith(r"\begin{figure}")
    assert "tikzpicture" in r["snippet"]


# ─── Overview table ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overview_table_typst_contains_approved_papers(tmp_project: Path):
    await persist_papers(
        [
            Paper(
                source="openalex",
                source_id="1",
                title="Paper A",
                authors=["Alice Smith"],
                year=2023,
                venue="ICML",
            ),
            Paper(
                source="openalex",
                source_id="2",
                title="Paper B",
                authors=["Bob Jones"],
                year=2024,
                venue="Nature",
            ),
        ]
    )
    await set_review_status([1, 2], "approved", reason="r", reviewed_by="auto_high")

    r = await generate_overview_table(backend="typst")
    assert r["rows"] == 2
    snippet = r["snippet"]
    assert snippet.startswith("#table(")
    assert "Paper A" in snippet
    assert "Paper B" in snippet
    assert "Smith" in snippet  # last-name only for author column


@pytest.mark.asyncio
async def test_overview_table_latex_longtable(tmp_project: Path):
    await persist_papers(
        [Paper(source="openalex", source_id="1", title="T", authors=["J Doe"], year=2024)]
    )
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")

    r = await generate_overview_table(backend="latex", columns=["year", "title"])
    assert r["snippet"].startswith(r"\begin{longtable}")
    assert "Year & Title" in r["snippet"]
