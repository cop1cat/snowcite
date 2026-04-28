"""Section-as-entity tools (Phase 3 of v0.3).

A section row owns its own scope, draft, status, and severity counters. The
critique/revise loop in Phase 5 reads and writes these fields per section,
which is why titles + scope live in the DB (not just in a singleton outline
JSON like the v0.2 path).

`scope` is a structured dict — `{clusters, keywords, questions}` — so that
`research_section` (Phase 4) can build search queries from it without parsing
free-form text.
"""

import json
from typing import Any

from snowcite.app import mcp
from snowcite.db import get_connection
from snowcite.types import SectionStatus


def _normalize_scope(scope: dict[str, Any] | None) -> dict[str, list[str]]:
    """Coerce arbitrary scope payloads into the canonical 3-key shape.

    Unknown keys are dropped silently — they'd just confuse `research_section`.
    Empty lists are kept (they signal "intentionally empty" vs missing).
    """
    scope = scope or {}
    out: dict[str, list[str]] = {"clusters": [], "keywords": [], "questions": []}
    for key in out:
        val = scope.get(key, [])
        if isinstance(val, list):
            out[key] = [str(v) for v in val if isinstance(v, str | int | float)]
    return out


def _row_to_section(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "scope": json.loads(row["scope_json"]),
        "draft": row["draft"],
        "status": row["status"],
        "parent_id": row["parent_id"],
        "position": row["position"],
        "severity": {
            "blockers": row["blockers"],
            "should_fix": row["should_fix"],
            "nits": row["nits"],
        },
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@mcp.tool()
async def create_section(
    title: str,
    scope: dict[str, Any] | None = None,
    parent_id: int | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Create a single section. Returns `{id}`.

    `scope` is a dict with optional keys `clusters`, `keywords`, `questions`
    (each a list of strings) — the prompts used by `research_section` and the
    critique loop. Unknown keys are dropped.
    `position` orders siblings; if omitted, appended after current siblings.
    """
    if not title.strip():
        return {"error": "title is empty"}
    norm_scope = _normalize_scope(scope)
    async with get_connection() as conn:
        if position is None:
            cur = await conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM sections WHERE parent_id IS ?",
                (parent_id,),
            )
            position = (await cur.fetchone())["next"]
        cur = await conn.execute(
            """
            INSERT INTO sections (title, scope_json, parent_id, position)
            VALUES (?, ?, ?, ?)
            """,
            (title.strip(), json.dumps(norm_scope), parent_id, position),
        )
        await conn.commit()
        return {"id": cur.lastrowid}


@mcp.tool()
async def bulk_create_sections(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Bulk-create sections from a proposed outline.

    Each item: `{title, scope?, parent_id?, position?}`. Order in the input
    list becomes default `position` if not provided. Returns
    `{inserted: N, ids: [...], errors: [{index, error}]}`.

    Use after Claude proposes an outline from `review_summary` clusters and
    the user approves — single round-trip for the whole structure.
    """
    inserted_ids: list[int] = []
    errors: list[dict[str, Any]] = []
    async with get_connection() as conn:
        # Cache next-position per parent so a bulk insert without explicit
        # positions packs them sequentially instead of all colliding at
        # MAX+1 of the pre-call state.
        next_pos: dict[int | None, int] = {}
        for idx, item in enumerate(sections):
            title = item.get("title", "")
            if not isinstance(title, str) or not title.strip():
                errors.append({"index": idx, "error": "title is empty"})
                continue
            parent_id = item.get("parent_id")
            position = item.get("position")
            if position is None:
                if parent_id not in next_pos:
                    cur = await conn.execute(
                        "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM sections "
                        "WHERE parent_id IS ?",
                        (parent_id,),
                    )
                    next_pos[parent_id] = (await cur.fetchone())["next"]
                position = next_pos[parent_id]
                next_pos[parent_id] += 1
            scope = _normalize_scope(item.get("scope"))
            cur = await conn.execute(
                """
                INSERT INTO sections (title, scope_json, parent_id, position)
                VALUES (?, ?, ?, ?)
                """,
                (title.strip(), json.dumps(scope), parent_id, position),
            )
            inserted_ids.append(cur.lastrowid)
        await conn.commit()
    return {"inserted": len(inserted_ids), "ids": inserted_ids, "errors": errors}


@mcp.tool()
async def list_sections() -> list[dict[str, Any]]:
    """All sections, ordered by (parent_id, position). Hierarchical via parent_id."""
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, title, scope_json, draft, status, parent_id, position,
                   blockers, should_fix, nits, created_at, updated_at
            FROM sections
            ORDER BY COALESCE(parent_id, 0), position, id
            """
        )
        rows = await cur.fetchall()
    return [_row_to_section(r) for r in rows]


@mcp.tool()
async def get_section(section_id: int) -> dict[str, Any] | None:
    """Full record for one section, or None if missing."""
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, title, scope_json, draft, status, parent_id, position,
                   blockers, should_fix, nits, created_at, updated_at
            FROM sections WHERE id = ?
            """,
            (section_id,),
        )
        row = await cur.fetchone()
    return _row_to_section(row) if row else None


@mcp.tool()
async def update_section(
    section_id: int,
    title: str | None = None,
    scope: dict[str, Any] | None = None,
    draft: str | None = None,
    status: SectionStatus | None = None,
    parent_id: int | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Patch fields on a section. Pass only the fields to change.

    Note: severity counters (`blockers`, `should_fix`, `nits`) are written by
    `critique_section` / `revise_section` (Phase 5), not by this tool.
    Setting `parent_id` does not validate against cycles — keep the tree sane.
    """
    if all(v is None for v in (title, scope, draft, status, parent_id, position)):
        return {"error": "no fields to update"}

    sets: list[str] = []
    params: list[Any] = []
    if title is not None:
        if not title.strip():
            return {"error": "title is empty"}
        sets.append("title = ?")
        params.append(title.strip())
    if scope is not None:
        sets.append("scope_json = ?")
        params.append(json.dumps(_normalize_scope(scope)))
    if draft is not None:
        sets.append("draft = ?")
        params.append(draft)
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if parent_id is not None:
        if parent_id == section_id:
            return {"error": "section cannot be its own parent"}
        sets.append("parent_id = ?")
        params.append(parent_id)
    if position is not None:
        sets.append("position = ?")
        params.append(position)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(section_id)

    async with get_connection() as conn:
        # `sets` is built only from the fixed allowlist above.
        sql = f"UPDATE sections SET {', '.join(sets)} WHERE id = ?"  # noqa: S608
        cur = await conn.execute(sql, params)
        if cur.rowcount == 0:
            return {"error": f"section {section_id} not found"}
        await conn.commit()
    return {"updated": True, "id": section_id}


@mcp.tool()
async def delete_section(section_id: int) -> dict[str, Any]:
    """Remove a section and all descendants (cascade via parent_id FK)."""
    async with get_connection() as conn:
        cur = await conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
        await conn.commit()
    return {"deleted": cur.rowcount}


@mcp.tool()
async def get_outline_inputs() -> dict[str, Any]:
    """Building blocks for proposing an outline: thesis + clusters + criteria.

    Returns `{thesis, clusters, criteria}` so Claude can propose a section
    structure without three separate round-trips. Designed to be the single
    read before `bulk_create_sections`.
    """
    async with get_connection() as conn:
        cur = await conn.execute("SELECT content FROM thesis WHERE id = 1")
        row = await cur.fetchone()
        thesis = row["content"] if row else None

        cur = await conn.execute("SELECT clusters_json FROM review_summary WHERE id = 1")
        row = await cur.fetchone()
        clusters = json.loads(row["clusters_json"]) if row else []

        cur = await conn.execute(
            "SELECT criteria_text FROM review_criteria ORDER BY id DESC LIMIT 1"
        )
        row = await cur.fetchone()
        criteria = row["criteria_text"] if row else None

    return {"thesis": thesis, "clusters": clusters, "criteria": criteria}
