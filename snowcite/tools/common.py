"""Shared helpers for tool modules."""

import json
from typing import Any

import aiosqlite


def paper_row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a SQLite row with `authors_json` / `metadata_json` columns into
    a regular dict with those fields parsed."""
    d = dict(row)
    d["authors"] = json.loads(d.pop("authors_json"))
    if "metadata_json" in d:
        d["metadata"] = json.loads(d.pop("metadata_json")) if d["metadata_json"] else {}
    return d
