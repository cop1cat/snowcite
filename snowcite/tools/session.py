"""T26: session state snapshot for `/clear`-friendly workflow recovery.

After a context reset Claude loses track of what's already done in this
project. `get_session_state()` reads the DB and returns a compact (~200-word)
structured summary so Claude can restore bearings with one MCP call instead
of probing half a dozen tools.
"""

from typing import Any

import aiosqlite

from snowcite.app import mcp
from snowcite.db import get_connection
from snowcite.projects import find_project_root
from snowcite.types import Phase


async def _infer_phase(conn: aiosqlite.Connection) -> Phase:
    """Derive workflow phase from DB state.

    Walks later stages first — once we see expanded sections, we're 'writing'
    (or 'polishing') regardless of the review state. Falls back to earlier
    phases when the later tables are empty.
    """
    # Writing / polishing — latest stage, beats everything earlier.
    cur = await conn.execute("SELECT COUNT(*) FROM section_content")
    sections_written = (await cur.fetchone())[0]
    if sections_written > 0:
        cur = await conn.execute("SELECT COUNT(*) FROM section_content WHERE polished = 0")
        unpolished = (await cur.fetchone())[0]
        return "writing" if unpolished > 0 else "polishing"

    # Skeleton approved?
    cur = await conn.execute("SELECT approved FROM skeleton WHERE id = 1")
    row = await cur.fetchone()
    if row and row["approved"]:
        return "skeleton_approved"

    # Outline?
    cur = await conn.execute("SELECT approved FROM outline WHERE id = 1")
    row = await cur.fetchone()
    if row:
        return "outline_approved" if row["approved"] else "outline_proposed"

    # Any papers yet?
    cur = await conn.execute("SELECT COUNT(*) FROM papers")
    total_papers = (await cur.fetchone())[0]
    if total_papers == 0:
        cur = await conn.execute("SELECT 1 FROM review_criteria LIMIT 1")
        return "criteria_set" if await cur.fetchone() else "not_started"

    # Review in flight?
    cur = await conn.execute("SELECT COUNT(*) FROM reviews WHERE status = 'unreviewed'")
    unreviewed = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM reviews WHERE status = 'approved'")
    approved = (await cur.fetchone())[0]
    if approved > 0 and unreviewed == 0:
        return "snowballing"
    return "reviewing"


_NEXT_ACTION_HINTS: dict[Phase, str] = {
    "not_started": "Run init_project() if you haven't, then set_review_criteria().",
    "criteria_set": "Run search_papers(query=...) to pull in candidates.",
    "reviewing": "Batch through get_unreviewed_papers(limit=20). Use reviewed_by='auto_low' for uncertain cases.",
    "snowballing": "Walk approved papers via expand_citations(), or move on to propose an outline.",
    "outline_proposed": "Ask the user to approve the outline, then approve_outline().",
    "outline_approved": "Write the skeleton (3-5 sentences/section) via save_skeleton().",
    "skeleton_approved": "Expand sections one at a time via save_section(). Run check_section_drift first.",
    "writing": "Continue save_section for remaining outline sections, or polish_section completed ones.",
    "polishing": "Run polish_document across the whole doc, then compile_pdf.",
    "done": "Document compiled. Nothing outstanding.",
}


@mcp.tool()
async def get_session_state() -> dict[str, Any]:
    """Compact snapshot of the current project for post-`/clear` recovery.

    Returns phase, next_action hint, counts, and the last few review actions.
    No abstracts, no section bodies — this is a restore beacon, not a dump.
    """
    if find_project_root() is None:
        return {
            "phase": "not_started",
            "next_action": _NEXT_ACTION_HINTS["not_started"],
            "project_active": False,
        }

    async with get_connection() as conn:
        phase = await _infer_phase(conn)

        cur = await conn.execute("SELECT COUNT(*) FROM papers")
        total = (await cur.fetchone())[0]
        counts: dict[str, int] = {"papers_total": total}
        cur = await conn.execute("SELECT status, COUNT(*) FROM reviews GROUP BY status")
        for row in await cur.fetchall():
            counts[row[0]] = row[1]

        cur = await conn.execute("SELECT COUNT(*) FROM section_content")
        counts["sections_written"] = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM section_content WHERE polished = 1")
        counts["sections_polished"] = (await cur.fetchone())[0]

        cur = await conn.execute(
            """
            SELECT paper_id, old_status, new_status, reason, reviewed_by, changed_at
            FROM review_history ORDER BY id DESC LIMIT 5
            """
        )
        last_actions = [
            {
                "paper_id": r["paper_id"],
                "old_status": r["old_status"],
                "new_status": r["new_status"],
                "reason": r["reason"],
                "reviewed_by": r["reviewed_by"],
                "at": r["changed_at"],
            }
            for r in await cur.fetchall()
        ]

        cur = await conn.execute("SELECT approved FROM outline WHERE id = 1")
        outline_row = await cur.fetchone()
        cur = await conn.execute("SELECT approved FROM skeleton WHERE id = 1")
        skeleton_row = await cur.fetchone()

        cur = await conn.execute(
            """
            SELECT target_pages, target_sources_min, target_sources_max,
                   target_words, citation_density_target
            FROM project_metadata WHERE id = 1
            """
        )
        meta_row = await cur.fetchone()
        targets = (
            {k: meta_row[k] for k in meta_row.keys() if meta_row[k] is not None} if meta_row else {}
        )

    return {
        "phase": phase,
        "next_action": _NEXT_ACTION_HINTS[phase],
        "project_active": True,
        "counts": counts,
        "last_actions": last_actions,
        "outline": {
            "exists": outline_row is not None,
            "approved": bool(outline_row and outline_row["approved"]),
        },
        "skeleton": {
            "exists": skeleton_row is not None,
            "approved": bool(skeleton_row and skeleton_row["approved"]),
        },
        "targets": targets,
    }
