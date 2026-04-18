"""Project initialization — creates `.snowcite/`, persists metadata, writes CLAUDE.md.

Claude drives the onboarding dialog through AskUserQuestion (MCP tools can't initiate
user-facing prompts). It collects metadata, then calls `init_project(metadata=...)`
which persists it, re-renders CLAUDE.md from `templates/claude_md.j2`, and hands
back a diff for `.claude/settings.json` that Claude can apply after asking the user
how to resolve it.
"""

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from snowcite.app import mcp
from snowcite.db import get_connection, init_db
from snowcite.projects import create_project_dir, find_project_root, migrate_legacy_db


_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_AGENT_TEMPLATES = ("academic_reviewer", "humanizer")

# Fields we support on project_metadata. Keeping this in one place so the INSERT
# column list, the Jinja variables, and the return-value all stay in sync.
_METADATA_FIELDS = (
    "author",
    "supervisor",
    "institution",
    "department",
    "year",
    "work_type",
    "target_length",
    "language",
    "discipline",
    "standard",
    "methodology",
    "backend",
    "review_strictness",
    "deadline",
)

# Baseline allowlist for Claude Code's settings.json. T4 merges/diffs this into
# an existing file (or creates one fresh). The exact set mirrors what the repo
# ships in `.claude/settings.json`.
_SETTINGS_ALLOWLIST = [
    "mcp__snowcite__*",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebSearch",
    # Compile backends. `compile_pdf` calls these internally, but direct
    # invocation is useful for diagnostics (`typst --version`, font listing).
    "Bash(typst:*)",
    "Bash(tectonic:*)",
]


# ─── Metadata persistence ───────────────────────────────────────────────────


async def _load_metadata() -> dict[str, Any]:
    """Read the singleton project_metadata row. Returns {} if missing."""
    async with get_connection() as conn:
        cur = await conn.execute(
            "SELECT * FROM project_metadata WHERE id = 1",
        )
        row = await cur.fetchone()
    if row is None:
        return {}
    data = {k: row[k] for k in row.keys() if k not in ("id", "created_at", "updated_at")}
    if data.get("extra_json"):
        data["extra"] = json.loads(data.pop("extra_json"))
    else:
        data.pop("extra_json", None)
    return {k: v for k, v in data.items() if v is not None}


async def _save_metadata(metadata: dict[str, Any]) -> None:
    """Upsert project_metadata singleton from the provided dict.

    Unknown keys land in extra_json so we don't lose them on round-trip.
    """
    known = {k: metadata.get(k) for k in _METADATA_FIELDS if k in metadata}
    extra = {k: v for k, v in metadata.items() if k not in _METADATA_FIELDS}
    extra_json = json.dumps(extra) if extra else "{}"

    cols = ["id", *known.keys(), "extra_json", "updated_at"]
    placeholders = ["1", *["?"] * len(known), "?", "CURRENT_TIMESTAMP"]
    updates = [f"{k} = excluded.{k}" for k in (*known.keys(), "extra_json")]
    updates.append("updated_at = CURRENT_TIMESTAMP")

    # Column names come from _METADATA_FIELDS (static module constant), never from
    # user input — safe to interpolate.
    sql = (
        f"INSERT INTO project_metadata ({', '.join(cols)}) "  # noqa: S608
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT(id) DO UPDATE SET {', '.join(updates)}"
    )
    async with get_connection() as conn:
        await conn.execute(sql, (*known.values(), extra_json))
        await conn.commit()


# ─── CLAUDE.md generation ───────────────────────────────────────────────────


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(enabled_extensions=(), disabled_extensions=("j2",)),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _neutralize(value: Any) -> Any:
    """Make user-supplied metadata values safe to interpolate into a Jinja
    template with autoescape off.

    CLAUDE.md / agent templates are rendered with autoescape disabled (they
    are Markdown, not HTML). Without this step, a metadata value containing
    `{{ config }}` or `{% include ... %}` would re-evaluate as Jinja when
    the template renders. We neutralise the three Jinja openers in every
    string before it reaches the template.
    """
    if isinstance(value, str):
        return value.replace("{{", "{\u200b{").replace("}}", "}\u200b}").replace("{%", "{\u200b%")
    if isinstance(value, dict):
        return {k: _neutralize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_neutralize(v) for v in value]
    return value


def _render_template(path: str, metadata: dict[str, Any]) -> str:
    # Defaults that every metadata-driven template assumes are set.
    defaults = {
        "language": "en",
        "standard": "plain",
        "backend": "typst",
        "review_strictness": "standard",
    }
    ctx = {k: _neutralize(v) for k, v in {**defaults, **metadata}.items()}
    return _jinja_env().get_template(path).render(**ctx)


def _render_claude_md(metadata: dict[str, Any]) -> str:
    return _render_template("claude_md.j2", metadata)


def _write_agents(project_root: Path, metadata: dict[str, Any], overwrite: bool) -> list[str]:
    """Write `.claude/agents/*.md` from the bundled Jinja templates.

    Returns the list of agent names that were actually written — existing files
    are left alone unless `overwrite=True`, which is the case for `update=True`
    runs of init_project.
    """
    agents_dir = project_root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in _AGENT_TEMPLATES:
        target = agents_dir / f"{name.replace('_', '-')}.md"
        if target.exists() and not overwrite:
            continue
        body = _render_template(f"agents/{name}.md.j2", metadata)
        target.write_text(body, encoding="utf-8")
        written.append(target.name)
    return written


# ─── settings.json diff ─────────────────────────────────────────────────────


