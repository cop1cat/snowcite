"""Doctor — diagnose the local environment.

Checks external binaries (typst, tectonic, pandoc, uv), reachability of the
scholarly APIs snowcite talks to, and relevant env vars. Returns a structured
report so Claude can see "what's broken" without running a bunch of Bash
probes by hand.
"""

import asyncio
import os
import shutil
from typing import Any

import httpx

from snowcite.app import mcp
from snowcite.projects import find_project_root
from snowcite.settings import settings
from snowcite.sources._http import get_client
from snowcite.types import Severity  # re-exported for type callers


HTTP_SERVER_ERROR = 500
HTTP_TOO_MANY_REQUESTS = 429

_ = Severity  # keep import alive; narrows probe return values at boundary


async def _probe_http(name: str, url: str, timeout: float = 6.0) -> dict[str, Any]:
    try:
        r = await get_client().get(url, timeout=timeout)
    except (httpx.HTTPError, OSError) as e:
        return {"name": name, "severity": "warn", "detail": f"unreachable: {type(e).__name__}"}
    if r.status_code == HTTP_TOO_MANY_REQUESTS:
        return {
            "name": name,
            "severity": "warn",
            "detail": "HTTP 429 — rate-limited. Retries will still work but expect delays.",
        }
    if r.status_code < HTTP_SERVER_ERROR:
        return {"name": name, "severity": "ok", "detail": f"HTTP {r.status_code}"}
    return {
        "name": name,
        "severity": "warn",
        "detail": f"HTTP {r.status_code} (API may be degraded)",
    }


def _probe_binary(name: str, required: bool, hint: str) -> dict[str, Any]:
    path = shutil.which(name)
    if path is None:
        return {
            "name": name,
            "severity": "error" if required else "warn",
            "detail": f"not found on PATH — {hint}",
        }
    return {"name": name, "severity": "ok", "detail": path}


def _probe_env(name: str, friendly: str, required: bool = False) -> dict[str, Any]:
    val = os.environ.get(name)
    if val:
        return {"name": friendly, "severity": "ok", "detail": f"{name} is set"}
    return {
        "name": friendly,
        "severity": "error" if required else "warn",
        "detail": f"{name} unset (optional, improves rate limits)",
    }


def _probe_project() -> dict[str, Any]:
    root = find_project_root()
    if root is None:
        return {
            "name": "project",
            "severity": "warn",
            "detail": (
                "no active snowcite project in cwd or parents — run init_project() to create one"
            ),
        }
    return {"name": "project", "severity": "ok", "detail": str(root)}


@mcp.tool()
async def check_environment() -> dict[str, Any]:
    """Diagnose tooling and connectivity; returns a structured report.

    Entries have `severity` ∈ {ok, warn, error}. `ok` → nothing to do. `warn`
    → a feature degrades (missing pandoc → no `.docx` export). `error` → a
    blocker the user should fix before the relevant workflow works.
    """
    binaries = [
        ("typst", False, "brew install typst (needed for Typst backend)"),
        ("tectonic", False, "brew install tectonic (needed for LaTeX backend)"),
        ("pandoc", False, "brew install pandoc (needed for docx export)"),
        ("uv", True, "install via https://docs.astral.sh/uv/"),
    ]
    env_checks = [
        ("SNOWCITE_SEMANTIC_SCHOLAR_API_KEY", "Semantic Scholar API key"),
        ("SNOWCITE_OPENALEX_EMAIL", "OpenAlex polite-pool email"),
    ]

    binary_results = [_probe_binary(b, req, hint) for b, req, hint in binaries]
    env_results = [_probe_env(var, friendly) for var, friendly in env_checks]

    # return_exceptions=True so a single DNS blip doesn't tank the whole report.
    http_probes_raw = await asyncio.gather(
        _probe_http("openalex", "https://api.openalex.org/works?per-page=1"),
        _probe_http(
            "semantic_scholar",
            "https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1",
        ),
        _probe_http(
            "arxiv",
            "https://export.arxiv.org/api/query?search_query=all:test&max_results=1",
        ),
        return_exceptions=True,
    )
    probe_names = ("openalex", "semantic_scholar", "arxiv")
    http_probes: list[dict[str, Any]] = []
    for name, res in zip(probe_names, http_probes_raw, strict=True):
        if isinstance(res, BaseException):
            http_probes.append(
                {
                    "name": name,
                    "severity": "warn",
                    "detail": f"probe raised {type(res).__name__}: {res}",
                }
            )
        else:
            http_probes.append(res)

    all_entries = [*binary_results, *env_results, *http_probes, _probe_project()]
    errors = [e for e in all_entries if e["severity"] == "error"]
    warnings = [e for e in all_entries if e["severity"] == "warn"]

    if errors:
        verdict = "blocker"
    elif warnings:
        verdict = "degraded"
    else:
        verdict = "ok"

    return {
        "verdict": verdict,
        "errors": errors,
        "warnings": warnings,
        "ok": [e for e in all_entries if e["severity"] == "ok"],
        "settings": {
            "semantic_scholar_api_key_set": bool(settings.semantic_scholar_api_key),
            "openalex_email_set": bool(settings.openalex_email),
        },
    }
