"""T12/T13/T15/T16: bulk reclassify, undo, regenerate, export."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.export import export_bibtex, export_ris
from snowcite.tools.review import (
    bulk_reclassify,
    save_review_summary,
    set_review_status,
    undo_last_review_action,
)
from snowcite.tools.writing import (
    approve_outline,
    regenerate_section_brief,
    save_outline,
    save_section,
)


# ─── T13 — undo ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_undo_reverts_last_action_to_unreviewed(tmp_project: Path):
    await persist_papers([Paper(source="arxiv", source_id="x", title="T")])
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")

    r = await undo_last_review_action()
    assert r["undone"] is True
    assert r["reverted_to"] == "unreviewed"
    assert r["was"] == "approved"


@pytest.mark.asyncio
async def test_undo_restores_previous_status_when_not_first(tmp_project: Path):
    await persist_papers([Paper(source="arxiv", source_id="x", title="T")])
    await set_review_status([1], "approved", reason="r1", reviewed_by="auto_high")
    await set_review_status([1], "rejected", reason="r2", reviewed_by="auto_high")

    # Undo the "rejected" action → back to "approved".
    r = await undo_last_review_action()
    assert r["reverted_to"] == "approved"


@pytest.mark.asyncio
async def test_undo_empty_history_is_noop(tmp_project: Path):
    r = await undo_last_review_action()
    assert r["undone"] is False


@pytest.mark.asyncio
async def test_undo_does_not_leave_orphan_history_row(tmp_project: Path):
    """The history row for the undone action should itself be removed, so that a
    second undo walks further back rather than replaying the same entry."""
    await persist_papers(
        [
            Paper(source="arxiv", source_id="a", title="A"),
            Paper(source="arxiv", source_id="b", title="B"),
        ]
    )
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")
    await set_review_status([2], "rejected", reason="r", reviewed_by="auto_high")
    # Two undos → both revert.
    r1 = await undo_last_review_action()
    r2 = await undo_last_review_action()
    assert r1["paper_id"] == 2
    assert r2["paper_id"] == 1


# ─── T12 — bulk reclassify ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_reclassify_by_status(tmp_project: Path):
    await persist_papers(
        [Paper(source="arxiv", source_id=str(i), title=f"P{i}") for i in range(1, 6)]
    )
    await set_review_status([1, 2, 3], "approved", reason="r", reviewed_by="auto_high")
    await set_review_status([4, 5], "rejected", reason="r", reviewed_by="auto_high")

    # Flip all approved → maybe.
    r = await bulk_reclassify(
        new_status="maybe",
        reason="narrowing scope",
        current_status="approved",
    )
    assert r["updated"] == 3


@pytest.mark.asyncio
async def test_bulk_reclassify_by_source(tmp_project: Path):
    await persist_papers(
        [
            Paper(source="arxiv", source_id="1", title="A"),
            Paper(source="openalex", source_id="2", title="B"),
        ]
    )
    r = await bulk_reclassify(
        new_status="rejected",
        reason="source sanity",
        source="arxiv",
    )
    assert r["updated"] == 1


@pytest.mark.asyncio
async def test_bulk_reclassify_by_cluster(tmp_project: Path):
    await persist_papers(
        [Paper(source="arxiv", source_id=str(i), title=f"P{i}") for i in range(1, 4)]
    )
    await set_review_status([1, 2, 3], "approved", reason="r", reviewed_by="auto_high")
    await save_review_summary(
        summary="test",
        clusters=[
            {"topic": "attacks-classic", "paper_ids": [1, 2], "count": 2},
            {"topic": "defenses", "paper_ids": [3], "count": 1},
        ],
    )
    r = await bulk_reclassify(
        new_status="maybe",
        reason="shrinking scope",
        cluster="attacks-classic",
    )
    assert r["updated"] == 2


@pytest.mark.asyncio
async def test_bulk_reclassify_unknown_cluster(tmp_project: Path):
    await save_review_summary(summary="t", clusters=[{"topic": "a", "paper_ids": []}])
    r = await bulk_reclassify(new_status="rejected", reason="r", cluster="ghost")
    assert r["updated"] == 0
    assert "not found" in r["error"]


@pytest.mark.asyncio
async def test_bulk_reclassify_empty_filter(tmp_project: Path):
    await persist_papers([Paper(source="arxiv", source_id="1", title="P")])
    r = await bulk_reclassify(
        new_status="rejected",
        reason="test",
        current_status="approved",  # no papers match this filter
    )
    assert r["updated"] == 0


# ─── T15 — regenerate brief ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_brief_bundles_section_and_feedback(tmp_project: Path):
    await persist_papers(
        [Paper(source="openalex", source_id="1", title="P", year=2024, abstract="abs text")]
    )
    await save_outline([{"name": "intro", "target_words": 300, "paper_ids": [1]}])
    await approve_outline()
    await save_section("intro", "current draft text")

    r = await regenerate_section_brief("intro", feedback="please make it more critical")
    assert r["current"]["content"] == "current draft text"
    assert r["feedback"] == "please make it more critical"
    assert r["outline_entry"]["target_words"] == 300
    assert len(r["assigned_papers"]) == 1
    assert r["assigned_papers"][0]["abstract"] == "abs text"
    assert "instructions" in r


@pytest.mark.asyncio
async def test_regenerate_brief_missing_section_errors(tmp_project: Path):
    r = await regenerate_section_brief("nope", feedback="fix")
    assert "error" in r


# ─── T16 — export ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_bibtex_writes_file(tmp_project: Path):
    await persist_papers(
        [
            Paper(
                source="openalex",
                source_id="1",
                title="Paper A",
                authors=["Jane Doe"],
                year=2024,
                venue="ICML",
                doi="10.1/a",
            )
        ]
    )
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")

    r = await export_bibtex()
    path = Path(r["path"])
    assert path.exists()
    assert r["entries"] == 1
    content = path.read_text()
    assert "@article{doe2024paper," in content
    assert "doi = {10.1/a}" in content


@pytest.mark.asyncio
async def test_export_bibtex_custom_path(tmp_project: Path):
    await persist_papers([Paper(source="arxiv", source_id="1", title="P", year=2024)])
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")
    target = tmp_project / "custom.bib"
    r = await export_bibtex(output_path=str(target))
    assert Path(r["path"]) == target
    assert target.exists()


@pytest.mark.asyncio
async def test_export_ris_writes_file(tmp_project: Path):
    await persist_papers(
        [
            Paper(
                source="openalex",
                source_id="1",
                title="RIS Paper",
                authors=["Alice Smith", "Bob Jones"],
                year=2024,
                venue="Nature",
                doi="10.1/x",
                abstract="An abstract here.",
            )
        ]
    )
    await set_review_status([1], "approved", reason="r", reviewed_by="auto_high")

    r = await export_ris()
    path = Path(r["path"])
    assert path.exists()
    content = path.read_text()
    assert "TI  - RIS Paper" in content
    assert "AU  - Alice Smith" in content
    assert "AU  - Bob Jones" in content
    assert "PY  - 2024" in content
    assert "DO  - 10.1/x" in content
    assert "AB  - An abstract here." in content
    assert content.rstrip().endswith("ER  -")


@pytest.mark.asyncio
async def test_export_bibtex_empty_when_no_approved(tmp_project: Path):
    r = await export_bibtex()
    assert r["entries"] == 0
    # File should still be written (empty bibliography is a valid state).
    assert Path(r["path"]).exists()
