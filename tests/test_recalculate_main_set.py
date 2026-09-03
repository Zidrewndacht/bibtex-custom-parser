import json

import pytest

from shared import db


class TestBooleanTypeCoercion:
    """recalculate_main_set uses `v is True` / `v is False`.
    If the LLM ever returns JSON 1/0 or "true"/"false" strings instead of
    real booleans, those votes are SILENTLY DROPPED as unknown."""

    def test_int_zero_votes_are_dropped_flipping_majority(self, seed_paper):
        """True + 0 + 0 *should* be a 2-vs-1 No majority (conflict).
        Current code treats both 0s as unknown → shows ✔️ at 60% instead."""
        seed_paper(
            {"is_offtopic": True},
            {"is_offtopic": 0},      # LLM returned int, not false
            {"is_offtopic": 0},
        )
        db.recalculate_main_set("p1")

        paper = db.get_paper_by_id("p1")
        cls = json.loads(paper["classification"])
        cert = json.loads(paper["main_certainty"])

        # PIN CURRENT BEHAVIOUR (arguably a bug – flip assertions if you fix it):
        assert cls["is_offtopic"] is True      # ← silently wrong if 0 meant False
        assert cert["is_offtopic"] == "60"     # ← should be "conflict"

    def test_int_one_treated_as_unknown_reduces_certainty(self, seed_paper):
        seed_paper(
            {"is_offtopic": True},
            {"is_offtopic": 1},      # int, not bool
            {"is_offtopic": True},
        )
        db.recalculate_main_set("p1")
        cert = json.loads(db.get_paper_by_id("p1")["main_certainty"])
        assert cert["is_offtopic"] == "80"     # not "solid"

    def test_string_booleans_treated_as_unknown(self, seed_paper):
        seed_paper(
            {"is_offtopic": True},
            {"is_offtopic": "false"},   # string
            {"is_offtopic": True},
        )
        db.recalculate_main_set("p1")
        cert = json.loads(db.get_paper_by_id("p1")["main_certainty"])
        assert cert["is_offtopic"] == "80"

class TestTextFieldMerging:
    """Text fields are de-duplicated case-insensitively after stripping
    trailing `.` / `,` — but NOT normalised beyond that."""

    def test_case_and_trailing_punct_deduped(self, seed_paper):
        seed_paper(
            {"technique": {"model": "CNN"}},
            {"technique": {"model": "cnn."}},
            {"technique": {"model": "CNN"}},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        assert cls["technique"]["model"] == "CNN"   # one value, Set-1 casing kept

    def test_whitespace_variants_are_NOT_deduped(self, seed_paper):
        """'CNN, RNN' vs 'CNN,RNN' survive as two entries → silent duplication."""
        seed_paper(
            {"technique": {"model": "CNN, RNN"}},
            {"technique": {"model": "CNN,RNN"}},
            {"technique": {"model": ""}},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        # PIN: both variants kept
        assert cls["technique"]["model"] == "CNN, RNN; CNN,RNN"

class TestNumericAveraging:
    def test_string_relevance_silently_excluded_from_average(self, seed_paper):
        """A relevance returned as "7" (string) is skipped by the
        isinstance(int, float) check, biasing the average."""
        seed_paper(
            {"relevance": 6},
            {"relevance": "10"},   # string – excluded
            {"relevance": 8},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        assert cls["relevance"] == pytest.approx(7.0)   # (6+8)/2, NOT (6+10+8)/3

    def test_average_score_truncated_to_int(self, seed_paper):
        seed_paper(
            {"estimated_score": 7},
            {"estimated_score": 8},
            {"estimated_score": 8},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        # (7+8+8)/3 = 7.666… → int() → 7
        assert cls["estimated_score"] == 7

    def test_verified_derived_from_score_threshold_7(self, seed_paper):
        seed_paper(
            {"estimated_score": 7},
            {"estimated_score": 6},
            {"estimated_score": 9},
        )
        db.recalculate_main_set("p1")
        cls = json.loads(db.get_paper_by_id("p1")["classification"])
        # scores ≥7 → [1, 0, 1] → majority verified=True
        assert cls["verified"] is True
        assert cls["verified_by"] == "computer"

def test_user_override_count_NOT_reset_after_ai_reclassification(test_db, seed_paper):
    """After AI reclassifies, classification == last_llm_classification,
    so the true override count is 0. But recalculate_main_set never
    touches the user_override_count column → stale number is displayed."""
    seed_paper({"is_offtopic": False}, {"is_offtopic": False}, {"is_offtopic": False})
    db.recalculate_main_set("p1")

    # User overrides one field
    db.update_paper_custom_fields("p1", {"is_offtopic": "true"}, changed_by="user")
    assert db.get_paper_by_id("p1")["user_override_count"] == 1

    # AI reclassifies (same value the user set, so no real disagreement)
    seed_paper({"is_offtopic": True}, {"is_offtopic": True}, {"is_offtopic": True})
    db.recalculate_main_set("p1")

    paper = db.get_paper_by_id("p1")
    # classification now equals last_llm_classification → true count is 0
    assert paper["classification"] == paper["last_llm_classification"]
    # PIN CURRENT BEHAVIOUR (stale count survives):
    assert paper["user_override_count"] == 1   # ← arguably should be 0


