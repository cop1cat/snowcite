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


_ARXIV_ID_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5})(v\d+)?$")


def normalize_doi(doi: str | None) -> str | None:
    """Canonicalise a DOI string for storage and dedup.

    Handles:
    - URL prefixes (https://doi.org/, http://doi.org/, doi:) → stripped
    - lowercase
    - arXiv variants folded to `10.48550/arxiv.<id>`:
      - `arxiv:2301.12345` → `10.48550/arxiv.2301.12345`
      - bare `2301.12345` → `10.48550/arxiv.2301.12345`
      - `2301.12345v2` → `10.48550/arxiv.2301.12345` (version stripped)
      - existing `10.48550/arxiv.2301.12345v3` → version stripped
    """
    if not doi:
        return None
    cleaned = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    if not cleaned:
        return None

    # Strip version suffix from an already-canonical arXiv DOI.
    arxiv_doi_match = re.match(r"^10\.48550/arxiv\.(\d{4}\.\d{4,5})(?:v\d+)?$", cleaned)
    if arxiv_doi_match:
        return f"10.48550/arxiv.{arxiv_doi_match.group(1)}"

    # Fold plain arXiv ids and `arxiv:` variants into the canonical DOI form.
    m = _ARXIV_ID_RE.match(cleaned)
    if m:
        return f"10.48550/arxiv.{m.group(1)}"

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
