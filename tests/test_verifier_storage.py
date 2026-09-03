import json

import pytest

from shared import db


@pytest.fixture()
def paper(test_db):
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO papers (id, title, set_1_llm) VALUES ('p1','T','{}')"
        )
    return "p1"


def test_float_score_silently_truncated(paper):
    db.update_set_verifier(paper, 1, {"verified": True, "estimated_score": 7.9},
                           model_name="m", reasoning_trace="", json_result="{}",
                           valid=True)
    blob = json.loads(db.get_paper_by_id(paper)["set_1_llm"])
    assert blob["estimated_score"] == 7      # 7.9 → 7, no warning


def test_string_int_score_coerced(paper):
    db.update_set_verifier(paper, 1, {"verified": True, "estimated_score": "8"},
                           model_name="m", reasoning_trace="", json_result="{}",
                           valid=True)
    blob = json.loads(db.get_paper_by_id(paper)["set_1_llm"])
    assert blob["estimated_score"] == 8


def test_verifier_log_entry_appended(paper):
    db.update_set_verifier(paper, 1, {"verified": False, "estimated_score": 3},
                           model_name="m", reasoning_trace="r", json_result="{}",
                           valid=True)
    log = json.loads(db.get_paper_by_id(paper)["set_1_llm_log"])
    assert len(log) == 1
    assert log[0]["type"] == "verifier"