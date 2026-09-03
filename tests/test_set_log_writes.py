# tests/test_set_log_writes.py
import json

import pytest

from shared import db


@pytest.fixture()
def paper(test_db):
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO papers (id, title, classification, main_certainty,
                                set_1_llm, set_1_llm_log, llm_log)
            VALUES ('p1', 'T', '{"is_offtopic": false}', '{"is_offtopic": "solid"}',
                    '{}', '[]', '[]')
        """)
    return "p1"


class TestUpdateSetCache:
    def test_stores_blob_and_appends_log(self, paper):
        db.update_set_cache(paper, 1,
                            llm_data={"is_offtopic": True, "relevance": 9},
                            model_name="test-model", reasoning_trace="think",
                            json_result='{"is_offtopic": true}', valid=True)
        p = db.get_paper_by_id(paper)
        blob = json.loads(p["set_1_llm"])
        assert blob["is_offtopic"] is True
        assert blob["relevance"] == 9
        log = json.loads(p["set_1_llm_log"])
        assert len(log) == 1
        assert log[0]["type"] == "classifier"
        assert log[0]["valid"] is True

    def test_invalid_entry_records_reason(self, paper):
        db.update_set_cache(paper, 1,
                            llm_data={}, model_name="m",
                            reasoning_trace="", json_result="{}",
                            valid=False, invalid_reason="Missing required fields: is_offtopic")
        log = json.loads(db.get_paper_by_id(paper)["set_1_llm_log"])
        assert log[0]["valid"] is False
        assert log[0]["invalid_reason"] == "Missing required fields: is_offtopic"

    def test_does_not_touch_main_classification(self, paper):
        db.update_set_cache(paper, 1,
                            llm_data={"is_offtopic": True},
                            model_name="m", reasoning_trace="",
                            json_result="{}", valid=True)
        p = db.get_paper_by_id(paper)
        cls = json.loads(p["classification"])
        assert cls["is_offtopic"] is False  # unchanged


class TestUpdateSetLogOnly:
    def test_appends_log_without_modifying_blob(self, paper):
        db.update_set_log_only(paper, 1,
                               log_type="error", model_name="m",
                               reasoning_trace="timeout", json_result="{}",
                               valid=False, invalid_reason="Connection Error")
        p = db.get_paper_by_id(paper)
        blob = json.loads(p["set_1_llm"])
        assert blob == {}  # untouched
        log = json.loads(p["set_1_llm_log"])
        assert len(log) == 1
        assert log[0]["type"] == "error"


class TestAppendTraceReviewLog:
    def test_appends_to_main_log_only(self, paper):
        result = db.append_trace_review_log(
            paper, model_name="auditor", reasoning_trace="meta-think",
            report_content="Everything looks consistent.")
        assert result["status"] == "success"
        p = db.get_paper_by_id(paper)
        log = json.loads(p["llm_log"])
        assert len(log) == 1
        assert log[0]["type"] == "trace_review"
        assert json.loads(log[0]["output"])["report"] == "Everything looks consistent."

    def test_does_not_touch_classification_or_audit_fields(self, paper):
        db.append_trace_review_log(paper, model_name="auditor",
                                   reasoning_trace="", report_content="ok")
        p = db.get_paper_by_id(paper)
        cls = json.loads(p["classification"])
        assert cls["is_offtopic"] is False
        assert p["changed"] is None       # not updated
        assert p["changed_by"] is None    # not updated
        cert = json.loads(p["main_certainty"])
        assert cert["is_offtopic"] == "solid"  # not wiped