import pytest

from shared import db
from web import importer


def _write_bib(tmp_path, content):
    p = tmp_path / "import.bib"
    p.write_text(content, encoding="utf-8")
    return str(p)


BASE = """
@article{{key{n},
  title  = {{{title}}},
  author = {{Smith, John}},
  year   = {{2024}},
  doi    = {{{doi}}}
}}
"""


def _count(test_db):
    with db.get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM papers WHERE id != '1'"
        ).fetchone()[0]


def test_exact_doi_duplicate_skipped(test_db, tmp_path):
    bib = BASE.format(n=1, title="Paper A", doi="10.1/x")
    importer.import_bibtex(_write_bib(tmp_path, bib), test_db)
    importer.import_bibtex(_write_bib(tmp_path, bib), test_db)
    assert _count(test_db) == 1


def test_same_title_year_different_doi_skipped(test_db, tmp_path):
    importer.import_bibtex(_write_bib(tmp_path,
        BASE.format(n=1, title="Paper A", doi="10.1/x")), test_db)
    importer.import_bibtex(_write_bib(tmp_path,
        BASE.format(n=2, title="Paper A", doi="10.1/y")), test_db)
    assert _count(test_db) == 1


@pytest.mark.parametrize("title_a, title_b, expect_dup", [
    ("A Study of PCBs", "a study of pcbs",         True),   # case
    ("A Study of PCBs", "A  Study   of  PCBs",     True),   # whitespace
    ("A Study of PCBs", "A Study-of-PCBs",         True),   # dash→space normalisation
    ("A Study of PCBs", "A Study of PCBA",         False),  # genuinely different
])
def test_title_normalisation_edge_cases(test_db, tmp_path, title_a, title_b, expect_dup):
    importer.import_bibtex(_write_bib(tmp_path,
        BASE.format(n=1, title=title_a, doi="10.1/a")), test_db)
    importer.import_bibtex(_write_bib(tmp_path,
        BASE.format(n=2, title=title_b, doi="10.1/b")), test_db)
    assert _count(test_db) == (1 if expect_dup else 2)


def test_page_count_parsing(test_db, tmp_path):
    bib = """
    @inproceedings{pg,
      title = {Pages}, author = {Doe, J}, year = {2024},
      pages = {276--279}, doi = {10.1/pg}
    }
    """
    importer.import_bibtex(_write_bib(tmp_path, bib), test_db)
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT pages, page_count FROM papers WHERE doi='10.1/pg'"
        ).fetchone()
    assert row["pages"] == "276 - 279"
    assert row["page_count"] == 4