"""Project resolver — cwd walk-up, migration, env override."""

from pathlib import Path

import pytest

from snowcite.projects import (
    NoProjectError,
    create_project_dir,
    find_project_root,
    migrate_legacy_db,
    require_project_root,
)


def test_find_project_root_none_when_no_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert find_project_root() is None


def test_find_project_root_walks_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    create_project_dir(tmp_path)
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    root = find_project_root()
    assert root is not None and root.resolve() == tmp_path.resolve()


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    create_project_dir(tmp_path)
    unrelated = tmp_path.parent / "unrelated"
    unrelated.mkdir(exist_ok=True)
    monkeypatch.chdir(unrelated)
    monkeypatch.setenv("SNOWCITE_PROJECT_ROOT", str(tmp_path))
    assert find_project_root() == tmp_path.resolve()


def test_env_override_ignored_without_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """SNOWCITE_PROJECT_ROOT pointing at a dir that has no .snowcite/ means no project."""
    monkeypatch.setenv("SNOWCITE_PROJECT_ROOT", str(tmp_path))
    assert find_project_root() is None


def test_require_raises_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SNOWCITE_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(NoProjectError):
        require_project_root()


def test_migrate_legacy_moves_file(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    legacy = data_dir / "papers.db"
    legacy.write_bytes(b"not really sqlite but that is fine for the move test")

    migrated = migrate_legacy_db(tmp_path)

    assert migrated is True
    assert not legacy.exists()
    assert (tmp_path / ".snowcite" / "papers.db").exists()


def test_migrate_legacy_noop_when_target_exists(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "papers.db").write_bytes(b"legacy")
    (tmp_path / ".snowcite").mkdir()
    (tmp_path / ".snowcite" / "papers.db").write_bytes(b"existing")

    migrated = migrate_legacy_db(tmp_path)
    assert migrated is False
    # Neither file got clobbered.
    assert (tmp_path / "data" / "papers.db").read_bytes() == b"legacy"
    assert (tmp_path / ".snowcite" / "papers.db").read_bytes() == b"existing"


def test_migrate_legacy_noop_when_no_legacy(tmp_path: Path):
    assert migrate_legacy_db(tmp_path) is False


def test_create_project_dir_idempotent(tmp_path: Path):
    a = create_project_dir(tmp_path)
    b = create_project_dir(tmp_path)
    assert a == b
    assert (tmp_path / ".snowcite" / "cache").is_dir()
