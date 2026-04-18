"""Abstract truncation helper — drives T1's "don't leak abstracts to context" rule."""

from snowcite.sources.base import Paper
from snowcite.tools.search import _compact_paper, _truncate_abstract


def test_truncate_none_passes_through():
    assert _truncate_abstract(None, 100) is None


def test_truncate_zero_drops_field():
    assert _truncate_abstract("some text", 0) is None


def test_truncate_shorter_than_limit():
    assert _truncate_abstract("short", 100) == "short"


def test_truncate_longer_gets_ellipsis():
    result = _truncate_abstract("a" * 500, 50)
    assert result is not None
    assert len(result) == 50
    assert result.endswith("…")


def test_truncate_trailing_whitespace_trimmed_before_ellipsis():
    result = _truncate_abstract("word    " + "x" * 100, 10)
    assert result is not None
    assert not result[:-1].endswith(" ")  # no orphan whitespace before ellipsis


def _paper(abstract: str | None) -> Paper:
    return Paper(source="arxiv", source_id="x1", title="Any", abstract=abstract)


def test_compact_paper_drops_abstract_by_default():
    p = _paper("Some long abstract here")
    d = _compact_paper(p, 0)
    assert d["abstract"] is None


def test_compact_paper_truncates_when_limit_given():
    p = _paper("a" * 200)
    d = _compact_paper(p, 40)
    assert d["abstract"] is not None
    assert len(d["abstract"]) == 40
