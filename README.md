# snowcite

MCP server for systematic literature review. Search arXiv / Semantic Scholar / OpenAlex / Crossref / PubMed, snowball through citations, review papers through chat, generate Typst or LaTeX documents, compile to PDF.

> No web UI, no browser, no second terminal. Claude reads abstracts in batches, pre-filters autonomously, surfaces borderline cases to you in chat.

## How it works

```mermaid
flowchart TD
    Start([User: I want a systematic review]) --> Init

    subgraph Phase1["Phase 1 — Onboarding"]
        Init["init_project<br/>discipline, standard, backend, language"]
        Init --> GenFiles["Generate<br/>CLAUDE.md<br/>.claude/settings.json<br/>.claude/agents/*"]
        GenFiles --> Criteria["set_review_criteria<br/>include / exclude / categories"]
    end

    Criteria --> Search

    subgraph Phase2["Phase 2 — Search &amp; review"]
        Search["search_papers<br/>auto_save, no abstracts in context"]
        Search --> ReviewLoop

        subgraph ReviewLoop["Batch review loop"]
            direction TB
            GetBatch["get_unreviewed_papers<br/>limit=20, no abstracts"]
            GetBatch --> AutoClassify{"Claude<br/>classifies"}
            AutoClassify -->|clear| BulkApprove["set_review_status<br/>bulk auto_high"]
            AutoClassify -->|borderline| AskUser["Show to user<br/>facts only, no recommendation"]
            AskUser --> UserDecide["User: i / e / m"]
            UserDecide --> SingleStatus["set_review_status<br/>reviewed_by=user"]
            BulkApprove --> Summary["save_review_summary<br/>≤500 words, rolling"]
            SingleStatus --> Summary
            Summary --> GetBatch
        end

        ReviewLoop --> Snowball{"Deeper?"}
        Snowball -->|yes| Expand["expand_citations<br/>references + citations"]
        Expand --> Search
        Snowball -->|no| Outline
    end

    subgraph Phase3["Phase 3 — Structure"]
        Outline["save_outline<br/>sections + paper_ids + target_words"]
        Outline --> OutlineOk{"User<br/>approves?"}
        OutlineOk -->|edits| Outline
        OutlineOk -->|yes| Skeleton["save_skeleton<br/>3-5 sentences/section"]
        Skeleton --> SkeletonOk{"User<br/>approves?"}
        SkeletonOk -->|edits| Skeleton
    end

    SkeletonOk -->|yes| Phase4

    subgraph Phase4["Phase 4 — Write by section"]
        ExpandSec["save_section"]
        ExpandSec --> Drift{"check_section_drift"}
        Drift -->|within tolerance| AcademicReview["academic-reviewer<br/>subagent"]
        Drift -->|drift| AskDrift["Ask user:<br/>accept / revert / edit"]
        AskDrift --> ExpandSec
        AcademicReview --> FixClaims["User picks fixes"]
        FixClaims --> NextSec{"More<br/>sections?"}
        NextSec -->|yes| ExpandSec
    end

    NextSec -->|no| Phase5

    subgraph Phase5["Phase 5 — Finalize"]
        Polish["polish_document<br/>cross-section transitions"]
        Polish --> Humanizer["humanizer subagent<br/>language, naturalness"]
        Humanizer --> FixLang["User accepts replacements"]
        FixLang --> Compile["compile_pdf<br/>typst or tectonic"]
    end

    Compile --> Done([review.pdf])

    classDef user fill:#fef3c7,stroke:#d97706,color:#000
    classDef auto fill:#dbeafe,stroke:#2563eb,color:#000
    classDef agent fill:#fce7f3,stroke:#db2777,color:#000
    classDef output fill:#dcfce7,stroke:#16a34a,color:#000

    class AskUser,UserDecide,OutlineOk,SkeletonOk,AskDrift,FixClaims,FixLang user
    class AutoClassify,BulkApprove,Search,Summary,Outline,Skeleton,ExpandSec,Polish,Compile auto
    class AcademicReview,Humanizer agent
    class Done,GenFiles output
```

**Legend** — 🟨 user decisions, 🟦 automatic MCP calls, 🟪 subagents (fresh-context review), 🟩 outputs.

## Install

```bash
# Register as an MCP server in Claude Code
claude mcp add snowcite -- uvx snowcite

# Optional but recommended — API keys boost rate limits
claude mcp add snowcite \
  -e SNOWCITE_SEMANTIC_SCHOLAR_API_KEY=xxx \
  -e SNOWCITE_OPENALEX_EMAIL=you@example.com \
  -- uvx snowcite

# Compile backends (install at least one)
brew install typst     # recommended — Cyrillic works out of the box
brew install tectonic  # LaTeX fallback
```

## First run

```
> init_project() here, I'm writing a bachelor thesis on X in Russian, ГОСТ 7.32
```

Claude collects metadata (author, institution, discipline, standard, backend),
scaffolds `.snowcite/` in the current directory, generates a tailored `CLAUDE.md`,
and creates review subagents under `.claude/agents/`.

Then drive the workflow from chat — set criteria, search, review, snowball,
outline, write, compile. See the diagram above for the full picture.

## Projects live in directories

Like `.git`, a `.snowcite/` subdirectory marks a project. Work on multiple
reviews in parallel by `cd`-ing between them — no global state, no switching
commands. `git clone` moves a project to a new machine.

```
my-thesis/
├── .snowcite/
│   ├── papers.db         # project DB — metadata, papers, artifacts, outline
│   └── cache/            # compile artifacts, always gitignored
├── CLAUDE.md             # snowcite-managed, regenerated by init_project
├── review.typ            # or review.tex
├── references.yml        # or references.bib
└── ...
```

## Docs

Full documentation: [cop1cat.github.io/snowcite](https://cop1cat.github.io/snowcite/). Coverage:

- Installation on macOS / Linux / Windows
- Workflow in depth (review loop, snowball, draft-first writing, subagents)
- Backends — Typst vs LaTeX, when to pick which
- Standards — ГОСТ 7.32, IEEE / ACM, APA, Vancouver, MLA, Chicago
- Troubleshooting — Cyrillic fonts, `biber` vs `bibtex` in tectonic, safety refusals
- Reference — every MCP tool's signature

## Development

```bash
git clone https://github.com/cop1cat/snowcite.git
cd snowcite
uv sync --group dev
uv run pytest
uv run ruff check
uv run ruff format
```

CI runs ruff + pytest on every push and PR.

## What this isn't

- **Not a web UI.** Review happens in chat. Architectural choice, see `CLAUDE.md`.
- **Not a Zotero replacement.** We import BibTeX / RIS but don't integrate with Zotero's API.
- **Not a full-auto thesis generator.** Systematic review requires human judgment at
  criteria-setting, borderline papers, outline structure. snowcite automates the
  mechanical parts and keeps you in the loop for the rest.

## License

MIT — see `LICENSE`.
