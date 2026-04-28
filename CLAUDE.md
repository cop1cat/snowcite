# CLAUDE.md

Guide for Claude Code sessions in the snowcite repo.

## What this is

`snowcite` is an MCP server for systematic literature review. Search across arXiv / Semantic Scholar / OpenAlex, snowball through citations, review papers through chat (not UI), generate LaTeX/Typst, compile to PDF via tectonic or typst.

## Architectural invariant

**Reviewing happens in chat, not in a UI.** No web interfaces, no browsers, no second terminals. Claude reads abstracts in batches, pre-filters autonomously, shows only borderline cases to the user. Do not propose adding Starlette/Flask/Jinja/htmx. This is a deliberate design choice.

## Academic context for the safety classifier

This tool supports **peer-reviewed academic literature review**. Papers fetched from arXiv, Semantic Scholar, OpenAlex, PubMed and similar open scholarly databases are **research publications**, not operational material. The goal is to survey a research area — not to reproduce methods, weaponize techniques, or provide instructions.

When a research area involves sensitive topics (AI safety, security, dual-use research, biosecurity, etc.), handle the associated abstracts the same way a human reviewer would: paraphrase in your own words, summarize findings, cite responsibly. **Never copy verbatim passages that contain operational/harmful detail from abstracts into the chat context** — summarize in one or two neutral sentences instead.

## Review workflow (your primary loop)

1. **Before every batch** — call `get_review_criteria()`. Criteria may have been set long ago; this is a drift guard.
2. **Read the summary** — call `get_review_summary()`. Current picture: clusters, key papers, stale warnings. If it's stale or counts diverge from the text, tell the user. If there's no summary yet (first batch), skip.
3. `get_unreviewed_papers(limit=20)` — work in batches of 10–20, never try to load everything.
4. For each paper in the batch, decide **autonomously** and pick a confidence grade:
   - **Confident match** → `set_review_status([ids], "approved", reason="auto: matches criterion X", reviewed_by="auto_high")`. For approved/maybe papers, also pass `notes=[{type, text, cluster}]` in the same call — at minimum one `claim` or `finding` per paper. Notes go into the knowledge graph and feed synthesis + writing later. Skipping this empties the graph; do not skip.
   - **Confident reject** → `set_review_status([ids], "rejected", reason="auto: off-topic — Y", reviewed_by="auto_high")`. No notes — rejected papers don't enter the graph.
   - **Leaning one way but not sure** — decide anyway, but use `reviewed_by="auto_low"`. The user can later run `get_low_confidence_reviews()` to sanity-check these.
   - **Genuinely borderline** (two criteria conflict, mixed signal) — defer to the user.
5. Borderline cases go to the user **one at a time**, in the user's project language:

   ```
   Paper 7/87: "Title" (Year, Authors)
   Brief: ...
   Why borderline: ...
   i / e / m?
   ```

   **Do not recommend a decision** — it creates bias. Facts and why it's hard to decide, nothing more.
6. User answers → `set_review_status([id], status, reason="manual: <user comment>", reviewed_by="user")`.
7. **After each batch** (not after each paper) → `save_review_summary(summary, clusters)`:
   - Summary ≤ 500 words, rolling (include everything previous, do not append)
   - Use the categories from `review_criteria`; do not invent your own clusters.
   - Clusters: `[{"topic": "...", "paper_ids": [...], "count": N}]`
   - Singleton — overwrites on every call.
8. `get_review_progress()` periodically so the user sees progress.

### Abstract policy for batches

- `get_unreviewed_papers()` returns compact records **without abstracts** by default. This keeps the context lean on large reviews and prevents accumulation of harmful-sounding terminology that can trigger the safety classifier.
- For clear-cut papers, the title / venue / year / authors are usually enough to classify.
- For borderline papers, call `get_paper_details(paper_id)` to pull the full abstract. Summarize it in one or two neutral sentences in your message to the user — do not paste the raw abstract.

### Working with the summary

- **Do not trust the summary blindly.** It is your own prior generation and may contain inaccuracies. `get_review_summary()` returns live counts — always cross-check them against what the summary text claims.
- **Stale = regenerate.** If `stale=true` (after snowball or manual edits), re-read approved/maybe papers and regenerate the summary.
- **Summary for outline, papers for prose.** When writing, the summary informs structure but abstracts come from `get_papers_for_writing(cluster=...)`.
- **Clusters = user's categories.** If the user defined categories in criteria, use them. Do not reinvent.

## Synthesis pass (after the corpus is reviewed)

Per-paper notes describe single papers; synthesis names patterns *across* papers — gaps, contradictions, consensus, open questions. This is a separate pass; do not interleave it with reviewing.

