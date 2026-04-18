# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/0.3.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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

[0.1.0]: https://github.com/cop1cat/snowball-mcp/releases/tag/v0.1.0
