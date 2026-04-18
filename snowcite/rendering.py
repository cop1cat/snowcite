"""Backend-aware document fragment renderers.

PRISMA flow diagrams and overview tables have to be emitted differently for
LaTeX (TikZ + longtable) vs Typst (`#figure` + `#table`). Keeping the
dispatch here — rather than spread across `writing.py` — makes the
per-backend code paths easy to find when adding new standards.
"""

from typing import Any

from snowcite.artifacts import citation_label
from snowcite.bibliography import escape_latex
from snowcite.types import ArtifactRecord, Backend


# ─── PRISMA flow ────────────────────────────────────────────────────────────


def prisma_flow(counts: dict[str, Any], backend: Backend) -> str:
    """Build a PRISMA figure snippet in the target backend's syntax."""
    if backend == "latex":
        return _prisma_tikz(counts)
    return _prisma_typst(counts)


def _prisma_tikz(counts: dict[str, Any]) -> str:
    excluded_lines = "; ".join(
        f"{e['count']} {e['reason']}" for e in counts["excluded_by_reason"][:6]
    )
    return (
        r"\begin{figure}[h]\centering"
        "\n"
        r"\begin{tikzpicture}[node distance=1.2cm, box/.style={rectangle, draw, minimum width=5cm}]"
        "\n"
        f"\\node[box] (id) {{Identified: {counts['identified']}}};\n"
        f"\\node[box, below=of id] (sc) {{Screened: {counts['screened']}}};\n"
        f"\\node[box, below=of sc] (ex) {{Excluded: {counts['excluded_total']} ({excluded_lines})}};\n"
        f"\\node[box, below=of ex] (inc) {{Included: {counts['included']}}};\n"
        r"\draw[->] (id) -- (sc); \draw[->] (sc) -- (ex); \draw[->] (sc) -- (inc);"
        "\n"
        r"\end{tikzpicture}"
        "\n"
        r"\caption{PRISMA flow.}\end{figure}"
    )


def _prisma_typst(counts: dict[str, Any]) -> str:
    excluded = "; ".join(f"{e['count']} {e['reason']}" for e in counts["excluded_by_reason"][:6])
    return (
        "#figure(caption: [PRISMA flow.])[\n"
        "  #table(columns: 1, stroke: 0.5pt,\n"
        f"    [*Identified:* {counts['identified']}],\n"
        f"    [*Screened:* {counts['screened']}],\n"
        f"    [*Excluded:* {counts['excluded_total']} ({excluded})],\n"
        f"    [*Included:* {counts['included']}],\n"
        "  )\n"
        "]"
    )


# ─── Overview table ─────────────────────────────────────────────────────────


def overview_table(
    records: list[dict[str, Any]],
    columns: list[str],
    backend: Backend,
) -> str:
    """Render a table of approved papers using the chosen backend's syntax."""
    if backend == "latex":
        return _overview_longtable(records, columns)
    return _overview_typst_table(records, columns)


def _overview_longtable(records: list[dict[str, Any]], columns: list[str]) -> str:
    header = " & ".join(c.capitalize() for c in columns) + r" \\" + "\n" + r"\hline"
    body_lines: list[str] = []
    for rec in records:
        cells = [escape_latex(str(rec.get(c, "") or "")) for c in columns]
        body_lines.append(" & ".join(cells) + r" \\")
    col_spec = "l" * len(columns)
    return (
        r"\begin{longtable}{"
        + col_spec
        + "}\n"
        + header
        + "\n"
        + "\n".join(body_lines)
        + "\n"
        + r"\end{longtable}"
    )


def _overview_typst_table(records: list[dict[str, Any]], columns: list[str]) -> str:
    header = ", ".join(f"[*{c.capitalize()}*]" for c in columns)
    rows: list[str] = []
    for rec in records:
        cells = ", ".join(f"[{rec.get(c, '') or ''}]" for c in columns)
        rows.append(cells)
    cols_arg = f"columns: {len(columns)}"
    all_cells = ",\n  ".join([header, *rows])
    return f"#table({cols_arg}, stroke: 0.5pt,\n  {all_cells}\n)"


