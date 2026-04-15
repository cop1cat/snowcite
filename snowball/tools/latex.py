from typing import Any

from snowball.app import mcp


@mcp.tool()
async def write_latex(
    sections: list[dict[str, str]],
    title: str,
    author: str,
    bibliography_style: str = "plain",
    output_dir: str = "data",
) -> dict[str, str]:
    """Build .tex + .bib from approved papers. Section content is provided ready by Claude."""
    raise NotImplementedError("Phase 6")


@mcp.tool()
async def compile_pdf(tex_path: str) -> dict[str, Any]:
    """Compile via tectonic. Returns {pdf_path, success, log}."""
    raise NotImplementedError("Phase 6")
