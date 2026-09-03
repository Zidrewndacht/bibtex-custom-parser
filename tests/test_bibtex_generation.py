# tests/test_bibtex_generation.py
from web.filters import generate_bibtex_string


def _paper(**overrides):
    base = {
        "id": "smith2024",
        "type": "article",
        "title": "A Study of PCBs",
        "authors": "Smith, John; Doe, Jane",
        "year": 2024,
        "journal": "Journal of Testing",
        "pages": "276 - 279",
        "doi": "10.1234/test",
        "keywords": "PCB; AOI; inspection",
    }
    base.update(overrides)
    return base


def test_article_generates_correct_type():
    result = generate_bibtex_string(_paper())
    assert result.startswith("@article{smith2024,")


def test_inproceedings_uses_booktitle():
    result = generate_bibtex_string(_paper(type="inproceedings"))
    assert "@inproceedings{" in result
    assert "booktitle = {Journal of Testing}" in result
    assert "journal =" not in result


def test_authors_reformatted_with_and():
    result = generate_bibtex_string(_paper())
    assert "Smith, John and Doe, Jane" in result


def test_pages_double_dash():
    result = generate_bibtex_string(_paper())
    assert "pages = {276--279}" in result


def test_keywords_comma_separated():
    result = generate_bibtex_string(_paper())
    assert "keywords = {PCB, AOI, inspection}" in result


def test_missing_optional_fields_omitted():
    result = generate_bibtex_string(_paper(doi=None, keywords=None, pages=None))
    assert "doi =" not in result
    assert "keywords =" not in result
    assert "pages =" not in result


def test_missing_id_returns_error():
    result = generate_bibtex_string({"title": "No ID"})
    assert "Error" in result


def test_conference_type_mapped_to_inproceedings():
    result = generate_bibtex_string(_paper(type="conference"))
    assert "@conference{" in result