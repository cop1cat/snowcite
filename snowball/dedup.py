"""DOI + fuzzy-title deduplication."""

import re
import unicodedata

from rapidfuzz import fuzz, process

TITLE_SIMILARITY_THRESHOLD = 90.0  # rapidfuzz ratio (0..100), ≥90 ≈ duplicate

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Lowercase, strip diacritics + punctuation, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_ish = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = ascii_ish.lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", no_punct).strip()


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    cleaned = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned or None


def find_title_match(needle_norm: str, haystack_norm: list[str]) -> int | None:
    """Index of best match in haystack if above threshold, else None.

    Uses rapidfuzz C-level extractOne for early-exit performance.
    """
    if not haystack_norm:
        return None
    result = process.extractOne(
        needle_norm,
        haystack_norm,
        scorer=fuzz.ratio,
        score_cutoff=TITLE_SIMILARITY_THRESHOLD,
    )
    if result is None:
        return None
    _, _, idx = result
    return idx
