"""Phase 3: sections as entities."""

import json
from pathlib import Path

import pytest

from snowcite.db import get_connection
from snowcite.tools.sections import (
    bulk_create_sections,
    create_section,
    delete_section,
    get_outline_inputs,
    get_section,
    list_sections,
    update_section,
)


@pytest.mark.asyncio
async def test_create_section_minimal(tmp_project: Path):
    r = await create_section(title="Intro")
    assert "id" in r
    s = await get_section(r["id"])
    assert s["title"] == "Intro"
    assert s["status"] == "outline"
    assert s["scope"] == {"clusters": [], "keywords": [], "questions": []}
    assert s["position"] == 0
    assert s["severity"] == {"blockers": 0, "should_fix": 0, "nits": 0}


@pytest.mark.asyncio
async def test_create_section_normalises_scope(tmp_project: Path):
    r = await create_section(
        title="X",
        scope={"clusters": ["A"], "keywords": ["k"], "questions": ["q?"], "garbage": "drop"},
    )
    s = await get_section(r["id"])
    assert s["scope"] == {"clusters": ["A"], "keywords": ["k"], "questions": ["q?"]}


@pytest.mark.asyncio
async def test_create_section_rejects_empty_title(tmp_project: Path):
    r = await create_section(title="   ")
    assert "error" in r


@pytest.mark.asyncio
async def test_position_auto_increments_among_siblings(tmp_project: Path):
    a = await create_section(title="A")
    b = await create_section(title="B")
    c = await create_section(title="C", parent_id=a["id"])
    items = await list_sections()
    by_id = {x["id"]: x for x in items}
    assert by_id[a["id"]]["position"] == 0
    assert by_id[b["id"]]["position"] == 1
    assert by_id[c["id"]]["position"] == 0  # first child


@pytest.mark.asyncio
async def test_bulk_create_packs_positions(tmp_project: Path):
    res = await bulk_create_sections(
        [
            {"title": "A"},
            {"title": "B"},
            {"title": ""},  # error
            {"title": "C"},
        ]
    )
    assert res["inserted"] == 3
    assert len(res["errors"]) == 1
    items = await list_sections()
    positions = [x["position"] for x in items]
    assert positions == [0, 1, 2]


@pytest.mark.asyncio
async def test_update_section_patches_fields(tmp_project: Path):
    r = await create_section(title="X")
    await update_section(
        section_id=r["id"],
        title="Y",
        draft="prose",
        status="drafting",
        scope={"clusters": ["c1"]},
    )
    s = await get_section(r["id"])
    assert s["title"] == "Y"
    assert s["draft"] == "prose"
    assert s["status"] == "drafting"
    assert s["scope"]["clusters"] == ["c1"]


@pytest.mark.asyncio
async def test_update_section_rejects_self_parent(tmp_project: Path):
    r = await create_section(title="X")
    bad = await update_section(section_id=r["id"], parent_id=r["id"])
    assert "error" in bad


@pytest.mark.asyncio
async def test_update_section_no_fields(tmp_project: Path):
    r = await create_section(title="X")
    bad = await update_section(section_id=r["id"])
    assert "error" in bad


@pytest.mark.asyncio
async def test_update_missing_section(tmp_project: Path):
    bad = await update_section(section_id=99999, title="X")
    assert "error" in bad


@pytest.mark.asyncio
async def test_delete_cascades_to_children(tmp_project: Path):
    a = await create_section(title="A")
    await create_section(title="A.1", parent_id=a["id"])
    await create_section(title="A.2", parent_id=a["id"])
    res = await delete_section(section_id=a["id"])
    assert res["deleted"] == 1
    assert await list_sections() == []


@pytest.mark.asyncio
async def test_get_outline_inputs(tmp_project: Path):
    async with get_connection() as conn:
        await conn.execute("INSERT INTO thesis (id, content) VALUES (1, 'thesis text')")
        await conn.execute(
            "INSERT INTO review_summary "
            "(id, summary, clusters_json, counts_snapshot_json, stale) "
            "VALUES (1, 's', ?, '{}', 0)",
            (json.dumps([{"topic": "T1", "paper_ids": [], "count": 0}]),),
        )
        await conn.execute("INSERT INTO review_criteria (criteria_text) VALUES ('include foo')")
        await conn.commit()
    r = await get_outline_inputs()
    assert r["thesis"] == "thesis text"
    assert r["clusters"][0]["topic"] == "T1"
    assert r["criteria"] == "include foo"


@pytest.mark.asyncio
async def test_get_outline_inputs_empty(tmp_project: Path):
    r = await get_outline_inputs()
    assert r == {"thesis": None, "clusters": [], "criteria": None}
