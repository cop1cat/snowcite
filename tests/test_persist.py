"""Insert / dedup roundtrip — ensures the shared _persist_papers core is correct."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper


def _mk(source: str, sid: str, title: str, *, doi: str | None = None) -> Paper:
    return Paper(source=source, source_id=sid, title=title, doi=doi)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_persist_empty_is_noop(tmp_project: Path):
    r = await persist_papers([])
    assert r == {"saved": 0, "duplicates": 0, "new_ids": [], "new_titles": []}


@pytest.mark.asyncio
async def test_persist_fresh_inserts(tmp_project: Path):
    papers = [_mk("arxiv", "1", "Paper A"), _mk("arxiv", "2", "Paper B")]
    r = await persist_papers(papers)
    assert r["saved"] == 2
    assert r["duplicates"] == 0
    assert len(r["new_ids"]) == 2
    assert r["new_titles"] == ["Paper A", "Paper B"]


@pytest.mark.asyncio
async def test_persist_doi_dedup(tmp_project: Path):
    # Same DOI → second insert is a duplicate even with different source_id.
    first = _mk("arxiv", "1", "Paper A", doi="10.1/foo")
    second = _mk("semantic_scholar", "X", "Paper A copy", doi="10.1/foo")

    r1 = await persist_papers([first])
    r2 = await persist_papers([second])

    assert r1["saved"] == 1
    assert r2["saved"] == 0
    assert r2["duplicates"] == 1


@pytest.mark.asyncio
async def test_persist_title_dedup_when_no_doi(tmp_project: Path):
    first = _mk("arxiv", "1", "A fancy title")
    second = _mk("openalex", "Y", "a fancy title!")  # punctuation/case variant

    r1 = await persist_papers([first])
    r2 = await persist_papers([second])

    assert r1["saved"] == 1
    assert r2["saved"] == 0
    assert r2["duplicates"] == 1


@pytest.mark.asyncio
async def test_persist_titles_aligned_with_ids(tmp_project: Path):
    papers = [_mk("arxiv", str(i), f"Title {i}") for i in range(5)]
    # Inject one duplicate mid-stream.
    papers.insert(2, _mk("arxiv", "0", "Title 0"))  # same source+source_id → dup

    r = await persist_papers(papers)
    assert len(r["new_ids"]) == r["saved"]
    assert len(r["new_titles"]) == r["saved"]
    # Saved titles are the 5 fresh ones, in submission order (not the duplicate).
    assert r["new_titles"] == [f"Title {i}" for i in range(5)]
