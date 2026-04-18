# snowcite

MCP server for systematic literature review. Search arXiv / Semantic Scholar / OpenAlex / Crossref / PubMed, snowball through citations, review papers through chat, generate Typst or LaTeX documents, compile to PDF.

!!! info "No UI, no browser"
    Review happens in chat. Claude reads abstracts in batches, pre-filters autonomously, surfaces borderline cases to you. Architectural choice — see [Workflow](workflow.md).

## What makes it different

- **Draft-first writing** — outline → skeleton → section-by-section expand with drift checks. No 2500-word walls of text dropped on you to review.
- **Two independent review subagents** — academic-reviewer critiques claims and citations, humanizer cleans language. They run with fresh context, like external reviewers.
- **Projects live in directories** — `.snowcite/` alongside your source files, like `.git`. `cd` to switch projects. `git clone` to share.
- **Typst first** — Cyrillic works out of the box, no font or biber dance. LaTeX available for strict ГОСТ / existing vuz templates.
- **Multi-discipline** — automatic source routing: STEM gets arXiv, medicine gets PubMed, everyone gets OpenAlex / Semantic Scholar / Crossref.

## Next

- [Installation](installation.md)
- [Getting started](getting-started.md) — your first review
- [Workflow](workflow.md) — detailed loop
- [Backends](backends.md) — Typst vs LaTeX
- [Troubleshooting](troubleshooting.md) — Cyrillic, safety refusals, tectonic quirks
