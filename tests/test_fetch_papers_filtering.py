import pytest
from shared import db

# After write-time normalization, the classification column only ever
# contains JSON true, false, null, or a missing key.
CASES = [
    ('{"is_offtopic": true}',     False),
    ('{"is_offtopic": false}',    True),
    ('{"is_offtopic": null}',     True),
    ('{}',                        True),   # key missing → json_extract NULL
    (None,                        True),   # column NULL
]

@pytest.mark.parametrize("classification_json, expect_visible", CASES)
def test_hide_offtopic_filtering(test_db, classification_json, expect_visible):
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO papers (id, title, classification) VALUES ('p1', 'T', ?)",
            (classification_json,),
        )
    rows = db.fetch_papers(hide_offtopic=True)
    visible = any(r["id"] == "p1" for r in rows)
    assert visible == expect_visible, (
        f"classification={classification_json!r} should be "
        f"{'visible' if expect_visible else 'hidden'}"
    )