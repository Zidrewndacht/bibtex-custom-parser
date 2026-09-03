import json

import pytest

from shared import db


@pytest.fixture()
def verified_paper(test_db):
    """Paper classified and LLM-verified."""
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO papers
                (id, title, classification, last_llm_classification,
                 main_certainty, verified, verified_by, estimated_score)
            VALUES ('p1', 'T',
                    '{"is_offtopic": false, "features.smt": true}',
                    '{"is_offtopic": false, "features.smt": true}',
                    '{"is_offtopic": "solid", "features.smt": "solid"}',
                    1, 'computer', 8)
        """)
    return "p1"


class TestVerificationReset:
    def test_classification_edit_resets_llm_verification(self, verified_paper):
        db.update_paper_custom_fields(verified_paper, {"features.smt": "false"})
        p = db.get_paper_by_id(verified_paper)
        assert p["verified"] is None
        assert p["estimated_score"] is None
        assert p["verified_by"] == ""

    def test_comment_only_edit_preserves_verification(self, verified_paper):
        db.update_paper_custom_fields(verified_paper, {"user_trace": "paywalled"})
        p = db.get_paper_by_id(verified_paper)
        assert p["verified"] == 1            # untouched
        assert p["verified_by"] == "computer"
        assert p["pdf_state"] == "paywalled"  # auto-paywall side effect fired

    def test_page_count_edit_does_not_count_as_override(self, verified_paper):
        db.update_paper_custom_fields(verified_paper, {"page_count": "12"})
        p = db.get_paper_by_id(verified_paper)
        assert p["user_override_count"] == 0   # page_count is not a classification field
        assert p["verified"] == 1              # not reset

    def test_user_set_verified_explicitly_blocks_auto_reset(self, verified_paper):
        """If the payload itself sets verified, the reset logic must stand down."""
        db.update_paper_custom_fields(
            verified_paper,
            {"features.smt": "false", "verified": "1", "verified_by": "user"},
        )
        p = db.get_paper_by_id(verified_paper)
        assert p["verified"] == 1
        assert p["verified_by"] == "user"


class TestLogCompaction:
    def test_consecutive_user_edits_compact_into_single_entry(self, verified_paper):
        db.update_paper_custom_fields(verified_paper, {"user_trace": "first"})
        db.update_paper_custom_fields(verified_paper, {"user_trace": "second"})
        log = json.loads(db.get_paper_by_id(verified_paper)["llm_log"])
        user_entries = [e for e in log if e["type"] == "user"]
        assert len(user_entries) == 1
        assert user_entries[0]["trace"] == "second"

    def test_ai_entry_between_user_edits_prevents_compaction(self, verified_paper):
        db.update_paper_custom_fields(verified_paper, {"user_trace": "first"})
        # Simulate an AI log entry arriving between two user edits
        with db.get_db() as conn:
            row = conn.execute("SELECT llm_log FROM papers WHERE id='p1'").fetchone()
            log = json.loads(row[0])
            log.append({"type": "averaged_llm", "timestamp": "2025-01-01T00:00:00Z",
                        "valid": True, "output": "{}"})
            conn.execute("UPDATE papers SET llm_log=? WHERE id='p1'",
                         (json.dumps(log),))
        db.update_paper_custom_fields(verified_paper, {"user_trace": "second"})
        log = json.loads(db.get_paper_by_id(verified_paper)["llm_log"])
        assert len([e for e in log if e["type"] == "user"]) == 2

    def test_certainty_map_not_wiped_on_comment_only_save(self, verified_paper):
        """Regression guard: saving only user_trace must not overwrite
        main_certainty with an empty/partial map."""
        before = json.loads(db.get_paper_by_id(verified_paper)["main_certainty"])
        db.update_paper_custom_fields(verified_paper, {"user_trace": "note"})
        after = json.loads(db.get_paper_by_id(verified_paper)["main_certainty"])
        assert after == before