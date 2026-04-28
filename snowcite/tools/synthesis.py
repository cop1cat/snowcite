"""Cross-paper synthesis tools (Phase 2 of v0.3).

Per-paper notes (Phase 1) are local: each one says something about a single
paper. Synthesis is the second pass — Claude reads the per-paper notes for a
cluster as a corpus and writes cross-paper notes (`gap`, `contradiction`,
`consensus`, `open_question`) that name patterns the user can't see by reading
papers one at a time. Cross-paper notes must point back at the per-paper notes
that produced them via `derived_from` links — otherwise they're untraceable.

`find_gaps` is a heuristic surfacer for clusters where synthesis is missing
or thin. It doesn't prescribe what to add — it just flags the spots that look
under-synthesised.
"""

import json
from typing import Any

from snowcite.app import mcp
from snowcite.db import get_connection
from snowcite.types import CROSS_PAPER_NOTE_TYPES, NoteType


# Threshold for "thin" cluster: fewer per-paper notes than this is a hint that
# synthesis can't be meaningful yet — read more papers first.
_MIN_PER_PAPER_NOTES = 3


@mcp.tool()
async def get_cluster_notes(cluster: str) -> dict[str, Any]:
    """Bundled view of one cluster: per-paper notes grouped by paper + existing cross-paper notes.

    Use this as the input to a synthesis pass — it returns everything Claude
    needs to reason across the cluster in one round-trip:

    - `papers`: list of `{paper_id, title, year, notes: [...]}` for every paper
      with at least one note in this cluster.
    - `cross_paper`: list of cross-paper notes (gap/contradiction/consensus/
      open_question) already recorded against the cluster, with their
      `derived_from` source ids.
    - `counts`: per-type counts in the cluster.
    """
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT n.id, n.paper_id, n.type, n.text, n.created_at,
                   p.title, p.year
            FROM notes n
            LEFT JOIN papers p ON p.id = n.paper_id
            WHERE n.cluster = ?
            ORDER BY n.paper_id NULLS LAST, n.id
            """,
            (cluster,),
        )
        rows = await cur.fetchall()

        cur = await conn.execute(
            """
            SELECT from_note_id, to_note_id, kind FROM note_links
            WHERE from_note_id IN (
                SELECT id FROM notes WHERE cluster = ?
            )
            """,
            (cluster,),
        )
        link_rows = await cur.fetchall()

    by_paper: dict[int, dict[str, Any]] = {}
    cross: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
        rec = {"id": r["id"], "type": r["type"], "text": r["text"]}
        if r["paper_id"] is None:
            cross.append(rec)
        else:
            bucket = by_paper.setdefault(
                r["paper_id"],
                {
                    "paper_id": r["paper_id"],
                    "title": r["title"],
                    "year": r["year"],
                    "notes": [],
                },
            )
            bucket["notes"].append(rec)

    # Attach derived_from sources to each cross-paper note.
    derived: dict[int, list[int]] = {}
    for lr in link_rows:
        if lr["kind"] == "derived_from":
            derived.setdefault(lr["from_note_id"], []).append(lr["to_note_id"])
    for c in cross:
        c["derived_from"] = derived.get(c["id"], [])

    return {
        "cluster": cluster,
        "papers": list(by_paper.values()),
        "cross_paper": cross,
        "counts": counts,
    }


@mcp.tool()
async def add_synthesis_note(
    cluster: str,
    type: NoteType,  # noqa: A002 — natural field name across the notes API
    text: str,
    derived_from_note_ids: list[int],
) -> dict[str, Any]:
    """Atomic insert of a cross-paper note + `derived_from` links to its sources.

    `type` must be a cross-paper type (gap, contradiction, consensus,
    open_question). `derived_from_note_ids` must reference existing per-paper
    notes — at least one is required, so the synthesis is traceable. Returns
    `{id, links: N}` or `{error}`.
    """
    if type not in CROSS_PAPER_NOTE_TYPES:
        return {
            "error": f"type must be cross-paper ({sorted(CROSS_PAPER_NOTE_TYPES)}); got {type!r}"
        }
    if not text.strip():
        return {"error": "text is empty"}
    if not derived_from_note_ids:
        return {"error": "derived_from_note_ids cannot be empty — synthesis must cite sources"}

    async with get_connection() as conn:
        # Validate that all source ids exist and are per-paper.
        placeholders = ",".join("?" * len(derived_from_note_ids))
        cur = await conn.execute(
            f"SELECT id, paper_id FROM notes WHERE id IN ({placeholders})",  # noqa: S608
            derived_from_note_ids,
        )
        found = await cur.fetchall()
        found_ids = {r["id"] for r in found}
        missing = [i for i in derived_from_note_ids if i not in found_ids]
        if missing:
            return {"error": f"derived_from_note_ids not found: {missing}"}
        non_paper = [r["id"] for r in found if r["paper_id"] is None]
        if non_paper:
            return {
                "error": f"derived_from must point to per-paper notes; "
                f"these are cross-paper: {non_paper}"
            }

        cur = await conn.execute(
            "INSERT INTO notes (paper_id, cluster, type, text) VALUES (NULL, ?, ?, ?)",
            (cluster, type, text.strip()),
        )
        new_id = cur.lastrowid
        for src in derived_from_note_ids:
            await conn.execute(
                "INSERT OR IGNORE INTO note_links (from_note_id, to_note_id, kind) "
                "VALUES (?, ?, 'derived_from')",
                (new_id, src),
            )
        await conn.commit()
    return {"id": new_id, "links": len(derived_from_note_ids)}


@mcp.tool()
async def find_gaps(cluster: str | None = None) -> dict[str, Any]:
    """Surface clusters where cross-paper synthesis is thin or missing.

    Heuristics (each cluster can hit multiple):
    - `thin`: fewer than 3 per-paper notes — synthesis is premature, read more
      papers first.
    - `unsynthesised`: ≥1 `limitation` note but no `gap`/`open_question` —
      limitations were noted per-paper but never aggregated into a cross-paper gap.
    - `unresolved_contradiction`: `contradiction` notes without `derived_from`
      links — recorded but not anchored to source papers.
    - `cluster_unknown_in_summary`: cluster name doesn't match any cluster in
      the current `review_summary` — likely a typo or invented label.

    With `cluster` filters to that one cluster; otherwise scans all clusters
    that have any notes.
    """
    async with get_connection() as conn:
        query = "SELECT cluster, type, id FROM notes WHERE cluster IS NOT NULL"
        params: list[Any] = []
        if cluster is not None:
            query += " AND cluster = ?"
            params.append(cluster)
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()

        cur = await conn.execute("SELECT from_note_id FROM note_links WHERE kind = 'derived_from'")
        anchored = {r["from_note_id"] for r in await cur.fetchall()}

    by_cluster: dict[str, dict[str, list[int]]] = {}
    for r in rows:
        by_cluster.setdefault(r["cluster"], {}).setdefault(r["type"], []).append(r["id"])

    findings: list[dict[str, Any]] = []
    for cname, types in sorted(by_cluster.items()):
        per_paper_n = sum(
            len(ids)
            for t, ids in types.items()
            if t in {"claim", "finding", "method", "limitation"}
        )
        flags: list[str] = []
        if per_paper_n < _MIN_PER_PAPER_NOTES:
            flags.append("thin")
        if types.get("limitation") and not (types.get("gap") or types.get("open_question")):
            flags.append("unsynthesised")
        contradictions = types.get("contradiction", [])
        unanchored = [nid for nid in contradictions if nid not in anchored]
        if unanchored:
            flags.append("unresolved_contradiction")
        if flags:
            findings.append(
                {
                    "cluster": cname,
                    "flags": flags,
                    "per_paper_notes": per_paper_n,
                    "cross_paper_notes": sum(
                        len(ids) for t, ids in types.items() if t in CROSS_PAPER_NOTE_TYPES
                    ),
                    "unanchored_contradiction_ids": unanchored,
                }
            )

    # Cross-check cluster names against review_summary if available.
    unknown_clusters: list[str] = []
    if cluster is None and by_cluster:
        async with get_connection() as conn:
            cur = await conn.execute("SELECT clusters_json FROM review_summary WHERE id = 1")
            row = await cur.fetchone()
        if row is not None:
            summary_clusters = {c.get("topic") for c in json.loads(row["clusters_json"])}
            unknown_clusters = sorted(set(by_cluster) - summary_clusters)

    return {
        "findings": findings,
        "unknown_clusters_in_summary": unknown_clusters,
        "total_clusters_with_notes": len(by_cluster),
    }
