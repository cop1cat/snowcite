"""snowcite — MCP server + library for systematic literature review.

Re-exports the stable, library-usable surface. The MCP tool surface is
registered via `server.py` / `snowcite.app`; consumers integrating as a
library work against the persistence + source layers.
"""

from snowcite.persistence import (
    ApprovedPaper,
    PersistResult,
    load_approved_papers,
    persist_papers,
    resolve_cluster_paper_ids,
)
from snowcite.projects import (
    NoProjectError,
    create_project_dir,
    find_project_root,
    get_db_path,
    require_project_root,
)
from snowcite.sources.base import Paper
from snowcite.types import (
    Backend,
    Confidence,
    Direction,
    Phase,
    ReviewedBy,
    Severity,
    Source,
    Status,
)


__version__ = "0.1.0"

__all__ = [
    "ApprovedPaper",
    "Backend",
    "Confidence",
    "Direction",
    "NoProjectError",
    "Paper",
    "PersistResult",
    "Phase",
    "ReviewedBy",
    "Severity",
    "Source",
    "Status",
    "__version__",
    "create_project_dir",
    "find_project_root",
    "get_db_path",
    "load_approved_papers",
    "persist_papers",
    "require_project_root",
    "resolve_cluster_paper_ids",
]
