"""snowball-mcp — MCP server for systematic literature review.

See PLAN.md for the roadmap and CLAUDE.md for the review workflow.
"""

import asyncio
import shutil
import sys

from snowball.app import mcp
from snowball.db import init_db

# Importing tool modules registers their @mcp.tool() decorators.
from snowball.tools import latex, review, search  # noqa: F401


def _check_tectonic() -> None:
    if shutil.which("tectonic") is None:
        print(
            "warning: tectonic not found — `compile_pdf` will fail. "
            "Install with `brew install tectonic`.",
            file=sys.stderr,
        )


def main() -> None:
    asyncio.run(init_db())
    _check_tectonic()
    mcp.run()


if __name__ == "__main__":
    main()
