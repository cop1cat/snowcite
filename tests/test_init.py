"""T4: full init_project onboarding — metadata, CLAUDE.md, settings diff."""

import json
from pathlib import Path

import pytest

from snowcite.db import _initialized
from snowcite.projects import create_project_dir
from snowcite.tools.init import (
    apply_settings_diff,
    get_project_metadata,
    init_project,
)


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh cwd with no .snowcite/ and no env override — the init_project target."""
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    _initialized.clear()
    return tmp_path


@pytest.mark.asyncio
async def test_init_creates_claude_md_and_dirs(isolated_cwd: Path):
    result = await init_project(
        metadata={
            "author": "Jane Doe",
            "language": "ru",
            "discipline": "cs",
            "standard": "gost",
            "backend": "typst",
        }
    )
    assert Path(result["claude_md_path"]).exists()
    assert (isolated_cwd / ".snowcite" / "papers.db").exists()
    assert (isolated_cwd / ".snowcite" / "cache").is_dir()

    text = Path(result["claude_md_path"]).read_text()
    assert "Jane Doe" in text
    assert "Discipline" in text  # rendered section
    assert "typst" in text


@pytest.mark.asyncio
async def test_init_persists_metadata_and_reads_back(isolated_cwd: Path):
    await init_project(
        metadata={
            "author": "Alice",
            "institution": "MSU",
            "year": 2026,
            "discipline": "medicine",
            "standard": "vancouver",
            "backend": "latex",
            "language": "en",
        }
    )
    md = await get_project_metadata()
    assert md["author"] == "Alice"
    assert md["institution"] == "MSU"
    assert md["year"] == 2026
    assert md["discipline"] == "medicine"


@pytest.mark.asyncio
async def test_init_update_preserves_existing_metadata(isolated_cwd: Path):
    await init_project(metadata={"author": "Alice", "institution": "MSU"})
    await init_project(metadata={"discipline": "medicine"}, update=True)
    md = await get_project_metadata()
    # Old fields survived the update.
    assert md["author"] == "Alice"
    assert md["institution"] == "MSU"
    # New field landed.
    assert md["discipline"] == "medicine"


@pytest.mark.asyncio
async def test_init_without_metadata_keeps_existing(isolated_cwd: Path):
    await init_project(metadata={"author": "Alice"})
    # No metadata + no update — just a rerun. Should not wipe the row.
    await init_project()
    md = await get_project_metadata()
    assert md["author"] == "Alice"


@pytest.mark.asyncio
async def test_settings_diff_create_when_missing(isolated_cwd: Path):
    result = await init_project(metadata={"author": "A"})
    diff = result["settings_diff"]
    assert diff["exists"] is False
    assert diff["action_required"] == "create"
    assert "mcp__snowcite__*" in diff["missing_entries"]


@pytest.mark.asyncio
async def test_settings_diff_ask_user_when_partial(isolated_cwd: Path):
    # Pre-create settings.json with only one entry.
    claude_dir = isolated_cwd / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["mcp__snowcite__*"]}})
    )

    result = await init_project(metadata={"author": "A"})
    diff = result["settings_diff"]
    assert diff["exists"] is True
    assert diff["action_required"] == "ask_user"
    # Snowcite's default allowlist is larger than what the user pre-seeded.
    assert len(diff["missing_entries"]) > 0
    assert "mcp__snowcite__*" in diff["existing_entries"]


@pytest.mark.asyncio
async def test_apply_settings_diff_merge(isolated_cwd: Path):
    create_project_dir()
    (isolated_cwd / ".claude").mkdir()
    (isolated_cwd / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["WebSearch"]}}, indent=2)
    )

    r = await apply_settings_diff("merge")
    assert r["applied"] is True
    content = json.loads((isolated_cwd / ".claude" / "settings.json").read_text())
    allow = content["permissions"]["allow"]
    assert "WebSearch" in allow  # preserved
    assert "mcp__snowcite__*" in allow  # added


@pytest.mark.asyncio
async def test_apply_settings_diff_overwrite_backs_up(isolated_cwd: Path):
    create_project_dir()
    (isolated_cwd / ".claude").mkdir()
    orig = isolated_cwd / ".claude" / "settings.json"
    orig.write_text("custom content, definitely not json but whatever")

    r = await apply_settings_diff("overwrite")
    assert r["applied"] is True
    assert (isolated_cwd / ".claude" / "settings.json.bak").exists()
    assert orig.exists()  # new one in place
    content = json.loads(orig.read_text())
    assert "mcp__snowcite__*" in content["permissions"]["allow"]


@pytest.mark.asyncio
async def test_apply_settings_diff_skip(isolated_cwd: Path):
    create_project_dir()
    r = await apply_settings_diff("skip")
    assert r["applied"] is False


@pytest.mark.asyncio
async def test_claude_md_contains_language_and_backend(isolated_cwd: Path):
    result = await init_project(metadata={"language": "fr", "backend": "latex", "standard": "apa"})
    text = Path(result["claude_md_path"]).read_text()
    assert "fr" in text
    assert "latex" in text
    assert "apa" in text
