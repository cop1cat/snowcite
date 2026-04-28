"""Critique / revise loop (Phase 5 of v0.3).

The third leg of the writing flow: draft → critique → revise. `critique_section`
gives Claude everything it needs to read a section like a strict academic
reviewer (the draft, the notes the section's claims should rest on, the linked
papers); Claude returns a list of severity-tagged issues; `record_section_critique`
persists the severity counts and updates iteration state. `revise_section`
replaces the draft with the rewrite and resets the counters so the next critique
sees a fresh draft.

Issues themselves are transient — they're produced fresh each iteration, so
storing them buys nothing. Only the *aggregate* (blockers / should_fix / nits)
and iteration count live on the section row, because they drive the stop
criterion.

Stop criterion: critique stops when blockers=0 OR critique_iterations >= 2.
The user can always override by calling `revise_section` again or
`update_section(status='done')` regardless of what the counters say.
"""

import json
from typing import Any

from snowcite.app import mcp
from snowcite.db import get_connection


_MAX_CRITIQUE_ITERATIONS = 2


@mcp.tool()
async def get_section_critique_inputs(section_id: int) -> dict[str, Any]:
    """Bundle everything needed to critique a section in one call.

    Returns `{section, notes, linked_papers}`:
    - `section`: full section row including current draft and severity state.
    - `notes`: per-paper + cross-paper notes whose `cluster` overlaps the
      section's `scope.clusters`. The corpus the section's claims should rest on.
    - `linked_papers`: papers connected via `paper_section_links`, with title
      / year / venue / review_status. Used to check that cited papers are
      actually approved and on-scope.

    Claude reads this, generates `[{severity, type, text, suggested_action}]`
    issues, and passes them to `record_section_critique`.
    """
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, title, scope_json, draft, status, parent_id, position,
                   blockers, should_fix, nits, critique_iterations,
                   created_at, updated_at
            FROM sections WHERE id = ?
            """,
            (section_id,),
        )
        sec_row = await cur.fetchone()
        if sec_row is None:
            return {"error": f"section {section_id} not found"}

        scope = json.loads(sec_row["scope_json"])
        clusters = [c for c in scope.get("clusters", []) if c]

        notes: list[dict[str, Any]] = []
        if clusters:
            placeholders = ",".join("?" * len(clusters))
            cur = await conn.execute(
                f"""
                SELECT id, paper_id, cluster, type, text
                FROM notes WHERE cluster IN ({placeholders})
                ORDER BY paper_id NULLS LAST, id
                """,  # noqa: S608 — placeholders count is fixed-from-input length
                clusters,
            )
            notes = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue, p.doi,
                   r.status AS review_status, l.via_query
            FROM paper_section_links l
            JOIN papers p ON p.id = l.paper_id
            LEFT JOIN reviews r ON r.paper_id = p.id
            WHERE l.section_id = ?
            ORDER BY p.year DESC, p.id DESC
            """,
            (section_id,),
        )
        linked = [dict(r) for r in await cur.fetchall()]

    section = {
        "id": sec_row["id"],
        "title": sec_row["title"],
        "scope": scope,
        "draft": sec_row["draft"],
        "status": sec_row["status"],
        "severity": {
            "blockers": sec_row["blockers"],
            "should_fix": sec_row["should_fix"],
            "nits": sec_row["nits"],
        },
        "critique_iterations": sec_row["critique_iterations"],
    }
    return {"section": section, "notes": notes, "linked_papers": linked}


@mcp.tool()
async def record_section_critique(
    section_id: int,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist severity aggregates from a critique pass and decide whether to stop.

    `issues` items: `{severity: 'blocker'|'should_fix'|'nit', type, text, suggested_action?}`.
    Only the per-severity counts are stored; the issues list is echoed back so
    Claude can present it to the user without re-running the analysis.

    Returns `{should_stop: bool, reason, severity, iteration, issues}`. Sets
    section.status to 'critiqued'.
    """
    counts = {"blocker": 0, "should_fix": 0, "nit": 0}
    for idx, item in enumerate(issues):
        sev = item.get("severity")
        if sev not in counts:
            return {"error": f"issues[{idx}].severity must be one of {sorted(counts)}; got {sev!r}"}
        counts[sev] += 1

    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT critique_iterations FROM sections WHERE id = ?", (section_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return {"error": f"section {section_id} not found"}
        new_iter = row["critique_iterations"] + 1

        await conn.execute(
            """
            UPDATE sections
            SET blockers = ?, should_fix = ?, nits = ?,
                critique_iterations = ?, status = 'critiqued',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (counts["blocker"], counts["should_fix"], counts["nit"], new_iter, section_id),
        )
        await conn.commit()

    if counts["blocker"] == 0:
        should_stop, reason = True, "no blockers remaining"
    elif new_iter >= _MAX_CRITIQUE_ITERATIONS:
        should_stop, reason = (
            True,
            (
                f"reached max critique iterations ({_MAX_CRITIQUE_ITERATIONS}) — "
                "surface remaining blockers to the user"
            ),
        )
    else:
        should_stop, reason = False, "blockers remain; revise and re-critique"

    return {
        "should_stop": should_stop,
        "reason": reason,
        "severity": {
            "blockers": counts["blocker"],
            "should_fix": counts["should_fix"],
            "nits": counts["nit"],
        },
        "iteration": new_iter,
        "issues": issues,
    }


@mcp.tool()
async def revise_section(
    section_id: int,
    new_draft: str,
    mark_done: bool = False,
) -> dict[str, Any]:
    """Replace the section draft and reset critique state for a fresh pass.

    Resets `blockers`, `should_fix`, `nits`, and `critique_iterations` so the
    next `record_section_critique` starts clean. Status moves to 'drafting'
    by default; pass `mark_done=True` when the user signals the section is
    finished (e.g. after a stop on `iteration >= 2` and they accept residual
    nits).
    """
    new_status = "done" if mark_done else "drafting"
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            UPDATE sections
            SET draft = ?, blockers = 0, should_fix = 0, nits = 0,
                critique_iterations = 0, status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_draft, new_status, section_id),
        )
        if cur.rowcount == 0:
            return {"error": f"section {section_id} not found"}
        await conn.commit()
    return {"updated": True, "id": section_id, "status": new_status}