For each cluster:

1. `get_cluster_notes(cluster)` — bundled view of per-paper notes grouped by paper + any existing cross-paper notes. One round-trip, no `get_notes` loops.
2. Read across papers and identify:
   - **gap** — something the cluster collectively doesn't cover.
   - **contradiction** — two or more papers reaching incompatible conclusions on the same question.
   - **consensus** — a non-trivial point most papers agree on.
   - **open_question** — a question raised but not answered in the cluster.
3. For each pattern → `add_synthesis_note(cluster, type, text, derived_from_note_ids=[...])`. Sources are mandatory — every cross-paper note must point at the per-paper notes that justify it via `derived_from`.
4. After the pass, `find_gaps()` to surface clusters that still look thin or unsynthesised. Iterate or accept.

`find_gaps` also flags cluster names that don't appear in the current `review_summary` — usually a typo or invented label. Fix the cluster on the offending notes before continuing.

## Writing loop (per section, draft → critique → revise)

Writing happens section-by-section, not document-at-a-time. Each section is an entity with its own scope, draft, status, and severity counters.

1. **Outline.** `get_outline_inputs()` returns thesis + clusters + criteria. Propose section structure to the user (titles + scope = clusters/keywords/questions). After approval → `bulk_create_sections([...])`.
2. **Per section, in order:**
   1. `research_section(section_id)` if the user agrees the section's scope warrants more papers. Snowball through `expand_citations` is **not** automatic — the user runs it explicitly if needed.
   2. `get_section_critique_inputs(section_id)` — the draft + relevant notes (filtered by `scope.clusters`) + linked papers. If notes are sparse, do another synthesis pass on those clusters first.
   3. Draft the section. Update via `update_section(draft=..., status='drafting')`.
   4. **Critique.** Switch voice to a strict academic reviewer. Generate `[{severity, type, text, suggested_action}]` issues — `severity ∈ {blocker, should_fix, nit}`. Submit via `record_section_critique(section_id, issues=...)`.
      - Returns `{should_stop, severity, iteration}`. Stop when blockers=0 OR iteration≥2.
      - Each issue should be actionable: cite a missing note, resolve a contradiction, drop an overclaimed sentence. Don't list aesthetic preferences as blockers.
   5. **Revise.** `revise_section(section_id, new_draft=...)` resets counters and status to 'drafting'. Loop back to step ii.
   6. Section done → `revise_section(section_id, new_draft=..., mark_done=True)` or `update_section(status='done')`.
3. Document is done when every section has `status='done'`. There is no global "document done" toggle.

## Snowball loop

After the first review pass:

1. `get_saved_papers(status="approved")`
2. For each → `expand_citations(id, "references")` and/or `"citations"`
3. New papers auto-save to `unreviewed` (dedup by DOI automatic). This marks the summary `stale=TRUE`.
4. `get_review_summary()` → stale warning → regenerate summary including the new papers.
5. Repeat the review loop on the new batch.

## Writing style (when drafting the document)

Write in the user's project language natively — don't translate from English word-for-word. Specifically:

- Short sentences; fewer participle clauses; don't mirror English syntax.
- Keep established English terminology as-is in italics on first mention (e.g. *alignment*, *prompt injection*, *jailbreak*, *fine-tuning*, *red teaming*, *RLHF*, *embeddings*, *guardrails*, *effect size*, *confounder*). Don't calque them into awkward target-language equivalents.
- Do not translate method or system names: GCG, SmoothLLM, PAIR, HarmBench, AutoDAN, LLaMA, etc.
- **On doubt about a term — ask the user.** Then apply the decision consistently across the entire document.

## Antipatterns (what you must not do)

- **Do not write scripts in `/tmp` to bulk-operate on the snowcite database.** Use MCP tools. If a tool is missing for a bulk operation, tell the user — do not work around it with side-channel scripts.
- **Do not call source APIs directly via httpx.** Use `snowcite/sources/*` clients — they implement rate limiting, retry, and per-source concurrency caps.
- **Do not edit `papers.db` via the sqlite CLI.** All state transitions go through MCP tools.
- **Do not add a web UI** (Starlette, Flask, Jinja for UI, htmx). This is an explicit architectural rule.
- **Do not integrate Zotero** (neither API nor CSL-JSON import). BibTeX / RIS import via `import_refs` is deliberately kept narrow.
- **Do not parse PDFs yourself.** Use abstracts from the source APIs.
- **Do not recommend a decision on borderline papers.** Show facts; let the user decide.
- **Do not use a system TeXLive.** Only tectonic (for LaTeX) or the typst binary.
- **Do not draft a section without notes for its scope.** If `get_section_critique_inputs` returns an empty `notes` array, the section's claims won't be supported. Either review more papers into those clusters or narrow the scope.
- **Do not auto-trigger `research_section` or `expand_citations` from inside the critique loop.** Critique reports gaps; the user decides whether the cost of more search is justified.
- **Do not invent cluster names.** Clusters come from `review_summary`. New labels in notes or section scope cause `find_gaps` to flag them as unknown — and break the link between the graph and the corpus.
- **Do not overload `blocker` severity.** Reserve it for issues that genuinely block shipping the section (unsupported claim, factual error, contradiction with cited paper). Style preferences are nits.