def _settings_diff(project_root: Path) -> dict[str, Any]:
    """Compute what `init_project` would add to `.claude/settings.json`.

    Returns {exists, missing_entries, existing_entries, action_required}.
    Claude uses this to ask the user via AskUserQuestion whether to merge,
    overwrite (with .bak), or skip.
    """
    path = project_root / ".claude" / "settings.json"
    wanted = _SETTINGS_ALLOWLIST
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "missing_entries": wanted,
            "existing_entries": [],
            "action_required": "create",
        }
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "exists": True,
            "path": str(path),
            "error": "existing settings.json is unreadable/invalid; user must resolve manually",
            "action_required": "user_decision",
        }
    existing = current.get("permissions", {}).get("allow", [])
    missing = [e for e in wanted if e not in existing]
    return {
        "exists": True,
        "path": str(path),
        "existing_entries": existing,
        "missing_entries": missing,
        "action_required": "ask_user" if missing else "nothing",
    }


def _create_settings_json(project_root: Path) -> None:
    path = project_root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"permissions": {"allow": _SETTINGS_ALLOWLIST}}, indent=2) + "\n",
        encoding="utf-8",
    )


# ─── Public MCP tools ───────────────────────────────────────────────────────


@mcp.tool()
async def init_project(
    metadata: dict[str, Any] | None = None,
    update: bool = False,
    migrate_from_legacy: bool = True,
    update_agents: bool = False,
) -> dict[str, Any]:
    """Initialize (or update) the snowcite project in the current working directory.

    Creates `.snowcite/` (with `papers.db`, `cache/`), persists metadata into the
    `project_metadata` singleton, and regenerates `CLAUDE.md` from the bundled
    Jinja template.

    For `.claude/settings.json`, we don't silently overwrite — `settings_diff` in
    the return value lists what's missing. Claude should ask the user via
    `AskUserQuestion` whether to merge / overwrite (backup in .bak) / skip, then
    apply the chosen action itself.

    `update=True` keeps existing `review_criteria`, `outline`, `skeleton`,
    `section_content`, `papers` etc. — it only touches metadata + CLAUDE.md +
    settings diff. Use this when the user tweaks their project profile mid-work.
    """
    metadata = metadata or {}

    # 1. Directory scaffold + legacy DB migration (pre-T20 layout).
    already = find_project_root()
    already_initialized = already is not None and already.resolve() == Path.cwd().resolve()
    snow = create_project_dir()
    project_root = snow.parent
    migrated = migrate_legacy_db() if migrate_from_legacy else False

    # 2. DB + schema (runs migrations too).
    await init_db()

    # 3. Persist metadata. Merge into existing if update=True and no metadata kwarg.
    if metadata:
        if update:
            existing = await _load_metadata()
            merged = {**existing, **metadata}
            await _save_metadata(merged)
            effective = merged
        else:
            await _save_metadata(metadata)
            effective = metadata
    else:
        effective = await _load_metadata()

    # 4. CLAUDE.md generation (always — it's snowcite-managed).
    claude_md_path = project_root / "CLAUDE.md"
    claude_md_path.write_text(_render_claude_md(effective), encoding="utf-8")

    # 5. Subagent templates under .claude/agents/. First init writes them; later
    # runs leave the user's edits alone unless `update_agents=True`.
    agents_written = _write_agents(project_root, effective, overwrite=update_agents)

    # 6. settings.json diff (never silently modified — Claude asks the user).
    diff = _settings_diff(project_root)

    return {
        "project_root": str(project_root),
        "snowcite_dir": str(snow),
        "already_initialized": already_initialized,
        "migrated_legacy": migrated,
        "metadata_effective": effective,
        "claude_md_path": str(claude_md_path),
        "agents_written": agents_written,
        "settings_diff": diff,
    }


@mcp.tool()
async def get_project_metadata() -> dict[str, Any]:
    """Return the current project_metadata row (empty dict if never set)."""
    return await _load_metadata()


@mcp.tool()
async def apply_settings_diff(action: str) -> dict[str, Any]:  # noqa: PLR0911 — each branch returns a distinct action shape
    """Apply the user's decision for `.claude/settings.json`.

    `action`:
    - `"create"` — create the file fresh (when it didn't exist).
    - `"merge"` — add missing snowcite entries to existing allow list.
    - `"overwrite"` — back up existing file as `settings.json.bak`, then replace.
    - `"skip"` — do nothing. Claude relays the consequence to the user.
    """
    root = find_project_root()
    if root is None:
        return {"applied": False, "error": "no active project"}
    path = root / ".claude" / "settings.json"

    if action == "skip":
        return {"applied": False, "action": "skip"}

    if action in ("create", "overwrite"):
        if action == "overwrite" and path.exists():
            path.rename(path.with_suffix(".json.bak"))
        _create_settings_json(root)
        return {"applied": True, "action": action, "path": str(path)}

    if action == "merge":
        if not path.exists():
            _create_settings_json(root)
            return {"applied": True, "action": "created (file was missing)", "path": str(path)}
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return {
                "applied": False,
                "error": f"existing settings.json is unreadable: {e}. Use overwrite or fix manually.",
            }
        perms = current.setdefault("permissions", {}).setdefault("allow", [])
        added: list[str] = []
        for entry in _SETTINGS_ALLOWLIST:
            if entry not in perms:
                perms.append(entry)
                added.append(entry)
        path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        return {"applied": True, "action": "merge", "added": added, "path": str(path)}

    return {"applied": False, "error": f"unknown action {action!r}"}
