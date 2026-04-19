"""Bibliography — BibTeX and Hayagriva generation."""

from snowcite.bibliography import (
    build_cite_key_map,
    disambiguate_key,
    generate_bibtex,
    generate_hayagriva,
    generate_hayagriva_entry,
    make_cite_key,
    rewrite_cite_refs,
)


def test_make_cite_key_basic():
    assert make_cite_key(["John Smith"], 2024, "A Fancy Title") == "smith2024a"


def test_make_cite_key_no_authors_uses_title_fallback():
    # Without authors the prefix comes from the first meaningful title word,
    # not the legacy "unknown" sentinel.
    assert make_cite_key([], 2024, "Untitled draft") == "untitled2024untitled"


def test_make_cite_key_no_authors_skips_stopwords():
    # "The" / "a" etc. are skipped so the key stays informative.
    assert make_cite_key([], 2024, "The Fancy Paper") == "fancy2024the"


def test_make_cite_key_no_authors_no_title_is_anon():
    assert make_cite_key([], 2024, "") == "anon2024untitled"


def test_make_cite_key_no_year():
    assert make_cite_key(["Jane Doe"], None, "Some Paper") == "doendsome"


def test_disambiguate_collides():
    used: set[str] = set()
    a = disambiguate_key("smith2024a", used)
    b = disambiguate_key("smith2024a", used)
    c = disambiguate_key("smith2024a", used)
    assert a == "smith2024a"
    assert b == "smith2024aa"
    assert c == "smith2024ab"


def test_generate_bibtex_basic():
    entry = generate_bibtex(
        title="Adversarial Attacks",
        authors=["Jane Doe", "John Smith"],
        year=2024,
        venue="ICML",
        doi="10.1/foo",
        source="openalex",
    )
    assert "@article{doe2024adversarial," in entry
    assert "author = {Jane Doe and John Smith}" in entry
    assert "doi = {10.1/foo}" in entry


def test_generate_bibtex_arxiv_becomes_misc():
    entry = generate_bibtex(
        title="Preprint",
        authors=["Alice"],
        year=2023,
        venue="arxiv:2301.00001",
        source="arxiv",
    )
    assert entry.startswith("@misc{")
    assert "howpublished =" in entry


def test_generate_bibtex_escapes_special_chars():
    entry = generate_bibtex(
        title="20% of $N$ papers & counting",
        authors=["Author"],
        year=2024,
    )
    assert r"\%" in entry
    assert r"\$" in entry
    assert r"\&" in entry


def test_hayagriva_entry_basic():
    frag = generate_hayagriva_entry(
        cite_key="doe2024paper",
        title="A Paper",
        authors=["Jane Doe"],
        year=2024,
        venue="Nature",
        doi="10.1/foo",
    )
    assert frag.startswith("doe2024paper:")
    assert "type: article" in frag
    assert 'title: "A Paper"' in frag
    assert '- "Jane Doe"' in frag
    assert 'date: "2024"' in frag
    assert 'title: "Nature"' in frag
    assert 'doi: "10.1/foo"' in frag


def test_hayagriva_entry_arxiv_is_web_type():
    frag = generate_hayagriva_entry(
        cite_key="x2023arxiv",
        title="Preprint",
        authors=[],
        year=2023,
        source="arxiv",
    )
    assert "type: web" in frag


def test_hayagriva_entry_escapes_quotes():
    frag = generate_hayagriva_entry(
        cite_key="k",
        title='Title with "quotes" and \\backslashes',
        authors=[],
        year=None,
    )
    # Both characters must survive as escape sequences in the YAML output.
    assert r"\"quotes\"" in frag
    assert r"\\backslashes" in frag


def test_build_cite_key_map_by_id():
    entries = [
        {"id": 10, "title": "Paper A", "authors": ["Alice Smith"], "year": 2023},
        {"id": 11, "title": "Paper B", "authors": ["Bob Jones"], "year": 2024},
    ]
    m = build_cite_key_map(entries)
    assert m == {10: "smith2023paper", 11: "jones2024paper"}


def test_build_cite_key_map_disambiguates():
    # Two entries with identical author+year+first-title-word → second gets a suffix.
    entries = [
        {"id": 1, "title": "Review", "authors": ["Alice Smith"], "year": 2024},
        {"id": 2, "title": "Review", "authors": ["Alice Smith"], "year": 2024},
    ]
    m = build_cite_key_map(entries)
    assert m[1] == "smith2024review"
    assert m[2] == "smith2024reviewa"


def test_rewrite_cite_refs_latex_single():
    out = rewrite_cite_refs("see [1] for details", {1: "smith2024a"}, "latex")
    assert out == "see \\cite{smith2024a} for details"


def test_rewrite_cite_refs_latex_multiple():
    out = rewrite_cite_refs("shown in [1, 2; 3]", {1: "a2024x", 2: "b2024y", 3: "c2024z"}, "latex")
    assert out == "shown in \\cite{a2024x,b2024y,c2024z}"


def test_rewrite_cite_refs_typst_single():
    out = rewrite_cite_refs("см. [1] и далее", {1: "smith2024a"}, "typst")
    assert out == "см. @smith2024a и далее"


def test_rewrite_cite_refs_typst_multiple():
    out = rewrite_cite_refs("[1, 2]", {1: "a2024x", 2: "b2024y"}, "typst")
    assert out == "@a2024x @b2024y"


def test_rewrite_cite_refs_unknown_id_left_untouched():
    # Unknown paper ids stay as `[N]` so the author can spot the orphan.
    out = rewrite_cite_refs("mix [1] and [999]", {1: "k"}, "latex")
    assert out == "mix \\cite{k} and [999]"


def test_rewrite_cite_refs_ignores_non_numeric_brackets():
    out = rewrite_cite_refs("[note] and [1]", {1: "k"}, "latex")
    assert out == "[note] and \\cite{k}"


def test_generate_hayagriva_full_doc():
    entries = [
        {
            "title": "Paper A",
            "authors": ["Alice Smith"],
            "year": 2023,
            "venue": "Venue",
            "doi": "10.1/a",
            "source": "openalex",
        },
        {
            "title": "Paper B",
            "authors": ["Bob Jones"],
            "year": 2024,
            "venue": None,
            "doi": None,
            "source": "arxiv",
        },
    ]
    doc = generate_hayagriva(entries)
    # Two entries, two cite keys
    assert "smith2023paper:" in doc
    assert "jones2024paper:" in doc
    # Separator between entries
    assert "\n\n" in doc
    # Trailing newline
    assert doc.endswith("\n")
