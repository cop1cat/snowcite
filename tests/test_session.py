"""T26: session state phase inference + next-action hints."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.review import set_review_criteria, set_review_status
from snowcite.tools.session import get_session_state
from snowcite.tools.writing import (
    approve_outline,
    approve_skeleton,
    polish_section,
    save_outline,
    save_section,
    save_skeleton,
)


@pytest.mark.asyncio
async def test_no_project_returns_not_started(tmp_path: Path, monkeypatch):
    """With no active project, session state degrades gracefully."""
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    r = await get_session_state()
    assert r["phase"] == "not_started"
    assert r["project_active"] is False
    assert "init_project" in r["next_action"]


@pytest.mark.asyncio
async def test_phase_not_started_on_fresh_project(tmp_project: Path):
    r = await get_session_state()
    assert r["phase"] == "not_started"
    assert r["project_active"] is True
    assert r["counts"]["papers_total"] == 0


@pytest.mark.asyncio
async def test_phase_criteria_set_after_setting_criteria(tmp_project: Path):
    await set_review_criteria("Include papers about X. Exclude Y.")
    r = await get_session_state()
    assert r["phase"] == "criteria_set"


@pytest.mark.asyncio
async def test_phase_reviewing_with_unreviewed_papers(tmp_project: Path):
    await set_review_criteria("...")
    await persist_papers(
        [
            Paper(source="arxiv", source_id="1", title="P"),
            Paper(source="arxiv", source_id="2", title="Q"),
        ]
    )
    r = await get_session_state()
    assert r["phase"] == "reviewing"


@pytest.mark.asyncio
async def test_phase_snowballing_after_all_reviewed(tmp_project: Path):
    await persist_papers(
        [
            Paper(source="arxiv", source_id="1", title="P"),
            Paper(source="arxiv", source_id="2", title="Q"),
        ]
    )
    await set_review_status([1, 2], "approved", reason="r", reviewed_by="auto_high")
    r = await get_session_state()
    assert r["phase"] == "snowballing"


@pytest.mark.asyncio
async def test_phase_outline_proposed_then_approved(tmp_project: Path):
    await save_outline([{"name": "intro", "target_words": 100}])
    r = await get_session_state()
    assert r["phase"] == "outline_proposed"
    assert r["outline"]["exists"] is True
    assert r["outline"]["approved"] is False

    await approve_outline()
    r = await get_session_state()
    assert r["phase"] == "outline_approved"


@pytest.mark.asyncio
async def test_phase_skeleton_approved(tmp_project: Path):
    await save_outline([{"name": "intro", "target_words": 100}])
    await approve_outline()
    await save_skeleton([{"name": "intro", "draft": "..."}])
    await approve_skeleton()
    r = await get_session_state()
    assert r["phase"] == "skeleton_approved"


@pytest.mark.asyncio
async def test_phase_writing_has_unpolished_section(tmp_project: Path):
    await save_section("intro", "draft text")
    r = await get_session_state()
    assert r["phase"] == "writing"
    assert r["counts"]["sections_written"] == 1
    assert r["counts"]["sections_polished"] == 0


@pytest.mark.asyncio
async def test_phase_polishing_when_all_sections_polished(tmp_project: Path):
    await save_section("intro", "draft")
    await polish_section("intro", "polished")
    r = await get_session_state()
    assert r["phase"] == "polishing"
    assert r["counts"]["sections_polished"] == 1


@pytest.mark.asyncio
async def test_last_actions_reflect_review_history(tmp_project: Path):
    await persist_papers([Paper(source="arxiv", source_id="x", title="T")])
    await set_review_status([1], "approved", reason="matches X", reviewed_by="auto_high")
    r = await get_session_state()
    assert len(r["last_actions"]) == 1
    a = r["last_actions"][0]
    assert a["paper_id"] == 1
    assert a["new_status"] == "approved"
    assert a["old_status"] == "unreviewed"
    assert a["reason"] == "matches X"
