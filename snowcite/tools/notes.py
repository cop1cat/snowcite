"""Notes / knowledge-graph tools (v0.3).

Notes are short structured statements about papers, written during review and
synthesised across papers afterwards. They form the working memory the user
draws on during writing — facts, methods, gaps, contradictions — instead of
re-reading abstracts. Tool layer enforces the per-paper vs cross-paper split:

- per-paper notes (claim/finding/method/limitation) require `paper_id`;
- cross-paper notes (gap/contradiction/consensus/open_question) reject it
  and instead reference other notes via `note_links` (Phase 2).
"""

from typing import Any

from snowcite.app import mcp
from snowcite.db import get_connection
from snowcite.types import (
    CROSS_PAPER_NOTE_TYPES,
    PER_PAPER_NOTE_TYPES,
    NoteLinkKind,
    NoteType,
)


def _validate_paper_id_for_type(note_type: str, paper_id: int | None) -> str | None:
    """Return an error message if (type, paper_id) combination is invalid, else None."""
    if note_type in PER_PAPER_NOTE_TYPES and paper_id is None:
        return f"note type {note_type!r} requires paper_id"
    if note_type in CROSS_PAPER_NOTE_TYPES and paper_id is not None:
        return f"note type {note_type!r} is cross-paper; leave paper_id null"
    return None


@mcp.tool()
async def add_note(
    type: NoteType,  # noqa: A002 — natural field name across the notes API
    text: str,
    paper_id: int | None = None,
    cluster: str | None = None,
) -> dict[str, Any]:
    """Record a single graph note. Returns {id} on success, {error} on validation failure.

    `type` ∈ {claim, finding, method, limitation, gap, contradiction, consensus, open_question}.
    Per-paper types require `paper_id`; cross-paper types reject it.
    `cluster` should match a topic from the current `review_summary` clusters
    (Claude must not invent new ones).
    Keep `text` short — one or two sentences, paraphrased.
    """
    err = _validate_paper_id_for_type(type, paper_id)
    if err:
        return {"error": err}
    if not text.strip():
        return {"error": "text is empty"}

    async with get_connection() as conn:
        cur = await conn.execute(
            "INSERT INTO notes (paper_id, cluster, type, text) VALUES (?, ?, ?, ?)",
            (paper_id, cluster, type, text.strip()),
        )
        await conn.commit()
        return {"id": cur.lastrowid}


