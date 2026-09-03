# tests/test_agreement_encoding_consistency.py
import json

import pytest

from meta import agreement_core
from shared import db


@pytest.fixture()
def seeded_db(test_db):
    """Seed a paper where Set 2 uses int 1/0 instead of booleans."""
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO papers (id, title, year, set_1_llm, set_2_llm, set_3_llm)
            VALUES ('p1', 'T', 2024, ?, ?, ?)
        """, (
            json.dumps({"is_offtopic": True, "relevance": 8}),
            json.dumps({"is_offtopic": 1, "relevance": 7}),   # int, not bool
            json.dumps({"is_offtopic": True, "relevance": 9}),
        ))
    return test_db


class TestEncodingDivergence:
    """Pins the current inconsistency between main classification
    and agreement report encoding for int-typed booleans."""

    def test_recalculate_treats_int_as_unknown(self, seeded_db):
        db.recalculate_main_set("p1")
        paper = db.get_paper_by_id("p1")
        cert = json.loads(paper["main_certainty"])
        # int 1 is dropped → [True, None, True] → '80' not 'solid'
        assert cert["is_offtopic"] == "80"

    def test_agreement_report_treats_int_as_valid_vote(self, seeded_db):
        papers = agreement_core.load_all_papers_from_single_db(
            seeded_db, ["is_offtopic"]
        )
        # agreement_core encodes int 1 as 2 (Yes) — lenient
        assert papers["p1"][1]["is_offtopic"] == 2  # Set 1: True → 2
        assert papers["p1"][2]["is_offtopic"] == 2  # Set 2: int 1 → 2 (!)
        assert papers["p1"][3]["is_offtopic"] == 2  # Set 3: True → 2

    def test_agreement_reports_perfect_while_ui_shows_partial(self, seeded_db):
        """The agreement report says 'perfect' but the UI shows 80% translucency."""
        db.recalculate_main_set("p1")
        cert = json.loads(db.get_paper_by_id("p1")["main_certainty"])

        papers = agreement_core.load_all_papers_from_single_db(
            seeded_db, ["is_offtopic"]
        )
        values = [papers["p1"][sn]["is_offtopic"] for sn in (1, 2, 3)]
        agreement = agreement_core.classify_3run_agreement(values)

        # PIN: disagreement between the two systems
        assert cert["is_offtopic"] == "80"       # UI says partial
        assert agreement == "perfect"             # Report says perfect