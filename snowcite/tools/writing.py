"""Draft-first writing pipeline: outline → skeleton → expand per section → polish.

Each stage persists to its own table (`outline`, `skeleton`, `section_content`)
so `/clear` and session restarts don't lose work. Claude drives the user-facing
approval cycle (via AskUserQuestion); these tools only read/write and flag drift.
"""

import json
from typing import Any

from snowcite.app import mcp
from snowcite.artifacts import (
    list_artifacts as _list_artifacts_all,
    load_artifact,
    load_artifacts_by_ids,
)
from snowcite.db import get_connection
from snowcite.persistence import load_approved_papers, load_papers_by_ids
from snowcite.rendering import (
    include_code,
    overview_table,
    primary_sources_appendix,
    prisma_flow,
)
from snowcite.types import Backend, DriftWarning, OutlineSection


# ─── Helpers ────────────────────────────────────────────────────────────────


_SINGLETON_TABLES = ("outline", "skeleton")


def _word_count(text: str) -> int:
    return len(text.split())


async def _load_singleton(table: str) -> dict[str, Any] | None:
    """Read outline or skeleton (singleton tables) and parse sections_json."""
    if table not in _SINGLETON_TABLES:
        raise ValueError(f"unknown singleton table: {table!r}")
    # Static branch avoids an f-string SQL (lint-friendly) and keeps the lookup
    # transparent — there are only two singleton tables.
    async with get_connection() as conn:
        if table == "outline":
            cur = await conn.execute(
                "SELECT id, sections_json, approved, created_at, updated_at "
                "FROM outline WHERE id = 1"
            )
        else:
            cur = await conn.execute(
                "SELECT id, sections_json, approved, created_at, updated_at "
                "FROM skeleton WHERE id = 1"
            )
        row = await cur.fetchone()
    if row is None:
        return None
    data = {k: row[k] for k in row.keys()}
    data["sections"] = json.loads(data.pop("sections_json"))
    return data


# ─── Outline ────────────────────────────────────────────────────────────────


