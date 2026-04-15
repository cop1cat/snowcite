from typing import Any

from snowball.app import mcp
from snowball.types import ReviewedBy, Source, Status


@mcp.tool()
async def set_review_criteria(criteria_text: str) -> dict[str, int]:
    """Store inclusion/exclusion criteria. Returns {id}."""
    raise NotImplementedError("Phase 5")


@mcp.tool()
async def get_review_criteria() -> dict[str, Any] | None:
    """Latest criteria. Claude must call this before each review batch (drift guard)."""
    raise NotImplementedError("Phase 5")


@mcp.tool()
async def get_unreviewed_papers(
    limit: int = 20,
    source: Source | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict[str, Any]]:
    """Batch of unreviewed papers for pre-filtering."""
    raise NotImplementedError("Phase 5")


@mcp.tool()
async def set_review_status(
    paper_ids: list[int],
    status: Status,
    reason: str,
    note: str | None = None,
    reviewed_by: ReviewedBy = "auto",
) -> dict[str, int]:
    """Batch-set review status with required reason (PRISMA trail)."""
    raise NotImplementedError("Phase 5")


@mcp.tool()
async def get_review_progress() -> dict[str, int]:
    """Counts: {total, approved, maybe, rejected, unreviewed}."""
    raise NotImplementedError("Phase 5")
