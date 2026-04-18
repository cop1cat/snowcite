"""Template loader for document backends (LaTeX / Typst) and standards.

Templates live as `.j2` files under `templates/{backend}/`. We render them
with Jinja2 — the same engine `init_project` uses for `CLAUDE.md` — so there's
one templating story in the codebase.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape


_TEMPLATES_DIR = Path(__file__).parent


class TemplateNotFoundError(FileNotFoundError):
    """Raised when the requested (backend, standard) combination has no template."""


def list_available(backend: str) -> list[str]:
    """Return the standards available for a backend (e.g. ["plain", "gost"])."""
    subdir = _TEMPLATES_DIR / backend
    if not subdir.is_dir():
        return []
    return sorted(p.stem.removesuffix(".tex").removesuffix(".typ") for p in subdir.glob("*.j2"))


def _ext_for(backend: str) -> str:
    ext = {"latex": "tex", "typst": "typ"}.get(backend)
    if ext is None:
        raise TemplateNotFoundError(f"Unknown backend: {backend!r}")
    return ext


def render_template(backend: str, standard: str, variables: dict[str, str]) -> str:
    """Render `templates/{backend}/{standard}.{ext}.j2` with `variables`.

    Autoescape is disabled — these are LaTeX/Typst documents, not HTML.
    The caller is responsible for passing content that's already syntactically
    valid in the target language.
    """
    ext = _ext_for(backend)
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    template_path = f"{backend}/{standard}.{ext}.j2"
    try:
        template = env.get_template(template_path)
    except TemplateNotFound as e:
        avail = ", ".join(list_available(backend)) or "(none)"
        raise TemplateNotFoundError(
            f"No template for backend={backend!r}, standard={standard!r}. Available: {avail}"
        ) from e
    return template.render(**variables)