# ─── Code-artifact inclusion ────────────────────────────────────────────────


def include_code(artifact: ArtifactRecord, backend: Backend) -> str:
    """Emit a backend-specific code-listing snippet for a code artifact.

    Prefers `source_path` (so `\\lstinputlisting` / `raw(read())` track the
    file on disk); falls back to inlining the stored content otherwise.
    """
    lang_hint = artifact.get("metadata", {}).get("language", "")
    if backend == "latex":
        if artifact.get("source_path"):
            return (
                f"\\lstinputlisting[caption={{{escape_latex(artifact['label'])}}}]"
                f"{{{artifact['source_path']}}}"
            )
        body = artifact["content"]
        return (
            f"\\begin{{lstlisting}}[caption={{{escape_latex(artifact['label'])}}}]\n"
            f"{body}\n"
            f"\\end{{lstlisting}}"
        )
    # Typst: caption content goes in markup `[...]`; file paths and lang in
    # string literals. Escape `]` inside label (markup terminator) and `"` /
    # `\` inside quoted strings. For inline content we use a fenced raw block
    # — `raw("...")` accepts only single-line strings reliably, a fenced
    # block handles multi-line verbatim.
    label = _typst_markup_escape(artifact["label"])
    if artifact.get("source_path"):
        src = _typst_string_escape(artifact["source_path"])
        lang = _typst_string_escape(lang_hint)
        return f'#figure(caption: [{label}], raw(read("{src}"), lang: "{lang}"))'
    fence = _fenced_raw(artifact["content"])
    lang_tag = lang_hint or ""
    return f"#figure(caption: [{label}])[{fence.replace('{lang}', lang_tag)}]"


def _typst_markup_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _typst_string_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _fenced_raw(content: str) -> str:
    """Wrap `content` in a Typst raw fence with enough backticks to be unique.

    Typst raw fences use 3+ backticks. If the content itself has a run of N
    backticks, the fence must be at least N+1. Shape: ```<lang>\\n<content>\\n```.
    """
    max_run = 0
    run = 0
    for ch in content:
        if ch == "`":
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    fence_len = max(3, max_run + 1)
    fence = "`" * fence_len
    # `{lang}` placeholder filled by the caller — leaves the fence composable
    # without threading lang_hint here.
    return f"{fence}{{lang}}\n{content}\n{fence}"


# ─── Primary-sources appendix ───────────────────────────────────────────────


def primary_sources_appendix(artifacts: list[ArtifactRecord], backend: Backend) -> str:
    """Render an appendix listing every included artifact with label, type, summary.

    This is the Primary-sources counterpart to the bibliography. Empty string
    if no artifacts are included (caller can skip inserting anything).
    """
    included = [a for a in artifacts if a.get("included", True)]
    if not included:
        return ""
    if backend == "latex":
        return _primary_sources_latex(included)
    return _primary_sources_typst(included)


def _primary_sources_latex(items: list[ArtifactRecord]) -> str:
    lines = [r"\section*{Primary sources}", r"\begin{itemize}"]
    for a in items:
        label = escape_latex(a["label"])
        summary = escape_latex(a.get("summary") or "")
        cite = _citation_token(a)
        entry = f"  \\item \\textbf{{{cite}}} {label} ({a['type']})"
        if summary:
            entry += f" --- {summary}"
        lines.append(entry)
    lines.append(r"\end{itemize}")
    return "\n".join(lines)


def _primary_sources_typst(items: list[ArtifactRecord]) -> str:
    lines = ["= Primary sources", ""]
    for a in items:
        cite = _citation_token(a)
        summary = a.get("summary") or ""
        dash = f" — {summary}" if summary else ""
        lines.append(f"- *{cite}* {a['label']} ({a['type']}){dash}")
    return "\n".join(lines)


def _citation_token(a: ArtifactRecord) -> str:
    # Delegate so appendix tokens match what `citation_label()` emits at import.
    return citation_label(a)
