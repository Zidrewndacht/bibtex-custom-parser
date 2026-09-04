import json
from shared import db

class TestTextFieldMerging:
    """Text fields are de-duplicated case-insensitively after stripping
    trailing `.` / `,`."""

    def test_case_and_trailing_punct_deduped(self, seed_paper):
        seed_paper(
            {"technique": {"model": "CNN"}},
            {"technique": {"model": "cnn."}},
            {"technique": {"model": "CNN"}},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        assert cls["technique"]["model"] == "CNN"

    def test_whitespace_variants_are_deduped(self, seed_paper):
        """'CNN, RNN' vs 'CNN,RNN' are normalized to the same string and deduped."""
        seed_paper(
            {"technique": {"model": "CNN, RNN"}},
            {"technique": {"model": "CNN,RNN"}},
            {"technique": {"model": ""}},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        # Both normalize to "CNN, RNN" and are deduplicated
        assert cls["technique"]["model"] == "CNN, RNN"

class TestNumericAveraging:
    def test_average_score_rounded_to_nearest_int(self, seed_paper):
        seed_paper(
            {"estimated_score": 7},
            {"estimated_score": 8},
            {"estimated_score": 8},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        # (7+8+8)/3 = 7.666… → round() → 8
        assert cls["estimated_score"] == 8

    def test_verified_derived_from_score_threshold_7(self, seed_paper):
        seed_paper(
            {"estimated_score": 7},
            {"estimated_score": 6},
            {"estimated_score": 9},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        assert cls["verified"] is True
        assert cls["verified_by"] == "computer"


class TestUserOverrideCount:
    def test_reset_after_ai_reclassification(self, test_db, seed_paper):
        """After AI reclassifies, classification == last_llm_classification,
        so the override count must reset to 0."""
        seed_paper({"is_offtopic": False},
                   {"is_offtopic": False},
                   {"is_offtopic": False})
        db.recalculate_main_set("p1")

        db.update_paper_custom_fields("p1", {"is_offtopic": "true"},
                                      changed_by="user")
        assert db.get_paper_by_id("p1")["user_override_count"] == 1

        # AI reclassifies with the same value the user set
        seed_paper({"is_offtopic": True},
                   {"is_offtopic": True},
                   {"is_offtopic": True})
        db.recalculate_main_set("p1")

        paper = db.get_paper_by_id("p1")
        assert paper["classification"] == paper["last_llm_classification"]
        assert paper["user_override_count"] == 0