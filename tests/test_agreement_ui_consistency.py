# tests/test_agreement_ui_consistency.py
"""After write-time normalization, the agreement report and the main UI
must produce consistent results for the same votes."""
import json
import pytest
from meta import agreement_core
from shared import db


@pytest.fixture()
def seeded_db(test_db):
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO papers (id, title, year, set_1_llm, set_2_llm, set_3_llm)
            VALUES ('p1', 'T', 2024, ?, ?, ?)
        """, (
            json.dumps({"is_offtopic": True, "relevance": 8}),
            json.dumps({"is_offtopic": True, "relevance": 7}),
            json.dumps({"is_offtopic": True, "relevance": 9}),
        ))
    return test_db


class TestAgreementUIConsistency:
    def test_unanimous_votes_solid_and_perfect(self, seeded_db):
        db.recalculate_main_set("p1")
        cert = json.loads(db.get_paper_by_id("p1")["main_certainty"])

        papers = agreement_core.load_all_papers_from_single_db(
            seeded_db, ["is_offtopic"])
        values = [papers["p1"][sn]["is_offtopic"] for sn in (1, 2, 3)]
        agreement = agreement_core.classify_3run_agreement(values)

        assert cert["is_offtopic"] == "solid"
        assert agreement == "perfect"

    def test_partial_agreement_consistent(self, seeded_db):
        with db.get_db() as conn:
            conn.execute("UPDATE papers SET set_2_llm = ? WHERE id = 'p1'",
                         (json.dumps({"relevance": 7}),))
        db.recalculate_main_set("p1")
        cert = json.loads(db.get_paper_by_id("p1")["main_certainty"])

        papers = agreement_core.load_all_papers_from_single_db(
            seeded_db, ["is_offtopic"])
        values = [papers["p1"][sn]["is_offtopic"] for sn in (1, 2, 3)]
        agreement = agreement_core.classify_3run_agreement(values)

        assert cert["is_offtopic"] == "80"
        assert agreement == "uncertain_biased_certain"

    def test_conflict_consistent(self, seeded_db):
        with db.get_db() as conn:
            conn.execute("UPDATE papers SET set_2_llm = ? WHERE id = 'p1'",
                         (json.dumps({"is_offtopic": False, "relevance": 7}),))
        db.recalculate_main_set("p1")
        cert = json.loads(db.get_paper_by_id("p1")["main_certainty"])

        papers = agreement_core.load_all_papers_from_single_db(
            seeded_db, ["is_offtopic"])
        values = [papers["p1"][sn]["is_offtopic"] for sn in (1, 2, 3)]
        agreement = agreement_core.classify_3run_agreement(values)

        assert cert["is_offtopic"] == "conflict"
        assert agreement == "contradiction_biased_yes"