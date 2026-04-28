"""Phase 5: critique / revise loop."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.critique import (
    get_section_critique_inputs,
    record_section_critique,
    revise_section,
)
from snowcite.tools.notes import add_note
from snowcite.tools.research import link_paper_to_section
from snowcite.tools.sections import create_section, get_section


@pytest.mark.asyncio
async def test_get_section_critique_inputs_bundles_data(tmp_project: Path):
    sec = await create_section(title="Methods", scope={"clusters": ["A", "B"]})
    await persist_papers([Paper(source="arxiv", source_id="x", title="P", year=2024)])
    await link_paper_to_section(paper_id=1, section_id=sec["id"])
    await add_note(type="claim", text="c1", paper_id=1, cluster="A")
    await add_note(type="finding", text="f1", paper_id=1, cluster="A")
    await add_note(type="claim", text="other", paper_id=1, cluster="C")  # outside scope

    res = await get_section_critique_inputs(section_id=sec["id"])
    assert res["section"]["id"] == sec["id"]
    # Only A/B notes; C-cluster note is excluded.
    assert len(res["notes"]) == 2
    assert all(n["cluster"] in {"A", "B"} for n in res["notes"])
    assert len(res["linked_papers"]) == 1


@pytest.mark.asyncio
async def test_get_section_critique_inputs_no_clusters_returns_empty_notes(tmp_project: Path):
    sec = await create_section(title="X")  # no clusters in scope
    res = await get_section_critique_inputs(section_id=sec["id"])
    assert res["notes"] == []


@pytest.mark.asyncio
async def test_record_critique_counts_and_stops_when_no_blockers(tmp_project: Path):
    sec = await create_section(title="X")
    res = await record_section_critique(
        section_id=sec["id"],
        issues=[
            {"severity": "should_fix", "type": "missing_evidence", "text": "x"},
            {"severity": "nit", "type": "style", "text": "y"},
        ],
    )
    assert res["should_stop"] is True
    assert res["reason"] == "no blockers remaining"
    assert res["severity"] == {"blockers": 0, "should_fix": 1, "nits": 1}

    s = await get_section(sec["id"])
    assert s["status"] == "critiqued"
    assert s["critique_iterations"] == 1


@pytest.mark.asyncio
async def test_record_critique_continues_when_blockers_remain(tmp_project: Path):
    sec = await create_section(title="X")
    res = await record_section_critique(
        section_id=sec["id"],
        issues=[{"severity": "blocker", "type": "unsupported_claim", "text": "x"}],
    )
    assert res["should_stop"] is False
    assert res["severity"]["blockers"] == 1


@pytest.mark.asyncio
async def test_record_critique_stops_after_max_iterations(tmp_project: Path):
    sec = await create_section(title="X")
    issues = [{"severity": "blocker", "type": "x", "text": "x"}]
    r1 = await record_section_critique(section_id=sec["id"], issues=issues)
    assert r1["should_stop"] is False
    r2 = await record_section_critique(section_id=sec["id"], issues=issues)
    assert r2["should_stop"] is True
    assert "max critique iterations" in r2["reason"]


@pytest.mark.asyncio
async def test_record_critique_invalid_severity(tmp_project: Path):
    sec = await create_section(title="X")
    bad = await record_section_critique(
        section_id=sec["id"],
        issues=[{"severity": "wat", "type": "x", "text": "x"}],
    )
    assert "error" in bad


@pytest.mark.asyncio
async def test_record_critique_missing_section(tmp_project: Path):
    bad = await record_section_critique(section_id=99999, issues=[])
    assert "error" in bad


@pytest.mark.asyncio
async def test_revise_section_resets_state(tmp_project: Path):
    sec = await create_section(title="X")
    await record_section_critique(
        section_id=sec["id"],
        issues=[
            {"severity": "blocker", "type": "x", "text": "x"},
            {"severity": "nit", "type": "y", "text": "y"},
        ],
    )
    assert (await get_section(sec["id"]))["critique_iterations"] == 1

    res = await revise_section(section_id=sec["id"], new_draft="rewritten prose")
    assert res["status"] == "drafting"
    s = await get_section(sec["id"])
    assert s["draft"] == "rewritten prose"
    assert s["severity"] == {"blockers": 0, "should_fix": 0, "nits": 0}
    assert s["critique_iterations"] == 0


@pytest.mark.asyncio
async def test_revise_section_mark_done(tmp_project: Path):
    sec = await create_section(title="X")
    res = await revise_section(section_id=sec["id"], new_draft="final", mark_done=True)
    assert res["status"] == "done"
    s = await get_section(sec["id"])
    assert s["status"] == "done"


@pytest.mark.asyncio
async def test_revise_missing_section(tmp_project: Path):
    bad = await revise_section(section_id=99999, new_draft="x")
    assert "error" in bad
