"""Phase 4: section-scoped research."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from snowcite.db import get_connection
from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.research import (
    get_section_papers,
    link_paper_to_section,
    research_section,
    unlink_paper_from_section,
)
from snowcite.tools.sections import create_section, delete_section, update_section


def _fake_search_results(per_call: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Yield successive responses that the patched search_papers will return."""
    yield from per_call


@pytest.mark.asyncio
async def test_research_section_runs_per_query_and_links(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
):
    sec = await create_section(
        title="Methods",
        scope={"keywords": ["graph attention", "GAT"], "questions": ["what is sparse attention?"]},
    )
    # Pre-seed three papers to be returned as "newly discovered" by search.
    await persist_papers(
        [
            Paper(source="arxiv", source_id="x1", title="P1"),
            Paper(source="arxiv", source_id="x2", title="P2"),
            Paper(source="arxiv", source_id="x3", title="P3"),
        ]
    )

    responses = iter(
        [
            {"saved": 1, "duplicates": 0, "new_ids": [1], "titles": ["P1"]},
            {"saved": 1, "duplicates": 0, "new_ids": [2], "titles": ["P2"]},
            {"saved": 1, "duplicates": 0, "new_ids": [3], "titles": ["P3"]},
        ]
    )

    async def fake_search(**kwargs: Any) -> dict[str, Any]:
        return next(responses)

    monkeypatch.setattr("snowcite.tools.research.search_papers", fake_search)

    res = await research_section(section_id=sec["id"])
    assert res["total_new"] == 3
    assert len(res["queries"]) == 3
    queries_used = [q["query"] for q in res["queries"]]
    assert queries_used == ["graph attention", "GAT", "what is sparse attention?"]

    linked = await get_section_papers(section_id=sec["id"])
    assert {p["id"] for p in linked} == {1, 2, 3}
    assert all(p["via_query"] for p in linked)


@pytest.mark.asyncio
async def test_research_section_no_scope(tmp_project: Path):
    sec = await create_section(title="Empty")
    res = await research_section(section_id=sec["id"])
    assert "error" in res


@pytest.mark.asyncio
async def test_research_section_missing(tmp_project: Path):
    res = await research_section(section_id=99999)
    assert "error" in res


@pytest.mark.asyncio
async def test_research_section_propagates_failed_sources(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
):
    sec = await create_section(title="X", scope={"keywords": ["k"]})

    async def fake_search(**kwargs: Any) -> dict[str, Any]:
        return {"saved": 0, "duplicates": 0, "new_ids": [], "failed_sources": ["arxiv"]}

    monkeypatch.setattr("snowcite.tools.research.search_papers", fake_search)
    res = await research_section(section_id=sec["id"])
    assert res["failed_sources"] == ["arxiv"]


@pytest.mark.asyncio
async def test_link_and_unlink_paper(tmp_project: Path):
    sec = await create_section(title="X")
    await persist_papers([Paper(source="arxiv", source_id="a", title="A")])

    res = await link_paper_to_section(paper_id=1, section_id=sec["id"], via_query="manual")
    assert res["linked"] is True
    # idempotent
    again = await link_paper_to_section(paper_id=1, section_id=sec["id"])
    assert again["linked"] is True

    linked = await get_section_papers(section_id=sec["id"])
    assert len(linked) == 1
    assert linked[0]["via_query"] == "manual"

    res = await unlink_paper_from_section(paper_id=1, section_id=sec["id"])
    assert res["deleted"] == 1
    assert await get_section_papers(section_id=sec["id"]) == []


@pytest.mark.asyncio
async def test_link_paper_validates_both_ends(tmp_project: Path):
    sec = await create_section(title="X")
    bad_paper = await link_paper_to_section(paper_id=99999, section_id=sec["id"])
    assert "error" in bad_paper

    await persist_papers([Paper(source="arxiv", source_id="a", title="A")])
    bad_section = await link_paper_to_section(paper_id=1, section_id=99999)
    assert "error" in bad_section


@pytest.mark.asyncio
async def test_section_delete_cascades_links(tmp_project: Path):
    sec = await create_section(title="X")
    await persist_papers([Paper(source="arxiv", source_id="a", title="A")])
    await link_paper_to_section(paper_id=1, section_id=sec["id"])

    await update_section(section_id=sec["id"], title="Renamed")
    await delete_section(section_id=sec["id"])
    async with get_connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM paper_section_links")
        assert (await cur.fetchone())[0] == 0
