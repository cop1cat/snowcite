"""Project resolver: locate `.snowcite/` by walking up from cwd.

Each snowcite project lives in its own directory, identified by a `.snowcite/`
subdirectory (analogous to `.git/`). Tools resolve the project at every call via
`require_project_root()`, so switching projects is just `cd` — there is no global
`current_project` state.
"""

import os
import shutil
from pathlib import Path


class NoProjectError(RuntimeError):
    """Raised when no `.snowcite/` is found in cwd or any parent."""


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (or cwd) looking for `.snowcite/`.

    Returns the directory that *contains* `.snowcite/`, or None if none found.

    Respects `SNOWCITE_PROJECT_ROOT` env var as an override — useful for tests
    and for running the server from a directory unrelated to the project.
    """
    override = os.environ.get("SNOWCITE_PROJECT_ROOT")
    if override:
        p = Path(override).resolve()
        return p if (p / ".snowcite").is_dir() else None

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / ".snowcite").is_dir():
            return directory
    return None


def require_project_root(start: Path | None = None) -> Path:
    """Same as `find_project_root`, but raises NoProjectError if none found."""
    root = find_project_root(start)
    if root is None:
        raise NoProjectError(
            "No snowcite project found in the current directory or any parent. "
            "Run `init_project()` here first to create a .snowcite/ directory."
        )
    return root


def get_db_path(start: Path | None = None) -> Path:
    """Absolute path to the active project's papers.db."""
    return require_project_root(start) / ".snowcite" / "papers.db"


def get_cache_dir(start: Path | None = None) -> Path:
    """Compile artifacts — always gitignored."""
    return require_project_root(start) / ".snowcite" / "cache"


def create_project_dir(target: Path | None = None) -> Path:
    """Create `.snowcite/` (and `cache/`) in `target` or cwd. Idempotent.

    Returns the path to the `.snowcite/` directory.
    """
    base = (target or Path.cwd()).resolve()
    snow = base / ".snowcite"
    snow.mkdir(exist_ok=True)
    (snow / "cache").mkdir(exist_ok=True)
    return snow


def migrate_legacy_db(target: Path | None = None) -> bool:
    """Move existing `./data/papers.db` into `./.snowcite/papers.db` if applicable.

    Returns True if migration occurred. No-op if there's already a DB under
    `.snowcite/` or no legacy file exists.

    Uses `shutil.move` rather than `Path.rename` — rename fails across
    filesystems (Docker bind mounts, symlinked directories, etc).
    """
    base = (target or Path.cwd()).resolve()
    legacy = base / "data" / "papers.db"
    dest = base / ".snowcite" / "papers.db"
    if legacy.exists() and not dest.exists():
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(legacy), str(dest))
        return True
    return False
