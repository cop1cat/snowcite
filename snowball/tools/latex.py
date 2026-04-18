"""LaTeX/PDF generation tools."""

import json
import subprocess
from pathlib import Path
from typing import Any

from snowball.app import mcp
from snowball.bibtex import generate_bibtex
from snowball.db import get_connection

TEX_TEMPLATE = r"""\documentclass[12pt,a4paper]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage[T1]{{fontenc}}
\usepackage{{hyperref}}
\usepackage[backend=biber,style={bib_style}]{{biblatex}}
\addbibresource{{references.bib}}

\title{{{title}}}
\author{{{author}}}
\date{{\today}}

\begin{{document}}
\maketitle

{sections}

\printbibliography
\end{{document}}
"""


@mcp.tool()
async def write_latex(
    sections: list[dict[str, str]],
    title: str,
    author: str,
    bibliography_style: str = "plain",
    output_dir: str = "data",
) -> dict[str, str]:
    """Build .tex + .bib from approved papers. Section content is provided ready by Claude.

    Each section: {"title": str, "content": str}.
    The .bib is auto-generated from all approved papers' bibtex or metadata.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    sections_tex = "\n\n".join(
        f"\\section{{{s['title']}}}\n{s['content']}" for s in sections
    )
    tex_content = TEX_TEMPLATE.format(
        title=title,
        author=author,
        bib_style=bibliography_style,
        sections=sections_tex,
    )
    tex_path = out / "review.tex"
    tex_path.write_text(tex_content, encoding="utf-8")

    async with get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT p.title, p.authors_json, p.year, p.venue, p.doi, p.bibtex, p.source
            FROM papers p
            JOIN reviews r ON r.paper_id = p.id
            WHERE r.status = 'approved'
            ORDER BY p.year, p.id
            """
        )
        rows = await cur.fetchall()

    bib_entries: list[str] = []
    for row in rows:
        if row["bibtex"]:
            bib_entries.append(row["bibtex"])
        else:
            authors = json.loads(row["authors_json"])
            bib_entries.append(generate_bibtex(
                title=row["title"],
                authors=authors,
                year=row["year"],
                venue=row["venue"],
                doi=row["doi"],
                source=row["source"],
            ))

    bib_path = out / "references.bib"
    bib_path.write_text("\n\n".join(bib_entries), encoding="utf-8")

    return {"tex_path": str(tex_path), "bib_path": str(bib_path)}


@mcp.tool()
async def compile_pdf(tex_path: str) -> dict[str, Any]:
    """Compile .tex via tectonic. Returns {pdf_path, success, log}."""
    tex = Path(tex_path)
    if not tex.exists():
        return {"pdf_path": "", "success": False, "log": f"File not found: {tex_path}"}

    result = subprocess.run(
        ["tectonic", str(tex)],
        capture_output=True,
        text=True,
        timeout=300,
    )

    pdf_path = tex.with_suffix(".pdf")
    return {
        "pdf_path": str(pdf_path) if pdf_path.exists() else "",
        "success": result.returncode == 0,
        "log": result.stdout + result.stderr,
    }
