# Troubleshooting

## "No snowcite project found"

The resolver walks up from your current working directory looking for a
`.snowcite/` subdir. If none is found anywhere in the parent chain, you get:

```
NoProjectError: No snowcite project found in the current directory or any parent.
Run `init_project()` here first to create a .snowcite/ directory.
```

Fix: `cd` to the directory that *should* hold this project, then ask Claude
to run `init_project`.

Alternative: `export SNOWCITE_PROJECT_ROOT=/path/to/project` to override the
resolver — useful when running the server from an unrelated directory.

## LaTeX compile fails on Cyrillic

Symptom: errors like `Missing character: There is no Ж in font ec-lmr12!` or
`Package inputenc Error: Unicode character Ы not set up`.

Cause: you're using an 8-bit fontenc (T1 or T2A) with tectonic's XeTeX,
which expects Unicode fonts via fontspec.

Fix: use the snowcite-generated templates. They already do:

```latex
\usepackage{fontspec}
\usepackage[russian,english]{babel}
\babelfont{rm}[Ligatures=TeX]{CMU Serif}
```

If you edited `review.tex` manually, regenerate via `write_document(...)` or
copy the preamble from `snowcite/templates/latex/plain.tex.j2`.

## LaTeX compile: "biber not found"

Tectonic ships `bibtex` but not `biber`. If your `\usepackage{biblatex}` call
has `backend=biber`, switch it to `backend=bibtex`. Our templates already do.

## Typst compile: `modern-g7-32` errors

The ГОСТ typst package pins a specific version. If typst complains about
missing functions or breaking changes, check `snowcite/templates/typst/gost.typ.j2`
and bump the `@preview/modern-g7-32:X.Y.Z` version tag. Run the tests locally
to make sure substitution still works before committing.

## Safety refusals on sensitive topics

snowcite is designed for academic reviews, including dual-use areas like AI
safety, cybersecurity, biosecurity. But the Claude safety classifier operates
on *context density* — a chat window full of abstracts containing operational
detail can trigger refusals even when your intent is scholarly.

Mitigations already in place:

- `get_unreviewed_papers(include_abstracts=False)` — default, keeps abstracts out of context
- CLAUDE.md explicitly frames the project as a peer-reviewed literature review
- `academic-reviewer` subagent paraphrases rather than quoting verbatim

If you still hit a refusal:

1. `/clear` to reset context — accumulated density is often the culprit
2. Be explicit: "This is a systematic review for my thesis. I need [X] at an
   academic level of detail, not operational."
3. Split into smaller sub-topics so any one session touches less material.

For genuinely borderline material (detailed attack recipes, weaponization
details), Claude may still refuse — that's the correct behavior. Keep the
review at the level of "here's what this paper claims and why it matters",
not "here's how to reproduce their attack".

## Rate-limited on Semantic Scholar

Unauthenticated: 100 req / 5 min. Our retry helper honors `Retry-After` and
backs off exponentially, but on a big snowball you might see warnings like:

```
warning: semantic_scholar: HTTP 429, waiting 30s (attempt 3/5)
```

These are fine — the search continues in parallel on other sources. Fix
permanently by requesting an API key and setting
`SNOWCITE_SEMANTIC_SCHOLAR_API_KEY`, which unlocks 100 req / sec.

## The Claude session lost context

Normal after `/clear` or a new session. Fix: the first tool Claude should call
is `get_session_state()`. It returns current phase, next-action hint, last
review actions, section counts. Claude picks up exactly where it left off.

## PDF output missing Russian characters

See [LaTeX compile fails on Cyrillic](#latex-compile-fails-on-cyrillic).
For Typst, make sure `set text(lang: "ru")` is in your document — snowcite
templates do this automatically based on `project_metadata.language`.

## I edited `CLAUDE.md` and it got overwritten

Yes — `CLAUDE.md` is snowcite-managed. Every `init_project` call (including
`update=True`) regenerates it from the template. Put project-specific notes
into a separate file, e.g. `NOTES.md`, and reference it from `CLAUDE.md` via
`@NOTES.md` if you want Claude to read it automatically.

## The review history looks wrong

`set_review_status` appends to `review_history` on every change. You can
inspect via:

```sql
sqlite3 .snowcite/papers.db \
  "SELECT paper_id, old_status, new_status, reason, reviewed_by, changed_at
   FROM review_history ORDER BY id DESC LIMIT 20;"
```

But don't `UPDATE` or `DELETE` from this table directly — it's the audit trail
the PRISMA flow diagram depends on.
