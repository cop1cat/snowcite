"""Document generation + PDF compilation.

Handles both LaTeX (via tectonic) and Typst (via the typst binary). Backend,
standard, and author can come from `project_metadata` once the user has
onboarded; callers also pass them explicitly for flexibility.
"""

import asyncio
from pathlib import Path
from typing import Any

from snowcite.app import mcp
from snowcite.bibliography import build_bibtex_document, generate_hayagriva
from snowcite.db import get_connection
from snowcite.logging import log
from snowcite.persistence import load_approved_papers
from snowcite.projects import require_project_root
from snowcite.templates import render_template
from snowcite.types import Backend


_EXT_TO_BACKEND: dict[str, Backend] = {".tex": "latex", ".typ": "typst"}
_COMPILE_TIMEOUT_SECONDS = 300
# Cap captured stderr so a misbehaving typst/tectonic pass can't flood memory.
_MAX_LOG_BYTES = 65_536


# ─── write_document ─────────────────────────────────────────────────────────


@mcp.tool()
async def write_document(
    sections: list[dict[str, str]],
    title: str,
    author: str,
    backend: Backend = "typst",
    standard: str = "plain",
    language: str = "ru",
    output_dir: str | None = None,
) -> dict[str, str]:
    """Render a review document (LaTeX or Typst) + bibliography from approved papers.

    `sections`: list of `{"title", "content"}` — section content must already be
      valid syntax for the chosen backend.

    `backend`: "typst" (default) or "latex".
    `standard`: template to use — "plain" / "gost" / ... (see templates/{backend}/).
    `language`: ISO code; LaTeX routes it to babel, Typst to `set text(lang:)`.
    `output_dir`: default is the project root so `.snowcite/` stays for DB only.
    """
    out = Path(output_dir) if output_dir else require_project_root()
    out.mkdir(parents=True, exist_ok=True)
    papers = await load_approved_papers()

    if backend == "latex":
        sections_rendered = "\n\n".join(
            f"\\section{{{s['title']}}}\n{s['content']}" for s in sections
        )
        babel_langs = {"ru": "russian,english", "en": "english"}.get(language, "english")
        variables = {
            "title": title,
            "author": author,
            "sections": sections_rendered,
            "babel_langs": babel_langs,
            "bib_style": "numeric" if standard == "plain" else "gost-numeric",
        }
        body = render_template("latex", standard, variables)
        doc_path = out / "review.tex"
        bib_path = out / "references.bib"
        bib_path.write_text(build_bibtex_document(list(papers)), encoding="utf-8")
    else:
        sections_rendered = "\n\n".join(f"= {s['title']}\n\n{s['content']}" for s in sections)
        csl = {"plain": "ieee", "gost": "gost-r-705-2008-numeric"}.get(standard, "ieee")
        variables = {
            "title": title,
            "author": author,
            "sections": sections_rendered,
            "lang": language,
            "csl_style": csl,
        }
        body = render_template("typst", standard, variables)
        doc_path = out / "review.typ"
        bib_path = out / "references.yml"
        bib_path.write_text(generate_hayagriva(list(papers)), encoding="utf-8")

    doc_path.write_text(body, encoding="utf-8")
    return {
        "doc_path": str(doc_path),
        "bib_path": str(bib_path),
        "backend": backend,
        "standard": standard,
    }


# ─── compile_pdf ────────────────────────────────────────────────────────────


async def _run_subprocess(cmd: list[str], cwd: Path | None) -> tuple[int, str]:
    """Run `cmd`, return (returncode, captured_log). stdout is discarded — tectonic
    and typst write the PDF to disk; we only keep stderr, capped at
    `_MAX_LOG_BYTES` so a pathological run can't blow memory."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_COMPILE_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        return -1, f"compile timed out after {_COMPILE_TIMEOUT_SECONDS}s"

    if stderr is None:
        log_bytes = b""
    elif len(stderr) > _MAX_LOG_BYTES:
        log_bytes = stderr[:_MAX_LOG_BYTES] + b"\n... (truncated)"
    else:
        log_bytes = stderr
    return proc.returncode or 0, log_bytes.decode(errors="replace")


@mcp.tool()
async def compile_pdf(doc_path: str) -> dict[str, Any]:
    """Compile a LaTeX or Typst source to PDF.

    Backend is inferred from the file extension: `.tex` → tectonic,
    `.typ` → typst. PDF lands next to the source.
    """
    src = Path(doc_path).resolve()
    if not src.exists():
        return {"pdf_path": "", "success": False, "log": f"file not found: {doc_path}"}

    backend = _EXT_TO_BACKEND.get(src.suffix)
    if backend is None:
        return {
            "pdf_path": "",
            "success": False,
            "log": f"unknown source extension {src.suffix!r} (expected .tex or .typ)",
        }

    cmd = ["tectonic", str(src)] if backend == "latex" else ["typst", "compile", str(src)]
    log.info("compiling %s with %s", src, cmd[0])
    returncode, logs = await _run_subprocess(cmd, cwd=src.parent)
    pdf = src.with_suffix(".pdf")
    return {
        "pdf_path": str(pdf) if pdf.exists() else "",
        "success": returncode == 0,
        "log": logs,
        "backend": backend,
    }


# ─── set_backend ────────────────────────────────────────────────────────────


@mcp.tool()
async def set_backend(
    new_backend: Backend,
    confirm_wipe_sections: bool = False,
) -> dict[str, Any]:
    """Switch the project's document backend (`typst` ↔ `latex`).

    Existing section_content is written in the source backend's syntax and
    won't compile under the new one — this tool refuses to switch unless the
    user has explicitly opted into wiping expanded sections.

    Flow:
    1. Call with `confirm_wipe_sections=False` (default) to see what would be
       lost. Returns a `needs_wipe` count; nothing is modified.
    2. If the user agrees, call again with `confirm_wipe_sections=True` to
       delete `section_content` rows and update `project_metadata.backend`.
       `outline` and `skeleton` are preserved — you re-expand sections under
       the new backend.
    """
    async with get_connection() as conn:
        cur = await conn.execute("SELECT backend FROM project_metadata WHERE id = 1")
        row = await cur.fetchone()
        current = row["backend"] if row else None

        cur = await conn.execute("SELECT COUNT(*) FROM section_content")
        section_count = (await cur.fetchone())[0]

        if current == new_backend:
            return {"changed": False, "backend": new_backend, "reason": "already set"}

        if section_count > 0 and not confirm_wipe_sections:
            return {
                "changed": False,
                "needs_wipe": section_count,
                "current_backend": current,
                "proposed_backend": new_backend,
                "message": (
                    f"{section_count} expanded section(s) exist in {current!r} "
                    f"syntax; switching to {new_backend!r} will make them "
                    f"uncompilable. Call again with confirm_wipe_sections=True "
                    f"to clear section_content (outline + skeleton survive)."
                ),
            }

        if section_count > 0:
            await conn.execute("DELETE FROM section_content")
        await conn.execute(
            """
            INSERT INTO project_metadata (id, backend, updated_at)
            VALUES (1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                backend = excluded.backend,
                updated_at = CURRENT_TIMESTAMP
            """,
            (new_backend,),
        )
        await conn.commit()

    return {
        "changed": True,
        "backend": new_backend,
        "previous": current,
        "sections_wiped": section_count,
    }
