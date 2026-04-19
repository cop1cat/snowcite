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
    gap_check,
    generate_overview_table,
    generate_prisma_flow,
    get_outline,
    get_section,
    get_skeleton,
    get_thesis,
    list_sections,
    polish_document,
    polish_section,
    rewrite_citations,
    save_outline,
    save_section,
    save_skeleton,
    save_thesis,
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


@pytest.mark.asyncio
async def test_rewrite_citations_remaps_bracketed_refs(tmp_project: Path):
    # Section with cites [1], [2, 3], [4]. Remap 1→11, 3→13; expect 1→11 and
    # 3→13 replaced, 2 and 4 left alone, structure of grouped cite preserved.
    await save_section("intro", "See [1] and [2, 3]; also [4].")
    r = await rewrite_citations(mapping={"1": 11, "3": 13})
    assert r["refs_replaced"] == 2
    assert len(r["modified"]) == 1
    assert r["modified"][0]["name"] == "intro"

    stored = await get_section("intro")
    assert "[11]" in stored["content"]
    assert "[2, 13]" in stored["content"]
    assert "[4]" in stored["content"]
    # Unchanged section ids should not get bumped.
    # Version was 1 initially (from save_section), now should be 2.
    assert stored["version"] == 2


@pytest.mark.asyncio
async def test_rewrite_citations_skips_sections_without_target_ids(tmp_project: Path):
    await save_section("a", "See [1].")
    await save_section("b", "See [99].")
    r = await rewrite_citations(mapping={"1": 2})
    assert r["refs_replaced"] == 1
    assert [m["name"] for m in r["modified"]] == ["a"]
    # Section b untouched — version stays at 1.
    assert (await get_section("b"))["version"] == 1


@pytest.mark.asyncio
async def test_rewrite_citations_empty_mapping_is_noop(tmp_project: Path):
    await save_section("x", "See [1].")
    r = await rewrite_citations(mapping={})
    assert r["refs_replaced"] == 0
    assert r["modified"] == []


# ─── Thesis + gap_check ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_thesis_save_and_get(tmp_project: Path):
    assert await get_thesis() is None
    r = await save_thesis("This paper surveys ML for mining.  \n\nSecond paragraph.")
    assert r["saved"] is True
    assert r["word_count"] > 0
    got = await get_thesis()
    assert got is not None
    assert "surveys ML" in got["content"]


@pytest.mark.asyncio
async def test_thesis_save_empty_is_error(tmp_project: Path):
    r = await save_thesis("   \n  ")
    assert "error" in r


@pytest.mark.asyncio
async def test_thesis_save_overwrites(tmp_project: Path):
    await save_thesis("first version")
    await save_thesis("second version is much longer and more detailed")
    got = await get_thesis()
    assert got["content"].startswith("second version")


@pytest.mark.asyncio
async def test_gap_check_flags_long_uncited_sentences(tmp_project: Path):
    # Two sentences: one with a cite, one without. Both above min_words.
    content = (
        "This claim is well documented in the literature [1]. "
        "A completely different assertion stands here with no supporting citation at all."
    )
    await save_section("intro", content)
    r = await gap_check(min_words=5)
    assert r["total_gaps"] == 1
    assert r["gaps"][0]["section"] == "intro"
    assert "completely different assertion" in r["gaps"][0]["sentences"][0]["sentence"]


@pytest.mark.asyncio
async def test_gap_check_skips_short_connectives(tmp_project: Path):
    # Short sentences below the default min_words are ignored even without cites.
    await save_section("short", "Hi. Also no cite here either really.")
    r = await gap_check()
    assert r["total_gaps"] == 0


@pytest.mark.asyncio
async def test_gap_check_no_sections_returns_empty(tmp_project: Path):
    r = await gap_check()
    assert r["total_gaps"] == 0
    assert r["gaps"] == []