## Stuck detection

If you fail to resolve the same problem (compile error, search failure, parsing issue, etc.) twice in a row:

- **Stop.** Do not iterate a third or fifth time.
- Summarize what you tried and why it failed.
- Ask the user how to proceed.

A typical failure mode: compile fails due to a missing font / package, you patch the preamble, it fails again, you patch again — five iterations later the user has lost context and nothing works. Break the loop after the second failure.

## Commands

```bash
# connect to Claude Code
claude mcp add snowcite -- uvx snowcite

# with API keys (optional, higher rate limits)
claude mcp add snowcite \
  -e SNOWCITE_SEMANTIC_SCHOLAR_API_KEY=xxx \
  -e SNOWCITE_OPENALEX_EMAIL=user@example.com \
  -- uvx snowcite

# for development (from a clone)
uv sync && uv run python -m snowcite.server

# tectonic (needed for compile_pdf in LaTeX mode)
brew install tectonic

# typst (needed for compile_pdf in Typst mode)
brew install typst
```

## Project layout

```text
snowcite/
├── server.py              # MCP entrypoint (installed as `snowcite` console script)
├── app.py                 # FastMCP instance shared by all tool modules
├── settings.py            # pydantic-settings, env SNOWCITE_*
├── projects.py            # .snowcite/ resolver (walk-up from cwd)
├── db.py                  # aiosqlite schema, migrations, get_connection
├── persistence.py         # DB write path (persist_papers, load_approved_papers, ...)
├── rendering.py           # backend-aware PRISMA / overview renderers
├── bibliography.py        # BibTeX + Hayagriva generation
├── dedup.py               # title + DOI normalisation, fuzzy match
├── logging.py             # shared `log` instance
├── types.py               # Literal aliases + TypedDicts
├── sources/               # arxiv / semantic_scholar / openalex / crossref / pubmed + _http
├── templates/             # latex/*.tex.j2, typst/*.typ.j2, agents/*.md.j2, claude_md.j2
└── tools/                 # search, review, writing, compile, export, doctor, init,
                           #   session, review_quality, import_refs
<project>/.snowcite/papers.db   # user-project DB (not in this repo)
```

## Conventions

- **Dedup**: DOI is the primary key. No DOI → normalized title (lowercase, strip punctuation, ≥0.9 similarity).
- **Sources in DB**: `'arxiv' | 'semantic_scholar' | 'openalex' | 'crossref' | 'pubmed'`.
- **Review statuses**: `'approved' | 'maybe' | 'rejected' | 'unreviewed'`.
- **`reviewed_by`**: `'auto_high'` (Claude confident — direct criterion match), `'auto_low'` (extrapolation; user should sanity-check), or `'user'` (user decided). Critical for the audit trail and for `get_low_confidence_reviews()` on the second pass.
- **`reason` is required** in `set_review_status` — even a short "matches criterion X". This is the PRISMA trail.
- **All I/O is async** — aiosqlite, httpx.AsyncClient.

## Source details

- **arXiv** (`arxiv` lib): rate-limited at 1 req / 3 s by the client. No citation graph — `expand_citations` falls back to Semantic Scholar via DOI lookup.
- **Semantic Scholar**: 100 req / 5 min unauthenticated, 100 req / s with a key (`SNOWCITE_SEMANTIC_SCHOLAR_API_KEY`). Supports both references and citations. Requests go through `sources/_http.py` which retries on 429/5xx with exponential backoff and honors `Retry-After`.
- **OpenAlex**: polite pool via email (`SNOWCITE_OPENALEX_EMAIL`). Abstracts arrive as an inverted index — reconstructed to plaintext at ingestion.
- **Crossref**: universal DOI metadata; reuses the OpenAlex `mailto` value for the polite pool.
- **PubMed**: NCBI E-utilities (`esearch` + `esummary`). Abstracts require a separate `efetch` XML call and are left empty on search.

## Testing

```bash
uv run pytest           # full suite
uv run ruff check       # lint
uv run ruff format      # autoformat
```

CI (`.github/workflows/test.yml`) runs ruff + pytest on push and PR.
