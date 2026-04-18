# Research artifacts

Beyond scholarly `papers`, snowcite can ingest any user-supplied research
material — interview transcripts, code, archival documents, notes, dataset
descriptions — and cite it inline alongside the literature. This turns
snowcite into a mixed-methods assistant rather than a pure literature-review
tool.

## Supported types

| Type | What it is | Typical use |
|---|---|---|
| `interview` | Transcript of a conversation | Block quotes in findings/discussion |
| `code` | Source file or snippet | `\lstinputlisting` / `#raw(read())` in methodology |
| `document` | Archival text, letter, internal doc | Cited like a primary source |
| `note` | Free-form research note | Referenced in discussion, background |
| `dataset` | Description of a dataset (not the data itself) | Methodology, data availability |

Only text files are supported. Convert PDFs and `.docx` with `pdftotext` or
pandoc first.

## Importing

From a file:

```
Import my interview with P03:
  path = "interviews/p03.md"
  type = "interview"
  label = "P03 — first pilot"
  summary = "Pilot interview covering onboarding friction"
  metadata = {"participant": "P03", "consent": "written", "language": "ru"}
```

Claude calls `import_artifact(path, type, label, summary, metadata)`.

From chat (for short notes / code snippets typed inline):

```
Save this snippet as a code artifact called "auth.py":
def login(user, pw):
    ...
```

Claude calls `add_artifact_inline(type, label, content, ...)`.

## Citation format

Every artifact gets a compact inline citation:

- `[I:3]` — interview id 3
- `[C:auth.py]` — code artifact (label, not id, is shown if available)
- `[D:5]` — document
- `[N:2]` — note
- `[DS:1]` — dataset

These tokens appear inline in the text, and the Primary-sources appendix
expands them. Keep the format consistent throughout the document.

## Assigning artifacts to a section

Outline entries accept `artifact_ids` alongside `paper_ids`:

```
save_outline([
  {
    "name": "findings",
    "target_words": 800,
    "paper_ids": [12, 17, 23],
    "artifact_ids": [1, 2, 3, 4],
  },
])
```

`prepare_section_for_review` and `regenerate_section_brief` load both
automatically. The `academic-reviewer` subagent verifies quotes against
both abstracts and artifact content.

## Writing with artifacts

When Claude drafts a section that has assigned artifacts, it:

1. Reads the full content of each assigned artifact (not truncated like
   abstracts — you want verbatim quotes).
2. Weaves in quotes, paraphrases, references using the `[X:id]` citation
   labels.
3. Does not copy entire transcripts — just the relevant excerpts.

Example output:

> Early users struggled to connect the two onboarding steps:
>
> > «Я не понял, надо ли сначала подтвердить почту или загрузить документ —
> > инструкция была в двух разных местах.» [I:3]
>
> This aligns with prior work on fragmented task flows [Smith2021].

## Code inclusion

For `code` artifacts snowcite generates a backend-specific listing snippet:

```
Include the auth.py artifact in the methodology section.
```

Claude calls `include_code_artifact(artifact_id, backend)` and pastes the
returned snippet into the section:

- LaTeX: `\lstinputlisting[caption={auth.py}]{/path/to/auth.py}`
- Typst: `#figure(caption: [auth.py], raw(read("/path/to/auth.py"), lang: "python"))`

Both read the file live from disk at compile time, so code changes
propagate automatically.

## Primary-sources appendix

Artifacts do not enter the main bibliography. Instead, generate an
appendix:

```
Add a primary-sources appendix at the end of the document.
```

Claude calls `generate_primary_sources_appendix(backend)` and pastes the
returned snippet after the main bibliography. Every included artifact
appears with its citation token, label, type, and summary.

## Excluding without deleting

`set_artifact_included(artifact_id, False)` removes an artifact from the
writing pipeline (won't appear in `prepare_section_for_review` or the
primary-sources appendix) but keeps it in the database. Useful for pilot
interviews that don't make it into the final thesis.

`set_artifact_included(artifact_id, True)` puts it back.

For a hard delete, use `delete_artifact(artifact_id)`.

## What snowcite does not do

- **No audio transcription.** Bring transcripts ready.
- **No PDF / .docx parsing.** Convert with `pdftotext` / `pandoc` first.
- **No data analysis.** Use pandas / R / etc. externally, save figures as
  PNG, insert them as `#image("plot.png")` / `\includegraphics`.
- **No automatic qualitative coding.** You tag manually via `metadata`, or
  ask Claude to help interactively, but snowcite has no built-in codebook
  structure.
