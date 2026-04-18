"""T7: _sources_for_discipline picks sensible defaults by discipline."""

from snowcite.tools.search import _sources_for_discipline


def test_unknown_discipline_keeps_legacy_defaults():
    # Pre-T7 default (arXiv + universal trio) when we don't know the field.
    result = _sources_for_discipline(None)
    assert "arxiv" in result
    assert "semantic_scholar" in result
    assert "openalex" in result
    assert "crossref" in result


def test_stem_discipline_includes_arxiv():
    for d in ("cs", "physics", "math", "stats"):
        result = _sources_for_discipline(d)
        assert "arxiv" in result, f"arxiv missing for {d}"


def test_humanities_discipline_excludes_arxiv():
    result = _sources_for_discipline("history")
    assert "arxiv" not in result
    assert "semantic_scholar" in result
    assert "openalex" in result


def test_medical_discipline_includes_pubmed_not_arxiv():
    result = _sources_for_discipline("medicine")
    assert "pubmed" in result
    assert "arxiv" not in result


def test_biology_includes_both_arxiv_not_applicable_and_pubmed():
    # Biology isn't STEM per our mapping (there's q-bio for preprints, which is
    # different), but it IS medical for routing purposes.
    result = _sources_for_discipline("biology")
    assert "pubmed" in result


def test_case_insensitive():
    assert "arxiv" in _sources_for_discipline("CS")
    assert "pubmed" in _sources_for_discipline("MEDICINE")
