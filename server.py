"""snowball-mcp — MCP server for systematic literature review.

Phase 1 scaffold: tool signatures registered, bodies are stubs.
See PLAN.md for the full roadmap and CLAUDE.md for the review workflow.
"""

import asyncio
import shutil
import sys
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from snowball.db import init_db

mcp = FastMCP("snowball")

Status = Literal["approved", "maybe", "rejected", "unreviewed"]
Source = Literal["arxiv", "semantic_scholar", "openalex"]
Direction = Literal["references", "citations"]
ReviewedBy = Literal["auto", "user"]


# ─── Search & save ──────────────────────────────────────────────────────────

@mcp.tool()
async def search_papers(
    query: str,
    sources: list[Source] | None = None,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict[str, Any]]:
    """Search arXiv / Semantic Scholar / OpenAlex, dedup, return papers (not saved)."""
    raise NotImplementedError("Phase 2")


@mcp.tool()
async def save_papers(papers: list[dict[str, Any]]) -> dict[str, int]:
    """INSERT OR IGNORE papers into DB. Returns {saved, duplicates}."""
    raise NotImplementedError("Phase 2")


@mcp.tool()
async def get_saved_papers(
    status: Status | None = None,
    source: Source | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch saved papers with optional filters."""
    raise NotImplementedError("Phase 3")


@mcp.tool()
async def get_paper_details(paper_id: int) -> dict[str, Any]:
    """Full paper record by id."""
    raise NotImplementedError("Phase 3")


@mcp.tool()
async def expand_citations(
    paper_id: int,
    direction: Direction,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch references or citations for a paper. arXiv falls back to Semantic Scholar by DOI."""
    raise NotImplementedError("Phase 4")


# ─── Review (chat-native) ───────────────────────────────────────────────────

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


# ─── LaTeX / PDF ────────────────────────────────────────────────────────────

@mcp.tool()
async def write_latex(
    sections: list[dict[str, str]],
    title: str,
    author: str,
    bibliography_style: str = "plain",
    output_dir: str = "data",
) -> dict[str, str]:
    """Build .tex + .bib from approved papers. Section content is provided ready by Claude."""
    raise NotImplementedError("Phase 6")


@mcp.tool()
async def compile_pdf(tex_path: str) -> dict[str, Any]:
    """Compile via tectonic. Returns {pdf_path, success, log}."""
    raise NotImplementedError("Phase 6")


# ─── Entrypoint ─────────────────────────────────────────────────────────────

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
