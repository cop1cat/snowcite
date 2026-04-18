"""Template loading + substitution."""

import pytest

from snowcite.templates import (
    TemplateNotFoundError,
    list_available,
    render_template,
)


def test_list_available_latex_has_plain_and_gost():
    avail = list_available("latex")
    assert "plain" in avail
    assert "gost" in avail


def test_list_available_typst_has_plain_and_gost():
    avail = list_available("typst")
    assert "plain" in avail
    assert "gost" in avail


def test_list_available_unknown_backend_returns_empty():
    assert list_available("nothing") == []


def test_render_substitutes_placeholders_in_latex_plain():
    out = render_template(
        "latex",
        "plain",
        {
            "title": "My Review",
            "author": "Alice",
            "babel_langs": "russian,english",
            "bib_style": "numeric",
            "sections": r"\section{Intro}\nHello.",
        },
    )
    assert "My Review" in out
    assert "Alice" in out
    assert "russian,english" in out
    assert "numeric" in out
    assert r"\section{Intro}" in out
    # Placeholders all consumed.
    assert "{{ title }}" not in out
    assert "{{- title -}}" not in out
    assert "{{ sections }}" not in out


def test_render_substitutes_placeholders_in_typst_plain():
    out = render_template(
        "typst",
        "plain",
        {
            "title": "Обзор",
            "author": "Иван Иванов",
            "lang": "ru",
            "csl_style": "ieee",
            "sections": "= Введение\n\nПривет.",
        },
    )
    assert "Обзор" in out
    assert "Иван Иванов" in out
    assert 'lang: "ru"' in out
    assert "= Введение" in out


def test_render_raises_for_unknown_standard():
    with pytest.raises(TemplateNotFoundError):
        render_template("latex", "no_such_standard", {})


def test_render_raises_for_unknown_backend():
    with pytest.raises(TemplateNotFoundError):
        render_template("nothing", "plain", {})
