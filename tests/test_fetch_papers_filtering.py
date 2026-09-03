import pytest

from shared import db

CASES = [
    # (classification JSON, expected visible when hide_offtopic=True)
    ('{"is_offtopic": true}',     False),
    ('{"is_offtopic": false}',    True),
    ('{"is_offtopic": 1}',        False),
    ('{"is_offtopic": 0}',        True),
    ('{"is_offtopic": "true"}',   False),
    ('{"is_offtopic": "false"}',  True),
    ('{"is_offtopic": "False"}',  True),
    ('{"is_offtopic": "FALSE"}',  False),   # ← not in the IN list → hidden
    ('{"is_offtopic": "True"}',   False),
    ('{"is_offtopic": null}',     True),
    ('{}',                        True),    # key missing → json_extract NULL
    (None,                        True),    # column NULL
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