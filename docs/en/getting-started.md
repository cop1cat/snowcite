# Getting started

## 1. Create a project directory

```bash
mkdir my-review && cd my-review
```

That's it — `.snowcite/` and every generated file land here. `cd` into this
directory any time you want to work on this review; snowcite resolves the
active project from your current working directory.

## 2. Initialize

From Claude Code (inside `my-review/`):

> Let's start a snowcite project. I'm writing a bachelor thesis on
> adversarial attacks on LLMs, in Russian, ГОСТ 7.32, Typst.

Claude collects metadata via `AskUserQuestion` (author, institution, deadline,
etc.), then calls `init_project(metadata=...)`. The tool:

- Creates `.snowcite/papers.db` and `.snowcite/cache/`.
- Writes a tailored `CLAUDE.md` at the project root — this guides every future
  Claude session in this directory.
- Writes `.claude/agents/academic-reviewer.md` and `.claude/agents/humanizer.md`.
- Emits a diff for `.claude/settings.json` (new file or missing entries) so
  Claude can ask you how to resolve it: merge, overwrite with backup, or skip.

## 3. Set review criteria

Criteria are free text — include clauses, exclude clauses, and optionally
user-defined clusters for the review summary:

```
Include: adversarial attacks on language models (LLMs or text classifiers),
         papers from 2023+.
Exclude: vision-only adversarial work, hardware attacks.
Clusters: attacks-optimization, attacks-jailbreak, defenses-detection,
         defenses-certified, evaluation, surveys.
```

Claude calls `set_review_criteria(criteria_text=...)`.

## 4. Search and review

```
Search arXiv, Semantic Scholar and OpenAlex for "adversarial attacks LLM
2023-2025", limit 50 each.
```

Claude calls `search_papers(query, limit=50)`. By default, `auto_save=True`
persists results to the DB and returns `{saved, duplicates, new_ids, titles}` —
abstracts never enter your chat context. Then:

```
Start reviewing. Batch of 20.
```

For each paper in the batch, Claude decides autonomously and tags the decision
with `reviewed_by` (`auto_high` for clear matches, `auto_low` for less certain,
or defers to you for genuinely borderline ones). After each batch it saves a
rolling review summary.

## 5. Snowball

Once you have an approved set, deepen through citations:

```
Run snowball — expand_citations(references) on the approved papers, then
re-review the new ones.
```

New papers from the snowball are added to `unreviewed`; the summary is marked
stale. Iterate.

## 6. Outline and skeleton

```
Propose an outline for the document.
```

Claude calls `save_outline(sections=[...])` with sections, paper IDs per
section, and target word counts. You approve or edit. Same for
`save_skeleton(sections=[...])` — the 3-5-sentence version of each section —
which gives you the arc in about 500 words total.

## 7. Expand section by section

```
Write the first section.
```

Claude drafts, calls `check_section_drift`, then `save_section`. It then
spawns the `academic-reviewer` subagent, which reads your section + the
assigned papers' abstracts cold (fresh context) and returns a structured
findings list — unsupported claims, citation misuse, fabricated quotes,
logical gaps. Decide which to fix; save the revision.

## 8. Polish

After all sections are in:

```
Run polish_document for cross-section consistency, then humanizer.
```

`polish_document` handles transitions and cross-section duplication. Then
the `humanizer` subagent flags machine-translated phrasing, LLM tics and
awkward sentences — per-phrase replacement suggestions you accept or reject.

## 9. Compile

```
compile_pdf on review.typ
```

`typst compile` runs and drops `review.pdf` next to the source. Done.
