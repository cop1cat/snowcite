"""Phase 2: cross-paper synthesis."""

import json
from pathlib import Path

import pytest

from snowcite.db import get_connection
from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.notes import add_note
from snowcite.tools.synthesis import (
    add_synthesis_note,
    find_gaps,
    get_cluster_notes,
)


async def _seed_two_papers() -> tuple[int, int]:
    res = await persist_papers(
        [
            Paper(source="arxiv", source_id="a", title="A", year=2023),
            Paper(source="arxiv", source_id="b", title="B", year=2024),
        ]
    )
    return res["new_ids"][0], res["new_ids"][1]


@pytest.mark.asyncio
async def test_get_cluster_notes_groups_by_paper(tmp_project: Path):
    p1, p2 = await _seed_two_papers()
    await add_note(type="claim", text="c1", paper_id=p1, cluster="X")
    await add_note(type="finding", text="f1", paper_id=p1, cluster="X")
    await add_note(type="claim", text="c2", paper_id=p2, cluster="X")
    await add_note(type="claim", text="other", paper_id=p1, cluster="Y")

    view = await get_cluster_notes(cluster="X")
    assert view["cluster"] == "X"
    assert len(view["papers"]) == 2
    p1_bucket = next(p for p in view["papers"] if p["paper_id"] == p1)
    assert len(p1_bucket["notes"]) == 2
    assert p1_bucket["title"] == "A"
    assert view["counts"]["claim"] == 2
    assert view["cross_paper"] == []


@pytest.mark.asyncio
async def test_add_synthesis_note_atomic(tmp_project: Path):
    p1, p2 = await _seed_two_papers()
    n1 = await add_note(type="limitation", text="small dataset", paper_id=p1, cluster="X")
    n2 = await add_note(type="limitation", text="single domain", paper_id=p2, cluster="X")

    res = await add_synthesis_note(
        cluster="X",
        type="gap",
        text="No cross-domain evaluation in the cluster",
        derived_from_note_ids=[n1["id"], n2["id"]],
    )
    assert "id" in res and res["links"] == 2

    view = await get_cluster_notes(cluster="X")
    assert len(view["cross_paper"]) == 1
    assert sorted(view["cross_paper"][0]["derived_from"]) == sorted([n1["id"], n2["id"]])


@pytest.mark.asyncio
async def test_add_synthesis_note_rejects_per_paper_type(tmp_project: Path):
    p1, _ = await _seed_two_papers()
    n = await add_note(type="claim", text="x", paper_id=p1, cluster="X")
    res = await add_synthesis_note(
        cluster="X", type="claim", text="x", derived_from_note_ids=[n["id"]]
    )
    assert "error" in res


@pytest.mark.asyncio
async def test_add_synthesis_note_requires_sources(tmp_project: Path):
    res = await add_synthesis_note(cluster="X", type="gap", text="x", derived_from_note_ids=[])
    assert "error" in res and "derived_from" in res["error"]


@pytest.mark.asyncio
async def test_add_synthesis_note_rejects_missing_or_cross_paper_sources(tmp_project: Path):
    p1, _ = await _seed_two_papers()
    n_per = await add_note(type="claim", text="x", paper_id=p1, cluster="X")
    cross = await add_synthesis_note(
        cluster="X", type="gap", text="g", derived_from_note_ids=[n_per["id"]]
    )

    # Missing id
    miss = await add_synthesis_note(
        cluster="X", type="gap", text="g2", derived_from_note_ids=[99999]
    )
    assert "error" in miss

    # Pointing at a cross-paper note
    bad = await add_synthesis_note(
        cluster="X", type="gap", text="g3", derived_from_note_ids=[cross["id"]]
    )
    assert "error" in bad and "cross-paper" in bad["error"]


@pytest.mark.asyncio
async def test_find_gaps_thin_cluster(tmp_project: Path):
    p1, _ = await _seed_two_papers()
    await add_note(type="claim", text="c", paper_id=p1, cluster="X")
    res = await find_gaps()
    flags = {f["cluster"]: f["flags"] for f in res["findings"]}
    assert "thin" in flags["X"]


@pytest.mark.asyncio
async def test_find_gaps_unsynthesised(tmp_project: Path):
    p1, p2 = await _seed_two_papers()
    # Three per-paper notes including a limitation, no cross-paper gap → unsynthesised.
    await add_note(type="claim", text="a", paper_id=p1, cluster="X")
    await add_note(type="finding", text="b", paper_id=p1, cluster="X")
    await add_note(type="limitation", text="lim", paper_id=p2, cluster="X")
    res = await find_gaps(cluster="X")
    flags = res["findings"][0]["flags"]
    assert "unsynthesised" in flags
    assert "thin" not in flags


@pytest.mark.asyncio
async def test_find_gaps_unanchored_contradiction(tmp_project: Path):
    # Create a contradiction note without sources by going through the DB —
    # add_synthesis_note enforces sources, so the unanchored case can only
    # arise from older data or manual edits. We simulate it.
    p1, p2 = await _seed_two_papers()
    await add_note(type="claim", text="a", paper_id=p1, cluster="X")
    await add_note(type="finding", text="b", paper_id=p1, cluster="X")
    await add_note(type="claim", text="c", paper_id=p2, cluster="X")
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO notes (paper_id, cluster, type, text) "
            "VALUES (NULL, 'X', 'contradiction', 'A vs B')"
        )
        await conn.commit()
    res = await find_gaps(cluster="X")
    flags = res["findings"][0]["flags"]
    assert "unresolved_contradiction" in flags


@pytest.mark.asyncio
async def test_find_gaps_unknown_cluster_in_summary(tmp_project: Path):
    p1, _ = await _seed_two_papers()
    await add_note(type="claim", text="x", paper_id=p1, cluster="typo_cluster")
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO review_summary "
            "(id, summary, clusters_json, counts_snapshot_json, stale) "
            "VALUES (1, '', ?, ?, 0)",
            (json.dumps([{"topic": "real_cluster", "paper_ids": [p1], "count": 1}]), "{}"),
        )
        await conn.commit()
    res = await find_gaps()
    assert "typo_cluster" in res["unknown_clusters_in_summary"]
