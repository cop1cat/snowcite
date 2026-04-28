"""Phase 1: notes / knowledge-graph tools."""

from pathlib import Path

import pytest

from snowcite.db import get_connection
from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.notes import (
    add_note,
    add_notes,
    delete_note,
    get_note_density,
    get_notes,
    link_notes,
    update_note,
)
from snowcite.tools.review import set_review_status


async def _seed_paper() -> int:
    res = await persist_papers([Paper(source="arxiv", source_id="a", title="A")])
    return res["new_ids"][0]


@pytest.mark.asyncio
async def test_add_note_per_paper_requires_paper_id(tmp_project: Path):
    r = await add_note(type="claim", text="something")
    assert "error" in r and "paper_id" in r["error"]


@pytest.mark.asyncio
async def test_add_note_cross_paper_rejects_paper_id(tmp_project: Path):
    pid = await _seed_paper()
    r = await add_note(type="gap", text="missing X", paper_id=pid)
    assert "error" in r and "cross-paper" in r["error"]


@pytest.mark.asyncio
async def test_add_note_and_fetch(tmp_project: Path):
    pid = await _seed_paper()
    r = await add_note(type="finding", text="Method beats baseline", paper_id=pid, cluster="bench")
    assert "id" in r
    rows = await get_notes(paper_id=pid)
    assert len(rows) == 1
    assert rows[0]["type"] == "finding"
    assert rows[0]["cluster"] == "bench"


@pytest.mark.asyncio
async def test_add_note_rejects_empty_text(tmp_project: Path):
    pid = await _seed_paper()
    r = await add_note(type="claim", text="   ", paper_id=pid)
    assert "error" in r


@pytest.mark.asyncio
async def test_add_notes_batch_partial_success(tmp_project: Path):
    pid = await _seed_paper()
    r = await add_notes(
        [
            {"type": "claim", "text": "ok", "paper_id": pid},
            {"type": "claim", "text": ""},  # empty text + missing paper_id
            {"type": "gap", "text": "missing"},  # cross-paper, valid
        ]
    )
    assert r["inserted"] == 2
    assert len(r["errors"]) == 1


@pytest.mark.asyncio
async def test_get_notes_filters(tmp_project: Path):
    pid = await _seed_paper()
    await add_note(type="claim", text="c1", paper_id=pid, cluster="A")
    await add_note(type="finding", text="f1", paper_id=pid, cluster="B")
    await add_note(type="gap", text="g1", cluster="A")

    assert len(await get_notes(cluster="A")) == 2
    assert len(await get_notes(type="finding")) == 1
    assert len(await get_notes(paper_id=pid)) == 2


@pytest.mark.asyncio
async def test_update_note(tmp_project: Path):
    pid = await _seed_paper()
    r = await add_note(type="claim", text="old", paper_id=pid)
    await update_note(note_id=r["id"], text="new", cluster="X")
    rows = await get_notes(paper_id=pid)
    assert rows[0]["text"] == "new"
    assert rows[0]["cluster"] == "X"


@pytest.mark.asyncio
async def test_update_note_type_swap_rejected_when_paper_id_mismatch(tmp_project: Path):
    pid = await _seed_paper()
    r = await add_note(type="claim", text="x", paper_id=pid)
    bad = await update_note(note_id=r["id"], type="gap")  # cross-paper but paper_id is set
    assert "error" in bad


@pytest.mark.asyncio
async def test_delete_note(tmp_project: Path):
    pid = await _seed_paper()
    r = await add_note(type="claim", text="x", paper_id=pid)
    res = await delete_note(note_id=r["id"])
    assert res["deleted"] == 1
    assert await get_notes(paper_id=pid) == []


@pytest.mark.asyncio
async def test_delete_paper_cascades_to_notes(tmp_project: Path):
    pid = await _seed_paper()
    await add_note(type="claim", text="x", paper_id=pid)
    async with get_connection() as conn:
        await conn.execute("DELETE FROM papers WHERE id = ?", (pid,))
        await conn.commit()
    assert await get_notes() == []


@pytest.mark.asyncio
async def test_link_notes(tmp_project: Path):
    pid = await _seed_paper()
    a = await add_note(type="claim", text="a", paper_id=pid)
    b = await add_note(type="gap", text="g")
    res = await link_notes(from_note_id=b["id"], to_note_id=a["id"], kind="derived_from")
    assert res["linked"] is True
    # idempotent
    again = await link_notes(from_note_id=b["id"], to_note_id=a["id"], kind="derived_from")
    assert again["linked"] is True


@pytest.mark.asyncio
async def test_set_review_status_inline_notes(tmp_project: Path):
    pid = await _seed_paper()
    res = await set_review_status(
        paper_ids=[pid],
        status="approved",
        reason="match",
        notes=[
            {"type": "claim", "text": "introduces foo", "cluster": "core"},
            {"type": "finding", "text": "+10% accuracy"},
        ],
    )
    assert res["updated"] == 1
    assert len(res["note_ids"]) == 2
    rows = await get_notes(paper_id=pid)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_set_review_status_inline_notes_rejects_multi_paper(tmp_project: Path):
    pid = await _seed_paper()
    res2 = await persist_papers([Paper(source="arxiv", source_id="b", title="B")])
    pid2 = res2["new_ids"][0]
    res = await set_review_status(
        paper_ids=[pid, pid2],
        status="approved",
        reason="match",
        notes=[{"type": "claim", "text": "x"}],
    )
    assert "error" in res
    assert res["updated"] == 0
    assert await get_notes() == []


@pytest.mark.asyncio
async def test_set_review_status_inline_notes_rejects_cross_paper_type(tmp_project: Path):
    pid = await _seed_paper()
    res = await set_review_status(
        paper_ids=[pid],
        status="approved",
        reason="m",
        notes=[{"type": "gap", "text": "x"}],
    )
    assert "error" in res


@pytest.mark.asyncio
async def test_get_note_density(tmp_project: Path):
    pid = await _seed_paper()
    await add_note(type="claim", text="c", paper_id=pid, cluster="A")
    await add_note(type="finding", text="f", paper_id=pid, cluster="A")
    await add_note(type="gap", text="g", cluster="B")
    d = await get_note_density()
    assert d["density"]["A"]["claim"] == 1
    assert d["density"]["A"]["finding"] == 1
    assert d["density"]["B"]["gap"] == 1
