import json

from shared import db


def test_full_paper_lifecycle_integrity(test_db, seed_paper):
    # 1. Three independent classifications.
    #
    # Note:
    # - set_1_llm / set_2_llm / set_3_llm use nested JSON.
    # - main_certainty uses flattened dot-path keys.
    seed_paper(
        {"is_offtopic": False, "relevance": 8, "features": {"smt": True}},
        {"is_offtopic": False, "relevance": 7, "features": {"smt": True}},
        {"is_offtopic": False, "relevance": 9, "features": {"smt": False}},  # conflict
    )

    db.recalculate_main_set("p1")

    p = db.get_paper_by_id("p1")
    cls = json.loads(p["classification"])
    cert = json.loads(p["main_certainty"])

    assert cls["is_offtopic"] is False
    assert cls["relevance"] == 8.0

    # classification is nested
    assert cls["features"]["smt"] is True

    # certainty map is flat dot-path
    assert cert["features.smt"] == "conflict"

    # 2. Verifier scores all three sets
    for sn, score in [(1, 9), (2, 8), (3, 4)]:
        db.update_set_verifier(
            "p1",
            sn,
            {"verified": score >= 7, "estimated_score": score},
            model_name="m",
            reasoning_trace="",
            json_result="{}",
            valid=True,
        )

    # 3. Re-average picks up verifier data
    db.recalculate_main_set("p1")

    p = db.get_paper_by_id("p1")
    cls = json.loads(p["classification"])

    assert cls["verified"] is True
    assert cls["estimated_score"] == 7
    assert p["verified"] == 1
    assert p["verified_by"] == "computer"

    # 4. User overrides one field → verification must reset
    #
    # update_paper_custom_fields takes dot-path form.
    db.update_paper_custom_fields("p1", {"features.smt": "false"})

    p = db.get_paper_by_id("p1")
    cls = json.loads(p["classification"])

    assert p["verified"] is None
    assert p["user_override_count"] == 1
    assert cls["features"]["smt"] is False

    # 5. History log has the expected shape
    log = json.loads(p["llm_log"])
    types = [e["type"] for e in log]

    assert "averaged_llm" in types
    assert "user" in types