"""Bibliography — BibTeX and Hayagriva generation."""

from snowcite.bibliography import (
    disambiguate_key,
    generate_bibtex,
    generate_hayagriva,
    generate_hayagriva_entry,
    make_cite_key,
)


def test_make_cite_key_basic():
    assert make_cite_key(["John Smith"], 2024, "A Fancy Title") == "smith2024a"


def test_make_cite_key_no_authors():
    assert make_cite_key([], 2024, "Untitled draft") == "unknown2024untitled"


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
