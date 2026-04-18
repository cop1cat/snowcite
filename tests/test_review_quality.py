"""T17/T19: prepare_section_for_review packs everything a review subagent needs
into one call — section text, outline entry, assigned paper metadata + abstracts,
neighbouring section names, and project context."""

from pathlib import Path

import pytest

from snowcite.persistence import persist_papers
from snowcite.sources.base import Paper
from snowcite.tools.init import init_project
from snowcite.tools.review_quality import prepare_section_for_review
from snowcite.tools.writing import approve_outline, save_outline, save_section


@pytest.mark.asyncio
async def test_prepare_missing_section_returns_error(tmp_project: Path):
    r = await prepare_section_for_review("does_not_exist")
    assert "error" in r


@pytest.mark.asyncio
async def test_prepare_bundles_section_and_assigned_papers(tmp_project: Path):
    # Seed two papers, approve one, reference it from the outline.
    await persist_papers(
        [
            Paper(
                source="openalex",
                source_id="1",
                title="Paper A",
                authors=["Alice Smith"],
                year=2023,
                abstract="Abstract of paper A.",
                doi="10.1/a",
            ),
            Paper(
                source="openalex",
                source_id="2",
                title="Paper B",
                authors=["Bob Jones"],
                year=2024,
                abstract="Abstract of paper B.",
                doi="10.2/b",
            ),
        ]
    )
    await save_outline(
        [
            {"name": "intro", "target_words": 300, "paper_ids": [1]},
            {"name": "methods", "target_words": 500, "paper_ids": [2]},
        ]
    )
    await approve_outline()
    await save_section("intro", "Paper A argues X. See Smith 2023.")
    await save_section("methods", "Paper B argues Y.")

    r = await prepare_section_for_review("intro")

    assert r["section"]["name"] == "intro"
    assert "Paper A argues X" in r["section"]["content"]
    assert r["outline_entry"]["target_words"] == 300
    assert r["outline_entry"]["paper_ids"] == [1]

    assert len(r["assigned_papers"]) == 1
    assigned = r["assigned_papers"][0]
    assert assigned["title"] == "Paper A"
    assert assigned["abstract"] == "Abstract of paper A."
    assert assigned["doi"] == "10.1/a"

    # Neighbour sections listed, but not with their bodies.
    assert "methods" in r["other_sections"]


@pytest.mark.asyncio
async def test_prepare_can_omit_abstracts(tmp_project: Path):
    await persist_papers(
        [
            Paper(
                source="openalex",
                source_id="1",
                title="P",
                year=2024,
                abstract="Long abstract...",
            )
        ]
    )
    await save_outline([{"name": "intro", "target_words": 100, "paper_ids": [1]}])
    await approve_outline()
    await save_section("intro", "text")

    r = await prepare_section_for_review("intro", include_paper_abstracts=False)
    assert r["assigned_papers"]
    assert "abstract" not in r["assigned_papers"][0]


@pytest.mark.asyncio
async def test_prepare_includes_project_context(tmp_project: Path, monkeypatch):
    # Set metadata so project_context carries language/standard/etc.
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    await init_project(
        metadata={
            "language": "ru",
            "standard": "gost",
            "discipline": "cs",
            "review_strictness": "phd_committee",
            "backend": "typst",
        }
    )
    await save_section("intro", "text")

    r = await prepare_section_for_review("intro")
    ctx = r["project_context"]
    assert ctx["language"] == "ru"
    assert ctx["review_strictness"] == "phd_committee"


# ─── Agent template generation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_project_writes_both_agents(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    r = await init_project(metadata={"language": "en"})

    # init_project should have written both agents on fresh project.
    written = r["agents_written"]
    assert "academic-reviewer.md" in written
    assert "humanizer.md" in written

    ar = tmp_path / ".claude" / "agents" / "academic-reviewer.md"
    hm = tmp_path / ".claude" / "agents" / "humanizer.md"
    assert ar.exists() and hm.exists()

    # Frontmatter + tool scoping rendered correctly.
    ar_text = ar.read_text()
    assert "name: academic-reviewer" in ar_text
    assert "mcp__snowcite__prepare_section_for_review" in ar_text
    hm_text = hm.read_text()
    assert "name: humanizer" in hm_text
    assert "Read" in hm_text


@pytest.mark.asyncio
async def test_init_does_not_overwrite_existing_agents_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    # First init creates both files.
    await init_project(metadata={"language": "en"})

    ar = tmp_path / ".claude" / "agents" / "academic-reviewer.md"
    ar.write_text("USER EDIT — do not clobber")

    # Second init should leave it alone.
    r = await init_project(metadata={"language": "en"}, update=True)
    assert "academic-reviewer.md" not in r["agents_written"]
    assert ar.read_text() == "USER EDIT — do not clobber"


@pytest.mark.asyncio
async def test_init_update_agents_flag_overwrites(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    await init_project(metadata={"language": "en"})
    ar = tmp_path / ".claude" / "agents" / "academic-reviewer.md"
    ar.write_text("old content")

    r = await init_project(metadata={"language": "en"}, update=True, update_agents=True)
    assert "academic-reviewer.md" in r["agents_written"]
    # Template content back in place.
    assert "name: academic-reviewer" in ar.read_text()
