import json

import pytest

from meta import agreement_core
from shared import db


@pytest.fixture()
def log_db(test_db):
    """Seed papers with various log states. Returns a helper + the db path."""
    def _insert(paper_id, set_logs):
        with db.get_db() as conn:
            conn.execute("""
                INSERT INTO papers (id, title, set_1_llm_log, set_2_llm_log, set_3_llm_log)
                VALUES (?, ?, ?, ?, ?)
            """, (
                paper_id, "T",
                json.dumps(set_logs.get(1, [])),
                json.dumps(set_logs.get(2, [])),
                json.dumps(set_logs.get(3, [])),
            ))
    return _insert


def test_counts_valid_and_invalid_entries(test_db, log_db):
    log_db("p1", {
        1: [
            {"type": "classifier", "valid": True},
            {"type": "classifier", "valid": False},
            {"type": "verifier", "valid": True},
        ],
        2: [{"type": "classifier", "valid": True}],
    })
    result = agreement_core.analyze_llm_logs(test_db, ["p1"])
    ls = result["log_stats"]
    assert ls["total_entries"] == 4
    assert ls["invalid_entries"] == 1
    assert len(ls["papers_with_invalid"]) == 1
    assert ls["papers_with_invalid"][0]["paper_id"] == "p1"


def test_consensus_run_counting(test_db, log_db):
    log_db("p1", {
        1: [
            {"type": "classifier", "valid": True},
            {"type": "consensus", "valid": True},
            {"type": "consensus", "valid": True},
        ],
        2: [{"type": "classifier", "valid": True}],
        3: [{"type": "classifier", "valid": True}],
    })
    result = agreement_core.analyze_llm_logs(test_db, ["p1"])
    cs = result["consensus_stats"]
    assert cs["total_classify_runs"] == 5  # 3 in set1 + 1 in set2 + 1 in set3
    assert cs["num_sets_analyzed"] == 3
    assert cs["max_runs"] == 3
    assert cs["max_runs_paper"] == "p1"
    assert cs["max_runs_set"] == 1


def test_invalid_entries_counted_per_paper(test_db, log_db):
    log_db("p1", {
        1: [
            {"type": "classifier", "valid": True},
            {"type": "classifier", "valid": False},
        ],
    })
    log_db("p2", {
        1: [{"type": "classifier", "valid": True}],
    })
    result = agreement_core.analyze_llm_logs(test_db, ["p1", "p2"])
    ls = result["log_stats"]
    assert ls["total_entries"] == 3
    assert ls["invalid_entries"] == 1
    assert len(ls["papers_with_invalid"]) == 1
    assert ls["papers_with_invalid"][0]["paper_id"] == "p1"


def test_empty_paper_list_returns_empty(test_db):
    result = agreement_core.analyze_llm_logs(test_db, [])
    assert result["log_stats"]["total_entries"] == 0
    assert result["consensus_stats"]["avg_runs"] == 0.0