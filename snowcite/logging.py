"""Snowcite's single logger.

All modules use `from snowcite.logging import log`. Callers embedding snowcite
as a library can silence or re-route via `logging.getLogger("snowcite")`.
"""

import logging


log = logging.getLogger("snowcite")

# Ensure warnings surface by default when no root configuration is present;
# the MCP server entrypoint does a richer setup in `server.py`.
if not log.handlers and not logging.getLogger().handlers:
    log.addHandler(logging.NullHandler())
