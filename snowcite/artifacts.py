"""Research-artifact persistence: interviews, code, notes, documents, datasets.

Mirrors `persistence.py` for papers but for user-supplied materials. Artifacts
are cited inline and listed in a separate Primary-sources appendix; they do not
enter the main bibliography.
"""

import json
import re
from typing import Any

from snowcite.db import get_connection
from snowcite.types import ArtifactRecord, ArtifactType


_FILENAME_LIKE_RE = re.compile(r"^[\w\-.]+$")


async def save_artifact(
    *,
    type: ArtifactType,  # noqa: A002 — `type` is the natural field name; kwarg-only mitigates builtin shadowing
    label: str,
    content: str,
    source_path: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert an artifact; returns its id."""
    async with get_connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO artifacts (type, label, source_path, content, summary, metadata_json, included)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (type, label, source_path, content, summary, json.dumps(metadata or {})),
        )
        await conn.commit()
        return cur.lastrowid


async def load_artifact(artifact_id: int) -> ArtifactRecord | None:
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT id, type, label, source_path, content, summary, metadata_json, "
            "included, created_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_record(row)


async def list_artifacts(
    type: ArtifactType | None = None,  # noqa: A002 — field name consistency with save_artifact
    included_only: bool = False,
) -> list[ArtifactRecord]:
    query = (
        "SELECT id, type, label, source_path, content, summary, metadata_json, "
        "included, created_at FROM artifacts WHERE 1=1"
    )
    params: list[Any] = []
    if type is not None:
        query += " AND type = ?"
        params.append(type)
    if included_only:
        query += " AND included = 1"
    query += " ORDER BY id"
    async with get_connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]


async def load_artifacts_by_ids(artifact_ids: list[int]) -> list[ArtifactRecord]:
    """Fetch a subset of artifacts by id, preserving DB order (id ascending)."""
    if not artifact_ids:
        return []
    placeholders = ",".join("?" * len(artifact_ids))
    async with get_connection() as conn:
        cur = await conn.execute(
            f"""
            SELECT id, type, label, source_path, content, summary, metadata_json,
                   included, created_at
            FROM artifacts WHERE id IN ({placeholders})
            ORDER BY id
            """,  # noqa: S608 — placeholder count bound from artifact_ids
            artifact_ids,
        )
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]


async def delete_artifact(artifact_id: int) -> bool:
    """Hard delete. Returns True if a row was removed."""
    async with get_connection() as conn:
        cur = await conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        await conn.commit()
        return cur.rowcount > 0


async def set_included(artifact_id: int, included: bool) -> bool:
    """Toggle `included`. Excluded artifacts are ignored by the writing pipeline."""
    async with get_connection() as conn:
        cur = await conn.execute(
            "UPDATE artifacts SET included = ? WHERE id = ?",
            (1 if included else 0, artifact_id),
        )
        await conn.commit()
        return cur.rowcount > 0


def _row_to_record(row: Any) -> ArtifactRecord:
    return {
        "id": row["id"],
        "type": row["type"],
        "label": row["label"],
        "source_path": row["source_path"],
        "content": row["content"],
        "summary": row["summary"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "included": bool(row["included"]),
        "created_at": row["created_at"],
    }


def citation_label(artifact: ArtifactRecord) -> str:
    """Short inline citation.

    For code artifacts whose label is filename-like (`auth.py`, `utils-v2.ts`),
    the label is used verbatim — `[C:auth.py]` reads better in prose than
    `[C:7]`. For all other types, and for code with spaces / punctuation in
    the label, the numeric id is used: `[I:3]`, `[D:12]`.

    The primary-sources appendix expands either form back to the full record.
    """
    prefix = {
        "interview": "I",
        "code": "C",
        "document": "D",
        "note": "N",
        "dataset": "DS",
    }[artifact["type"]]
    label = artifact.get("label")
    if artifact["type"] == "code" and label and _FILENAME_LIKE_RE.match(label):
        return f"[{prefix}:{label}]"
    return f"[{prefix}:{artifact['id']}]"
