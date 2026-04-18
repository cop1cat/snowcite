"""Export approved bibliography and the document to external formats.

- `export_bibtex` — `.bib` from the current approved set
- `export_ris` — RIS flavored for Mendeley / EndNote import
- `export_docx` — shells out to pandoc to convert the rendered document
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any

from snowcite.app import mcp
from snowcite.bibliography import build_bibtex_document
from snowcite.logging import log
from snowcite.persistence import ApprovedPaper, load_approved_papers
from snowcite.projects import require_project_root


_EXPORT_TIMEOUT_SECONDS = 120


def _default_output_path(name: str) -> Path:
    return require_project_root() / name


# ─── BibTeX ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def export_bibtex(output_path: str | None = None) -> dict[str, Any]:
    """Write a .bib file for the approved set. Reuses per-paper bibtex when present."""
    papers = await load_approved_papers()
    path = Path(output_path) if output_path else _default_output_path("references.bib")
    path.write_text(build_bibtex_document(list(papers)) + "\n", encoding="utf-8")
    return {"path": str(path), "entries": len(papers)}


# ─── RIS ────────────────────────────────────────────────────────────────────

# Minimal RIS entries — TY + TI + AU + PY + JO + DO + AB + ER. Most reference
# managers (Mendeley, EndNote, Zotero) accept this subset for import.


def _ris_entry(paper: ApprovedPaper) -> str:
    lines = [f"TY  - {'GEN' if paper['source'] == 'arxiv' else 'JOUR'}"]
    lines.append(f"TI  - {paper['title']}")
    for a in paper["authors"]:
        lines.append(f"AU  - {a}")
    if paper["year"]:
        lines.append(f"PY  - {paper['year']}")
    if paper["venue"]:
        lines.append(f"JO  - {paper['venue']}")
    if paper["doi"]:
        lines.append(f"DO  - {paper['doi']}")
    if paper["abstract"]:
        lines.append(f"AB  - {paper['abstract']}")
    lines.append("ER  - ")
    return "\n".join(lines)


@mcp.tool()
async def export_ris(output_path: str | None = None) -> dict[str, Any]:
    """Write a RIS file for Mendeley / EndNote import."""
    papers = await load_approved_papers()
    body = "\n\n".join(_ris_entry(p) for p in papers) + "\n"
    path = Path(output_path) if output_path else _default_output_path("references.ris")
    path.write_text(body, encoding="utf-8")
    return {"path": str(path), "entries": len(papers)}


# ─── DOCX (via pandoc) ──────────────────────────────────────────────────────


@mcp.tool()
async def export_docx(source_path: str, output_path: str | None = None) -> dict[str, Any]:
    """Convert `review.tex` or `review.typ` to `.docx` via pandoc.

    Pandoc is the bridge; humanities users commonly need Word-compatible
    output for supervisor review. Bibliography citations may degrade to plain
    text — that's a pandoc limitation.
    """
    if shutil.which("pandoc") is None:
        return {
            "success": False,
            "error": "pandoc not found on PATH — `brew install pandoc` or equivalent",
        }
    src = Path(source_path).resolve()
    if not src.exists():
        return {"success": False, "error": f"file not found: {source_path}"}

    dst = Path(output_path) if output_path else src.with_suffix(".docx")
    cmd = ["pandoc", str(src), "-o", str(dst)]
    log.info("pandoc %s → %s", src, dst)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_EXPORT_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        return {"success": False, "error": f"pandoc timed out after {_EXPORT_TIMEOUT_SECONDS}s"}

    combined = stdout.decode(errors="replace") + stderr.decode(errors="replace")
    if proc.returncode != 0:
        return {"success": False, "error": f"pandoc exit {proc.returncode}", "log": combined}
    return {"success": True, "path": str(dst), "log": combined or None}
