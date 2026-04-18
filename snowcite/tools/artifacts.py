"""MCP tools for managing research artifacts (interviews, code, notes, etc.).

Thin wrappers over `snowcite.artifacts` — the heavy lifting is in the
persistence module; these expose the Claude-facing surface.
"""

from pathlib import Path
from typing import Any

from snowcite import artifacts
from snowcite.app import mcp
from snowcite.types import ArtifactType


# 200k characters is roughly a 1-hour interview transcript or a small
# source file. Big enough for most materials, small enough to refuse a
# runaway import. Callers can pre-trim or split if they hit the ceiling.
_MAX_ARTIFACT_CHARS = 200_000
# UTF-8 text is at most 4 bytes per char. Use that as the upper bound to
# short-circuit before reading a huge file into memory.
_MAX_ARTIFACT_BYTES = _MAX_ARTIFACT_CHARS * 4


@mcp.tool()
async def import_artifact(
    path: str,
    type: ArtifactType,  # noqa: A002 — field name consistency across artifact API
    label: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read a text file from disk and register it as a research artifact.

    `path`: absolute or project-relative path to a text file.
    `type`: one of `interview`, `code`, `document`, `note`, `dataset`.
    `label`: short human-readable name (default: the file basename).
    `summary`: one-sentence gloss that will be shown in the Primary-sources
      appendix. Optional, but strongly recommended — this is what the reader
      sees without the full content.
    `metadata`: free-form JSON for participant ids, tags, anonymisation flags
      (e.g. `{"participant": "P03", "consent": "written", "language": "ru"}`).

    Only text files are supported. Convert PDFs/docx with `pdftotext` /
    `pandoc` first, then import the resulting text.
    """
    file = Path(path)
    if not file.exists():
        return {"error": f"file not found: {path}"}

    # Cheap size probe before loading the file into memory.
    size_bytes = file.stat().st_size
    if size_bytes > _MAX_ARTIFACT_BYTES:
        return {
            "error": (
                f"file is {size_bytes} bytes; limit is ~{_MAX_ARTIFACT_BYTES} bytes "
                f"({_MAX_ARTIFACT_CHARS} chars). Split the file or trim first."
            )
        }

    try:
        content = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": f"file is not UTF-8 text: {path}. Convert to text first."}

    if len(content) > _MAX_ARTIFACT_CHARS:
        return {
            "error": (
                f"content exceeds {_MAX_ARTIFACT_CHARS} chars "
                f"({len(content)} given). Split the file or trim first."
            )
        }

    artifact_id = await artifacts.save_artifact(
        type=type,
        label=label or file.name,
        content=content,
        source_path=str(file.resolve()),
        summary=summary,
        metadata=metadata,
    )
    return {
        "id": artifact_id,
        "type": type,
        "label": label or file.name,
        "chars": len(content),
        "citation_label": artifacts.citation_label(
            {"id": artifact_id, "type": type}  # type: ignore[typeddict-item]
        ),
    }


@mcp.tool()
async def add_artifact_inline(
    type: ArtifactType,  # noqa: A002 — field name consistency across artifact API
    label: str,
    content: str,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register an artifact from a literal string (no file read).

    Handy for short notes, code snippets already in chat, or interview
    excerpts typed by the user. Same fields as `import_artifact`, minus the
    path.
    """
    if len(content) > _MAX_ARTIFACT_CHARS:
        return {"error": (f"content exceeds {_MAX_ARTIFACT_CHARS} chars ({len(content)} given).")}
    artifact_id = await artifacts.save_artifact(
        type=type,
        label=label,
        content=content,
        summary=summary,
        metadata=metadata,
    )
    return {
        "id": artifact_id,
        "type": type,
        "label": label,
        "chars": len(content),
        "citation_label": artifacts.citation_label(
            {"id": artifact_id, "type": type}  # type: ignore[typeddict-item]
        ),
    }


@mcp.tool()
async def list_artifacts(
    type: ArtifactType | None = None,  # noqa: A002
    included_only: bool = False,
) -> list[dict[str, Any]]:
    """Browse artifacts. Returns metadata + summary (no content bodies).

    Use `get_artifact(id)` for the full content when you need to quote or
    analyse it.
    """
    records = await artifacts.list_artifacts(type=type, included_only=included_only)
    # Strip content from listings — keep the context lean.
    return [
        {
            "id": r["id"],
            "type": r["type"],
            "label": r["label"],
            "summary": r.get("summary"),
            "included": r["included"],
            "chars": len(r["content"]),
            "metadata": r.get("metadata", {}),
            "created_at": r["created_at"],
        }
        for r in records
    ]


@mcp.tool()
async def get_artifact(artifact_id: int) -> dict[str, Any] | None:
    """Full artifact record including the content body. Use for quoting."""
    record = await artifacts.load_artifact(artifact_id)
    return dict(record) if record is not None else None


@mcp.tool()
async def delete_artifact(artifact_id: int) -> dict[str, Any]:
    """Remove an artifact. Hard delete — use `set_artifact_included(False)` to
    exclude from the writing pipeline without losing it."""
    removed = await artifacts.delete_artifact(artifact_id)
    return {"deleted": removed, "id": artifact_id}


@mcp.tool()
async def set_artifact_included(artifact_id: int, included: bool) -> dict[str, Any]:
    """Toggle whether the writing pipeline considers this artifact.

    Excluded artifacts stay in the DB but do not appear in
    `prepare_section_for_review`, don't land in the Primary-sources appendix,
    and can't be picked up by automatic assignments.
    """
    updated = await artifacts.set_included(artifact_id, included)
    if not updated:
        return {"updated": False, "error": f"artifact {artifact_id} not found"}
    return {"updated": True, "id": artifact_id, "included": included}