@mcp.tool()
async def add_notes(notes: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch-insert notes. Each item: {type, text, paper_id?, cluster?}.

    Returns `{inserted: N, ids: [...], errors: [{index, error}]}`. Valid items
    are inserted even if some fail validation; the caller can fix the rejected
    rows and resend just those.
    """
    inserted_ids: list[int] = []
    errors: list[dict[str, Any]] = []
    async with get_connection() as conn:
        for idx, item in enumerate(notes):
            note_type = item.get("type")
            text = item.get("text", "")
            paper_id = item.get("paper_id")
            cluster = item.get("cluster")
            if not note_type:
                errors.append({"index": idx, "error": "missing type"})
                continue
            err = _validate_paper_id_for_type(note_type, paper_id)
            if err:
                errors.append({"index": idx, "error": err})
                continue
            if not isinstance(text, str) or not text.strip():
                errors.append({"index": idx, "error": "text is empty"})
                continue
            cur = await conn.execute(
                "INSERT INTO notes (paper_id, cluster, type, text) VALUES (?, ?, ?, ?)",
                (paper_id, cluster, note_type, text.strip()),
            )
            inserted_ids.append(cur.lastrowid)
        await conn.commit()
    return {"inserted": len(inserted_ids), "ids": inserted_ids, "errors": errors}


@mcp.tool()
async def get_notes(
    paper_id: int | None = None,
    cluster: str | None = None,
    type: NoteType | None = None,  # noqa: A002 — field name consistency across notes API
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch notes filtered by paper, cluster, and/or type. Newest first.

    Without filters returns every note up to `limit`. Use this before drafting a
    section to pull the relevant part of the graph.
    """
    query = "SELECT id, paper_id, cluster, type, text, created_at, updated_at FROM notes WHERE 1=1"
    params: list[Any] = []
    if paper_id is not None:
        query += " AND paper_id = ?"
        params.append(paper_id)
    if cluster is not None:
        query += " AND cluster = ?"
        params.append(cluster)
    if type is not None:
        query += " AND type = ?"
        params.append(type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@mcp.tool()
async def update_note(
    note_id: int,
    text: str | None = None,
    type: NoteType | None = None,  # noqa: A002 — field name consistency across notes API
    cluster: str | None = None,
) -> dict[str, Any]:
    """Edit fields on an existing note. Pass only the fields to change.

    Type changes are validated against the existing `paper_id` — switching from
    a per-paper type to a cross-paper type (or vice versa) requires also
    nulling/setting paper_id, which this tool will not do; recreate the note
    instead in that case.
    """
    if text is None and type is None and cluster is None:
        return {"error": "no fields to update"}

    async with get_connection() as conn:
        cur = await conn.execute("SELECT paper_id, type FROM notes WHERE id = ?", (note_id,))
        row = await cur.fetchone()
        if row is None:
            return {"error": f"note {note_id} not found"}

        new_type = type or row["type"]
        err = _validate_paper_id_for_type(new_type, row["paper_id"])
        if err:
            return {"error": f"type change invalid: {err}"}

        sets: list[str] = []
        params: list[Any] = []
        if text is not None:
            if not text.strip():
                return {"error": "text is empty"}
            sets.append("text = ?")
            params.append(text.strip())
        if type is not None:
            sets.append("type = ?")
            params.append(type)
        if cluster is not None:
            sets.append("cluster = ?")
            params.append(cluster)
        sets.append("updated_at = CURRENT_TIMESTAMP")
        params.append(note_id)

        # `sets` is built only from the fixed allowlist above — no user input
        # reaches the SQL.
        sql = f"UPDATE notes SET {', '.join(sets)} WHERE id = ?"  # noqa: S608
        await conn.execute(sql, params)
        await conn.commit()
    return {"updated": True, "id": note_id}


@mcp.tool()
async def delete_note(note_id: int) -> dict[str, Any]:
    """Remove a note and any links touching it. Idempotent — missing id is a no-op."""
    async with get_connection() as conn:
        cur = await conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        await conn.commit()
    return {"deleted": cur.rowcount}


@mcp.tool()
async def link_notes(
    from_note_id: int,
    to_note_id: int,
    kind: NoteLinkKind,
) -> dict[str, Any]:
    """Connect two notes with a typed edge.

    `kind` ∈ {supports, contradicts, extends, derived_from}. Used during
    cross-paper synthesis (Phase 2) to anchor `gap`/`contradiction`/etc. notes
    to the per-paper notes that prompted them.
    """
    async with get_connection() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO note_links (from_note_id, to_note_id, kind) VALUES (?, ?, ?)",
            (from_note_id, to_note_id, kind),
        )
        await conn.commit()
    return {"linked": True}


@mcp.tool()
async def get_note_density(cluster: str | None = None) -> dict[str, Any]:
    """Note counts per cluster × type — used by Phase 2's `find_gaps`.

    Without `cluster` returns the full breakdown; with `cluster` filters to one.
    Clusters with few per-paper notes or no `gap`/`contradiction` resolution are
    a hint that synthesis is incomplete.
    """
    query = """
        SELECT COALESCE(cluster, '') AS cluster, type, COUNT(*) AS n
        FROM notes
    """
    params: list[Any] = []
    if cluster is not None:
        query += " WHERE cluster = ?"
        params.append(cluster)
    query += " GROUP BY cluster, type ORDER BY cluster, type"

    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()

    by_cluster: dict[str, dict[str, int]] = {}
    for r in rows:
        c = r["cluster"] or "(unscoped)"
        by_cluster.setdefault(c, {})[r["type"]] = r["n"]
    return {"density": by_cluster}
