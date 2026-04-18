"""Shared helpers for tool modules."""

import json
from typing import Any


def paper_row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    d["authors"] = json.loads(d.pop("authors_json"))
    if "metadata_json" in d:
        d["metadata"] = json.loads(d.pop("metadata_json")) if d["metadata_json"] else {}
    return d
