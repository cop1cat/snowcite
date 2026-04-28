"""snowcite — MCP server for systematic literature review.

See TODO.md for the roadmap and CLAUDE.md for the review workflow.
"""

import asyncio
import atexit
import logging
import shutil
import sys

from snowcite.app import mcp
from snowcite.db import init_db
from snowcite.projects import NoProjectError
from snowcite.sources._http import close_client

# Importing tool modules registers their @mcp.tool() decorators. `compile`
# shadows a Python builtin so it gets an alias.
from snowcite.tools import (  # noqa: F401
    artifacts as artifact_tools,
    compile as compile_tools,
    critique as critique_tools,
    doctor,
    export,
    import_refs,
    init,
    notes as note_tools,
    research as research_tools,
    review,
    review_quality,
    search,
    sections as section_tools,
    session,
    synthesis as synthesis_tools,
    writing,
)


def _configure_logging() -> None:
    """Route snowcite logs to stderr in a human-readable format.

    Library users who want to silence or re-route should configure the
    `snowcite` logger before calling `main()`.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("snowcite")
    if not logger.handlers:
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _check_tectonic() -> None:
    if shutil.which("tectonic") is None:
        logging.getLogger("snowcite").warning(
            "tectonic not found — `compile_pdf` will fail in LaTeX mode. "
            "Install with `brew install tectonic`."
        )


def _try_init_db() -> None:
    """Initialize DB if a project exists in cwd; skip silently otherwise.

    Cwd may not contain a project at startup — the user hasn't run
    `init_project()` yet, or the server was launched from an unrelated
    directory. Either case is fine: the first DB-touching tool will raise
    `NoProjectError` with a clear message, and `init_project` itself does
    not need a pre-existing project.
    """
    try:
        asyncio.run(init_db())
    except NoProjectError:
        pass


def _shutdown_http_client() -> None:
    """Close the shared httpx client on process exit — suppresses ResourceWarnings."""
    try:
        asyncio.run(close_client())
    except RuntimeError:
        # Event loop already closed; nothing we can do cleanly.
        pass


def main() -> None:
    _configure_logging()
    atexit.register(_shutdown_http_client)
    _try_init_db()
    _check_tectonic()
    mcp.run()


if __name__ == "__main__":
    main()
