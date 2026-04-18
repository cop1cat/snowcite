"""Review tools — include_abstracts flag drives the T1 context-hygiene contract."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.review import get_unreviewed_papers


@pytest.mark.asyncio
async def test_get_unreviewed_omits_abstract_by_default(tmp_project: Path):
    await persist_papers([Paper(source="arxiv", source_id="x", title="T", abstract="ABS")])
    rows = await get_unreviewed_papers(limit=10)
    assert len(rows) == 1
    # Compact mode: abstract field is removed entirely, not just nulled.
    assert "abstract" not in rows[0]


@pytest.mark.asyncio
async def test_get_unreviewed_includes_abstract_when_requested(tmp_project: Path):
    await persist_papers([Paper(source="arxiv", source_id="x", title="T", abstract="ABS")])
    rows = await get_unreviewed_papers(limit=10, include_abstracts=True)
    assert rows[0]["abstract"] == "ABS"
