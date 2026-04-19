# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/0.3.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-04-19

### Added

- `save_thesis` / `get_thesis` tools — store a 2–5 paragraph statement of intent that anchors outline, search, and review in the optional thesis-first workflow.
- `gap_check` tool — flags substantive sentences (≥ 8 words by default) across stored sections that make no `[N]` citation. Candidates to cite or trim.
- `rewrite_citations` tool — bulk-remap `[N]` paper-id references across `section_content` through MCP, replacing the previous pattern of hand-patching generated `.tex` / `.typ` files.
- `estimate_pages` tool — renders the current draft to a temp PDF and reports actual page count, word total, and delta to `target_pages`.
- Target metrics on `project_metadata`: `target_pages`, `target_sources_min`, `target_sources_max`, `target_words`, `citation_density_target`. Surfaced in `get_session_state().targets`.
- `get_review_progress` now also reports writing stats (words, citations, citations per 100 words) and emits warnings when approved sources or citation density fall below targets.
- Self-contained ГОСТ Typst template (margins 30/15/20/20 mm, Times New Roman 14 pt, 1.5 line spacing, `gost-r-705-2008-numeric` bibliography). No longer depends on `@preview/modern-g7-32`.

### Fixed

- `write_document` now rewrites `[N]` paper-id citations in section content to the cite keys actually published in the bibliography (`\cite{key}` for LaTeX, `@key` for Typst). Previously the document and `.bib`/`.yml` used unrelated keys and the PDF failed to resolve references.
- Cite-key fallback for papers without structured authors derives the prefix from the first meaningful title word instead of a literal `unknown`.

### Changed

- CLAUDE.md template now documents the optional thesis-first flow, mandates a `get_low_confidence_reviews()` pass before `approve_outline()`, and explicitly bans `sed`/`grep` patching of generated compile artifacts after a failed `compile_pdf`.

### Migrated

- Additive `ALTER TABLE` on `project_metadata` to add the new target columns for pre-0.2 databases; runs on first `init_db` call.

## [0.1.0] — 2026-04-18

First public release of `snowcite` — an MCP server for systematic literature review.

### Added

- FastMCP-based MCP server, installed as the `snowcite` console command.
- Multi-source search: arXiv, Semantic Scholar, OpenAlex, Crossref, PubMed.
- Unified HTTP client (`sources/_http.py`) with rate limiting, exponential backoff, and `Retry-After` handling.
- DOI-first deduplication with a normalized-title fallback (fuzzy match ≥ 0.9).
- aiosqlite-backed storage in `<project>/.snowcite/papers.db`; project resolver walks up the directory tree.
- Review tools: `get_review_criteria`, `get_unreviewed_papers`, `get_paper_details`, `set_review_status`, `get_review_progress`, `get_low_confidence_reviews`.
- Rolling review summary (`save_review_summary` / `get_review_summary`) with a `stale` flag after snowball expansion.
- Snowball expansion: `expand_citations` over references and citations, with an arXiv → Semantic Scholar DOI fallback.
- Review statuses (`approved` / `maybe` / `rejected` / `unreviewed`) and an audit trail via `reviewed_by` (`auto_high` / `auto_low` / `user`) and a required `reason`.
- LaTeX and Typst generation from Jinja2 templates; BibTeX and Hayagriva bibliography assembly.
- PDF compilation via `tectonic` (LaTeX) and `typst` (Typst).
- External reference import: BibTeX and RIS (`import_refs`).
- Export, environment doctor checks, project init, and session management tools.
- Backend-aware PRISMA and overview diagram templates.
- MkDocs documentation, GitHub Actions CI (ruff + pytest), and a deploy workflow.

### Architectural decisions

- Review happens in chat — no web UI, no second terminal.
- All source access goes through `snowcite/sources/*` clients; direct `httpx` calls are disallowed.
- State transitions go through MCP tools only; direct edits to `papers.db` are unsupported.
- PDFs are not parsed — abstracts come from source APIs.
- Only `tectonic` and `typst` are supported; no system TeX Live.

[0.2.0]: https://github.com/cop1cat/snowball-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/cop1cat/snowball-mcp/releases/tag/v0.1.0
