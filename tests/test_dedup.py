"""Dedup helpers — title normalization, DOI normalization, fuzzy matching."""

from snowcite.dedup import find_title_match, normalize_doi, normalize_title


def test_normalize_title_strips_punct_and_case():
    assert normalize_title("Hello, World!") == "hello world"


def test_normalize_title_strips_diacritics():
    assert normalize_title("Café Cöncept") == "cafe concept"


def test_normalize_title_collapses_whitespace():
    assert normalize_title("  many   spaces\tand\ttabs ") == "many spaces and tabs"


def test_normalize_doi_none_empty():
    assert normalize_doi(None) is None
    assert normalize_doi("") is None
    assert normalize_doi("   ") is None


def test_normalize_doi_strips_prefixes_and_case():
    cases = [
        ("10.1234/abc", "10.1234/abc"),
        ("https://doi.org/10.1234/ABC", "10.1234/abc"),
        ("http://doi.org/10.1234/abc", "10.1234/abc"),
        ("doi:10.1234/AbC", "10.1234/abc"),
        ("  10.1234/abc  ", "10.1234/abc"),
    ]
    for raw, want in cases:
        assert normalize_doi(raw) == want, f"{raw} → got {normalize_doi(raw)!r}"


def test_normalize_doi_arxiv_variants_canonical():
    # All of these should fold to the same canonical arXiv DOI so that DOI
    # dedup recognizes them as the same paper.
    canonical = "10.48550/arxiv.2301.12345"
    cases = [
        "arxiv:2301.12345",
        "ArXiv:2301.12345",
        "2301.12345",
        "2301.12345v2",
        "10.48550/arXiv.2301.12345",
        "10.48550/arxiv.2301.12345v3",
        "https://doi.org/10.48550/arXiv.2301.12345",
    ]
    for raw in cases:
        assert normalize_doi(raw) == canonical, f"{raw} → got {normalize_doi(raw)!r}"


def test_normalize_doi_five_digit_arxiv_id():
    # arXiv switched to 5-digit sequence numbers in 2015 for some categories.
    assert normalize_doi("2301.12345") == "10.48550/arxiv.2301.12345"
    assert normalize_doi("2301.1234") == "10.48550/arxiv.2301.1234"


def test_find_title_match_empty_haystack():
    assert find_title_match("foo", []) is None


def test_find_title_match_exact_hit():
    haystack = ["a b c", "adversarial attacks on llms", "learning rate warmup"]
    idx = find_title_match("adversarial attacks on llms", haystack)
    assert idx == 1


def test_find_title_match_near_hit():
    haystack = ["adversarial attacks on llms"]
    # Small punctuation/word variations should still match above the 90 threshold.
    assert find_title_match("adversarial attacks on llm", haystack) == 0


def test_find_title_match_miss():
    haystack = ["completely unrelated topic"]
    assert find_title_match("adversarial attacks on llms", haystack) is None