@mcp.tool()
async def save_outline(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist the proposed outline (unapproved) for the document.

    Each section is `{"name", "target_words", "paper_ids": [...]}`. Overwrites
    any prior outline in this project; that's intentional — the user iterates
    by re-proposing, not by editing.
    """
    async with get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO outline (id, sections_json, approved, updated_at)
            VALUES (1, ?, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                sections_json = excluded.sections_json,
                approved = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (json.dumps(sections),),
        )
        await conn.commit()
    return {"saved": True, "sections": len(sections), "approved": False}


@mcp.tool()
async def get_outline() -> dict[str, Any] | None:
    """Return the current outline, or None if none proposed yet."""
    return await _load_singleton("outline")


@mcp.tool()
async def approve_outline() -> dict[str, Any]:
    """Mark the current outline as approved by the user. Required before write_skeleton."""
    async with get_connection() as conn:
        cur = await conn.execute("SELECT 1 FROM outline WHERE id = 1")
        if await cur.fetchone() is None:
            return {"approved": False, "error": "no outline to approve — run save_outline first"}
        await conn.execute(
            "UPDATE outline SET approved = 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
        await conn.commit()
    return {"approved": True}


# ─── Skeleton ───────────────────────────────────────────────────────────────


@mcp.tool()
async def save_skeleton(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist the 3-5-sentence-per-section skeleton draft.

    Each section is `{"name", "draft"}`. Names should match the approved outline;
    a mismatch returns a warning but we save anyway — Claude can decide whether
    to re-propose the outline or continue.
    """
    outline = await _load_singleton("outline")
    warnings: list[str] = []
    if outline:
        if not outline.get("approved"):
            warnings.append("outline is not yet approved — approve_outline first to avoid drift")
        outline_names = {s.get("name") for s in outline.get("sections", [])}
        skeleton_names = {s.get("name") for s in sections}
        missing = outline_names - skeleton_names
        extra = skeleton_names - outline_names
        if missing:
            warnings.append(f"skeleton missing outline sections: {sorted(missing)}")
        if extra:
            warnings.append(f"skeleton has sections not in outline: {sorted(extra)}")

    async with get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO skeleton (id, sections_json, approved, updated_at)
            VALUES (1, ?, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                sections_json = excluded.sections_json,
                approved = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (json.dumps(sections),),
        )
        await conn.commit()
    result = {"saved": True, "sections": len(sections), "approved": False}
    if warnings:
        result["warnings"] = warnings
    return result


@mcp.tool()
async def get_skeleton() -> dict[str, Any] | None:
    """Return the current skeleton (3-5-sentence draft per section), or None
    if none proposed yet. Counterpart to `get_outline`."""
    return await _load_singleton("skeleton")


@mcp.tool()
async def approve_skeleton() -> dict[str, Any]:
    """Mark skeleton as approved. Required before expand_section calls."""
    async with get_connection() as conn:
        cur = await conn.execute("SELECT 1 FROM skeleton WHERE id = 1")
        if await cur.fetchone() is None:
            return {"approved": False, "error": "no skeleton to approve — run save_skeleton first"}
        await conn.execute(
            "UPDATE skeleton SET approved = 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
        await conn.commit()
    return {"approved": True}


# ─── Expanded section content + drift check ────────────────────────────────

# A section's word count may exceed or undershoot its outline target. Allow up to
# ±30% of the target, and always tolerate at least 100 words of absolute swing
# (so a 200-word section has a usable window).
_DRIFT_TOLERANCE_FRACTION = 0.30
_DRIFT_TOLERANCE_ABSOLUTE = 100


def _check_drift(
    outline: dict[str, Any] | None,
    name: str,
    content: str,
) -> list[DriftWarning]:
    """Compute drift warnings for `content` vs. the outline entry for `name`."""
    warnings: list[DriftWarning] = []
    if outline is None:
        warnings.append({"severity": "warn", "kind": "no_outline", "detail": "no outline saved"})
        return warnings
    sections: list[OutlineSection] = outline.get("sections", [])
    target_entry = next((s for s in sections if s.get("name") == name), None)
    if target_entry is None:
        warnings.append(
            {
                "severity": "high",
                "kind": "unknown_section",
                "detail": f"section {name!r} not in outline",
            }
        )
        return warnings
    target_words = target_entry.get("target_words")
    actual_words = _word_count(content)
    if target_words:
        tolerance = max(_DRIFT_TOLERANCE_ABSOLUTE, int(target_words * _DRIFT_TOLERANCE_FRACTION))
        if abs(actual_words - target_words) > tolerance:
            warnings.append(
                {
                    "severity": "warn",
                    "kind": "word_count",
                    "detail": (
                        f"{actual_words} words vs target {target_words} (tolerance ±{tolerance})"
                    ),
                }
            )
    return warnings


@mcp.tool()
async def check_section_drift(name: str, content: str) -> dict[str, Any]:
    """Report drift warnings for a draft expansion without saving it.

    Claude should call this before `save_section` and surface the result to the
    user if anything non-empty comes back — they may want to shrink/grow the
    section or adjust the outline.
    """
    outline = await _load_singleton("outline")
    warnings = _check_drift(outline, name, content)
    return {
        "name": name,
        "word_count": _word_count(content),
        "warnings": warnings,
        "has_drift": bool(warnings),
    }


@mcp.tool()
async def save_section(name: str, content: str) -> dict[str, Any]:
    """Persist expanded content for one section. Increments version on re-save.

    Drift-checking is a separate tool (`check_section_drift`) so Claude can ask
    the user before persisting; this tool just writes whatever it was given.
    """
    async with get_connection() as conn:
        cur = await conn.execute("SELECT version FROM section_content WHERE name = ?", (name,))
        row = await cur.fetchone()
        next_version = (row["version"] + 1) if row else 1
        await conn.execute(
            """
            INSERT INTO section_content (name, content, word_count, version, polished, updated_at)
            VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET
                content = excluded.content,
                word_count = excluded.word_count,
                version = ?,
                polished = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (name, content, _word_count(content), next_version, next_version),
        )
        await conn.commit()
    return {
        "saved": True,
        "name": name,
        "version": next_version,
        "word_count": _word_count(content),
    }


@mcp.tool()
async def regenerate_section_brief(name: str, feedback: str) -> dict[str, Any]:
    """Bundle the context Claude needs to rewrite a section given user feedback.

    Does NOT write — returns the current section content, the outline entry,
    assigned paper abstracts, and the user's feedback string so Claude can
    produce a revision. Persist the result via `save_section(name, revision)`.

    Use this instead of free-hand rewriting: it guarantees the revision
    considers the outline target (word count + paper_ids) and has the
    feedback threaded through.
    """
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT content, word_count, version, polished FROM section_content WHERE name = ?",
            (name,),
        )
        row = await cur.fetchone()
        if row is None:
            return {"error": f"section {name!r} not found — run save_section first"}
        current = {k: row[k] for k in row.keys()}

        cur = await conn.execute("SELECT sections_json FROM outline WHERE id = 1")
        outline_row = await cur.fetchone()
    outline_entry: dict[str, Any] | None = None
    paper_ids: list[int] = []
    artifact_ids: list[int] = []
    if outline_row:
        outline_sections = json.loads(outline_row["sections_json"])
        outline_entry = next((s for s in outline_sections if s.get("name") == name), None)
        if outline_entry:
            paper_ids = outline_entry.get("paper_ids") or []
            artifact_ids = outline_entry.get("artifact_ids") or []

    assigned_papers = await load_papers_by_ids(paper_ids)
    assigned_artifacts = [
        dict(a) for a in await load_artifacts_by_ids(artifact_ids) if a["included"]
    ]

    return {
        "name": name,
        "current": current,
        "outline_entry": outline_entry,
        "assigned_papers": assigned_papers,
        "assigned_artifacts": assigned_artifacts,
        "feedback": feedback,
        "instructions": (
            "Produce a revised section that addresses the feedback. Respect the "
            "outline's target_words (±30%), cite only assigned_papers for "
            "scholarly sources, and reference assigned_artifacts (interviews, "
            "code, notes) using their citation_label (e.g. [I:3], [C:auth.py]). "
            "When done, call save_section(name, revised_content)."
        ),
    }


@mcp.tool()
async def get_section(name: str) -> dict[str, Any] | None:
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT name, content, word_count, version, polished, updated_at "
            "FROM section_content WHERE name = ?",
            (name,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


@mcp.tool()
async def list_sections() -> list[dict[str, Any]]:
    """All persisted sections with metadata (no content bodies). For session restore."""
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT name, word_count, version, polished, updated_at "
            "FROM section_content ORDER BY updated_at"
        )
        rows = await cur.fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


# ─── Polish ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def polish_section(name: str, polished_content: str) -> dict[str, Any]:
    """Save the polished version of one section (local pass — transitions within section).

    Sets `polished=1`. Claude runs this after expand_section when local cleanup is
    needed; it's distinct from `polish_document` which is a global pass.
    """
    wc = _word_count(polished_content)
    async with get_connection() as conn:
        cur = await conn.execute("SELECT version FROM section_content WHERE name = ?", (name,))
        row = await cur.fetchone()
        if row is None:
            return {"error": f"section {name!r} not found — run save_section first"}
        next_version = row["version"] + 1
        await conn.execute(
            """
            UPDATE section_content
            SET content = ?, word_count = ?, version = ?, polished = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE name = ?
            """,
            (polished_content, wc, next_version, name),
        )
        await conn.commit()
    return {"polished": True, "name": name, "version": next_version, "word_count": wc}


@mcp.tool()
async def polish_document(sections: list[dict[str, str]]) -> dict[str, Any]:
    """Save the global-pass polished versions for multiple sections at once.

    Each entry: `{"name", "content"}`. Sections not already saved are rejected —
    the global pass operates on content produced by `expand_section`.
    """
    updated: list[str] = []
    missing: list[str] = []
    async with get_connection() as conn:
        for s in sections:
            name = s["name"]
            cur = await conn.execute("SELECT version FROM section_content WHERE name = ?", (name,))
            row = await cur.fetchone()
            if row is None:
                missing.append(name)
                continue
            next_version = row["version"] + 1
            await conn.execute(
                """
                UPDATE section_content
                SET content = ?, word_count = ?, version = ?, polished = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
                """,
                (s["content"], _word_count(s["content"]), next_version, name),
            )
            updated.append(name)
        await conn.commit()
    return {"updated": updated, "missing": missing}


# ─── PRISMA flow + overview table ──────────────────────────────────────────


async def _prisma_counts() -> dict[str, Any]:
    """Aggregate review_history into the four PRISMA buckets.

    identified = #papers ever recorded (any status change entry)
    screened = #papers where latest status is anything except unreviewed
    excluded = #papers currently rejected, grouped by distinct reason
    included = #papers currently approved
    """
    async with get_connection() as conn:
        # identified: distinct papers that ever passed through review_history.
        cur = await conn.execute("SELECT COUNT(DISTINCT paper_id) FROM review_history")
        identified = (await cur.fetchone())[0]

        cur = await conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE status IN ('approved','rejected','maybe')"
        )
        screened = (await cur.fetchone())[0]

        cur = await conn.execute("SELECT COUNT(*) FROM reviews WHERE status = 'approved'")
        included = (await cur.fetchone())[0]

        cur = await conn.execute(
            """
            SELECT COALESCE(reason, '(no reason)') AS reason, COUNT(*) AS n
            FROM reviews WHERE status = 'rejected'
            GROUP BY reason ORDER BY n DESC
            """
        )
        excluded_by_reason = [
            {"reason": r["reason"], "count": r["n"]} for r in await cur.fetchall()
        ]

    excluded_total = sum(e["count"] for e in excluded_by_reason)
    return {
        "identified": identified,
        "screened": screened,
        "excluded_total": excluded_total,
        "excluded_by_reason": excluded_by_reason,
        "included": included,
    }


@mcp.tool()
async def generate_prisma_flow(backend: Backend = "typst") -> dict[str, Any]:
    """Build a PRISMA flow-diagram snippet from review_history.

    Returns backend-native source (TikZ for LaTeX, Typst figure for Typst)
    plus the raw counts, so Claude can paste the snippet into the document or
    summarize the counts in prose.
    """
    counts = await _prisma_counts()
    return {"backend": backend, "counts": counts, "snippet": prisma_flow(counts, backend)}


@mcp.tool()
async def include_code_artifact(artifact_id: int, backend: Backend = "typst") -> dict[str, Any]:
    """Emit a backend-specific code-listing snippet for a `code` artifact.

    Returned `snippet` is ready to paste into a section's content. Uses
    `\\lstinputlisting` for LaTeX and `#raw(read(...))` for Typst; both read
    the file live from disk, so code changes propagate at compile time.
    """
    a = await load_artifact(artifact_id)
    if a is None:
        return {"error": f"artifact {artifact_id} not found"}
    if a["type"] != "code":
        return {"error": f"artifact {artifact_id} is {a['type']!r}, not 'code'"}
    return {"backend": backend, "snippet": include_code(a, backend)}


@mcp.tool()
async def generate_primary_sources_appendix(backend: Backend = "typst") -> dict[str, Any]:
    """Appendix listing every included artifact — pair to the bibliography.

    Paste the returned `snippet` at the end of the document (after the main
    bibliography is fine). Empty `snippet` means no included artifacts.
    """
    items = await _list_artifacts_all(included_only=True)
    snippet = primary_sources_appendix(items, backend)
    return {"backend": backend, "snippet": snippet, "entries": len(items)}


@mcp.tool()
async def generate_overview_table(
    backend: Backend = "typst",
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """Render a table of approved papers with the chosen columns.

    `columns` can include any of `author`, `year`, `title`, `venue`, `doi`.
    Default: ["author", "year", "title", "venue"].
    """
    columns = columns or ["author", "year", "title", "venue"]
    papers = await load_approved_papers()
    records: list[dict[str, Any]] = [
        {
            "author": p["authors"][0].split()[-1] if p["authors"] else "",
            "year": p["year"],
            "title": p["title"],
            "venue": p["venue"] or "",
            "doi": p["doi"] or "",
        }
        for p in papers
    ]
    return {
        "backend": backend,
        "rows": len(records),
        "snippet": overview_table(records, columns, backend),
    }
