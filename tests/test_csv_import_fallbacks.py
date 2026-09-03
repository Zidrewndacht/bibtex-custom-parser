import os
import tempfile

from web.importer import convert_csv_to_bibtex


def _run_csv(csv_content):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        f.write(csv_content)
        path = f.name
    try:
        return convert_csv_to_bibtex(path)
    finally:
        os.unlink(path)

def test_csv_fallback_to_inproceedings():
    csv = """Document Title,Authors,Publication Year,Publication Title,Document Identifier
A Paper,Smith,2024,IEEE Conference on X,
"""
    entries = _run_csv(csv)
    assert len(entries) == 1
    assert '@inproceedings{' in entries[0]

def test_csv_empty_author_becomes_unknown():
    csv = """Document Title,Authors,Publication Year,Publication Title,Document Identifier
A Paper,,2024,Journal of Y,journal
"""
    entries = _run_csv(csv)
    # The code uses "Unknown" for the BibTeX citation KEY, but correctly omits 
    # the empty author field line itself to keep the BibTeX clean.
    assert 'Unknown2024A_Paper' in entries[0]
    assert 'author =' not in entries[0]

def test_csv_malformed_date_ignored():
    csv = """Document Title,Authors,Publication Year,Publication Title,Document Identifier,Date Added To Xplore
A Paper,Smith,2024,Journal Y,journal,Not A Date
"""
    entries = _run_csv(csv)
    assert 'month =' not in entries[0] # Should not crash, just omit month