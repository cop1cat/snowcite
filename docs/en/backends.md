# Backends — Typst vs LaTeX

snowcite supports two document backends. Pick one per project at `init_project`;
switching mid-project requires `set_backend(new_backend, confirm_wipe_sections=True)`
because expanded section content is not cross-compatible.

## TL;DR

| Use case | Recommendation |
|---|---|
| Cyrillic text | **Typst** |
| Strict ГОСТ 7.32-2017 | LaTeX (`standard="gost"`) |
| University-provided `.tex` template | LaTeX |
| Quick iteration | **Typst** (fast incremental compiles) |
| Medicine / Vancouver citations | Either — both support CSL / biblatex-vancouver |
| IEEE / ACM conference | Either — templates exist for both |

## Typst

Recommended default.

**Pros**

- **Cyrillic just works.** No `\babelfont`, no T2A, no font file hunting.
- **Single static binary**, installable via `brew install typst`. No TeXLive.
- **Fast incremental compilation** — seconds on a 200-page document.
- **Modern error messages** — locate problems without reading `.log` files.
- **Native CSL support** for bibliography styles via the bundled Hayagriva.

**Cons**

- Younger ecosystem. Some niche templates (strict legal-style citations,
  exotic typography) don't exist yet.
- ГОСТ 7.32-2017 support comes via `modern-g7-32`, which is maintained but
  evolving. For mission-critical ГОСТ compliance, consider LaTeX.

**Bibliography**

snowcite emits `.yml` in the [Hayagriva format](https://github.com/typst/hayagriva/blob/main/docs/file-format.md).
Typst's `#bibliography("references.yml", style: "<csl>")` takes any CSL style name.

## LaTeX

Use LaTeX when you have a university-provided `.tex` template, when strict ГОСТ
compliance matters, or when you're already committed to a biblatex-heavy
workflow.

**Compiler** — [tectonic](https://tectonic-typesetting.github.io/) only. System
TeXLive is not supported (different font paths, different packages bundled).
Tectonic is self-contained and downloads packages on demand.

**Cyrillic in tectonic**

Our `plain.tex.j2` and `gost.tex.j2` templates use `fontspec` + `\babelfont`:

```latex
\usepackage{fontspec}
\usepackage[russian,english]{babel}
\babelfont{rm}[Ligatures=TeX]{CMU Serif}
\babelfont{sf}[Ligatures=TeX]{CMU Sans Serif}
\babelfont{tt}{CMU Typewriter Text}
```

CMU fonts ship inside tectonic's bundle. The old `\usepackage[T2A]{fontenc}` +
8-bit Computer Modern pattern doesn't work under tectonic's XeTeX.

**Bibliography**

Hardcoded to `backend=bibtex` — `biber` isn't bundled with tectonic.

## Switching

If the user chose the wrong backend at onboarding, `set_backend(new_backend,
confirm_wipe_sections=True)` wipes `section_content` (because the syntax of
already-written sections is backend-specific) and keeps `outline` and
`skeleton`. The user then re-expands sections under the new backend.

## Standards available today

Both backends ship `plain` and `gost`. IEEE, ACM, APA, Vancouver, MLA and
Chicago templates are planned and will land under
[`snowcite/templates/`](https://github.com/cop1cat/snowcite/tree/main/snowcite/templates).
Contributions welcome.
