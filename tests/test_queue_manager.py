# tests/test_queue_manager.py
"""
High-impact tests for the queue manager.

Philosophy:
  - Only scenarios the frontend can actually produce.
  - The LLM is mocked deterministically (canned responses); we never test the LLM.
  - A correctly-formatted-but-wrong answer is NOT an error (that's the verifier's job).
  - Errors are: invalid output saved as valid, valid output discarded, or invalid
    output silently degrading into wrong-but-plausible data.

Seeding note: the shared seed_paper fixture json.dumps()es its arguments, so
passing None writes the literal string 'null'. Use seed_blobs() below when a
column must remain a real SQL NULL (truly unclassified), and simply DON'T call
seed_paper for fresh papers (requesting the fixture already inserts 'p1').
"""
import json
import threading
import time

import pytest

from shared import config, db
from queue_manager import create_queue_app
from queue_manager.dispatcher import _send_to_vllm_sync, can_admit_task, dispatcher_loop
from queue_manager.state import (
    TASK_CLASSIFY, TASK_VERIFY, TASK_RECLASSIFY,
    ClassificationStateMachine, VerificationStateMachine, ConsensusStateMachine,
    state,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_queue_state():
    """The queue state is a module-level singleton; isolate it per test."""
    def _clear():
        with state.lock:
            state.task_queue.clear()
            for k in state.in_flight:
                state.in_flight[k] = 0
            state.shutdown = False
    _clear()
    yield
    _clear()


@pytest.fixture()
def mock_llm(monkeypatch):
    """Deterministic LLM: append (content, model_name, reasoning_trace) tuples;
    each dispatch pops one. Returning content=None simulates 'vLLM not running'."""
    responses = []

    def fake_send(prompt, server_url_base=None, model_name="default", is_verification=False):
        return responses.pop(0)

    monkeypatch.setattr(config, "send_prompt_to_llm", fake_send)
    return responses


@pytest.fixture()
def make_client(test_db, mock_llm, monkeypatch):
    """Flask test client over the real queue app; optionally with a live dispatcher."""
    # Routes call config.get_model_alias(), which would attempt a REAL HTTP GET
    # against the LLM server and burn ~4s in connection retries per request.
    monkeypatch.setattr(config, "get_model_alias", lambda url: "mock-model")

    threads = []

    def _make(run_dispatcher=True):
        app = create_queue_app(test_db)
        app.config["TESTING"] = True
        if run_dispatcher:
            t = threading.Thread(target=dispatcher_loop, daemon=True)
            t.start()
            threads.append(t)
        return app.test_client()

    yield _make
    state.request_shutdown()
    for t in threads:
        t.join(timeout=5)


# ============================================================================
# Helpers
# ============================================================================

def make_valid_classify(**overrides):
    """A classify blob guaranteed to satisfy validate_llm_output() for whatever
    domain config the test fixtures define (built dynamically, not hardcoded)."""
    blob = {}
    for field in config.get_required_classification_fields():
        blob[field] = 7 if field == "relevance" else False
    blob["is_offtopic"] = False
    blob["relevance"] = 7
    blob.update(overrides)
    return blob


VALID_VERIFY = {"verified": True, "estimated_score": 8}


def seed_blobs(*blobs):
    """Seed set_N_llm blobs positionally. None writes a REAL SQL NULL
    (truly unclassified) - unlike the shared seed_paper fixture, which would
    json.dumps(None) into the string 'null'."""
    with db.get_db() as conn:
        for sn, blob in enumerate(blobs, start=1):
            conn.execute(
                f"UPDATE papers SET set_{sn}_llm = ? WHERE id='p1'",
                (json.dumps(blob) if blob is not None else None,),
            )


def run_task(state_machine, mock_llm, content, model="mock-model", trace=""):
    """Push one task through the REAL dispatch seam (_send_to_vllm_sync):
    canned LLM response -> JSON parse -> validation -> state machine -> DB."""
    mock_llm.append((content, model, trace))
    task = state_machine.get_prompts()[0]
    state.increment_in_flight(task["task_type"])
    _send_to_vllm_sync(task)  # synchronous; returns after DB writes complete


def paper():
    return db.get_paper_by_id("p1")


def set_log(set_num):
    return json.loads(paper()[f"set_{set_num}_llm_log"] or "[]")


def wait_until(cond, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


# ============================================================================
# TIER A - LLM output injection matrix (the highest-value seam)
# ============================================================================

class TestClassifyOutputInjection:

    def test_perfect_output_is_saved_and_valid(self, test_db, seed_paper, mock_llm):
        blob = make_valid_classify(relevance=9)
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))

        p = paper()
        assert json.loads(p["set_1_llm"]) == blob                  # blob saved verbatim
        assert set_log(1)[-1]["valid"] is True                     # stamped valid
        main = json.loads(p["classification"])
        assert main["is_offtopic"] is False                        # recalc ran
        assert p["changed_by"] == "LLM_Classify_Set1"
        assert state.get_total_in_flight() == 0                    # no in-flight leak

    @pytest.mark.parametrize("content", [
        pytest.param("not json at all", id="plain-text"),
        pytest.param("[1, 2, 3]", id="json-array-not-dict"),
        pytest.param("{}", id="empty-object"),
        pytest.param('```json\n{"is_offtopic": false}\n```', id="code-fenced"),
    ], ids=str)
    def test_bad_output_is_invalid_and_blob_untouched(self, test_db, seed_paper,
                                                      mock_llm, content):
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, content)

        assert paper()["set_1_llm"] is None                        # blob NOT written (still SQL NULL)
        entry = set_log(1)[-1]
        assert entry["valid"] is False                             # stamped invalid
        assert json.loads(paper()["classification"]) == {}         # recalc not polluted

    def test_missing_required_field_names_the_field(self, test_db, seed_paper, mock_llm):
        blob = make_valid_classify()
        del blob["is_offtopic"]                                    # universal field missing
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))

        entry = set_log(1)[-1]
        assert entry["valid"] is False
        assert "is_offtopic" in entry["invalid_reason"]
        assert paper()["set_1_llm"] is None

    def test_stray_extra_fields_are_tolerated(self, test_db, seed_paper, mock_llm):
        """Downstream ignores unknown keys; validation must not reject them."""
        blob = make_valid_classify(unexpected_junk={"nested": 123})
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        assert set_log(1)[-1]["valid"] is True

    def test_string_numbers_are_normalized_before_save(self, test_db, seed_paper, mock_llm):
        blob = make_valid_classify(relevance="8")                  # string number
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        saved = json.loads(paper()["set_1_llm"])
        assert saved["relevance"] == 8 and isinstance(saved["relevance"], int)

    def test_string_booleans_are_normalized_to_real_booleans(self, test_db, seed_paper,
                                                             mock_llm):
        """A stringified boolean must be stored as a real JSON boolean; stored as
        a string it would vote as NULL in averaging despite being stamped valid."""
        blob = make_valid_classify(is_offtopic="false")
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        assert set_log(1)[-1]["valid"] is True
        saved = json.loads(paper()["set_1_llm"])
        assert saved["is_offtopic"] is False                      # real bool, not "false"


    def test_formatted_lie_is_accepted_by_design(self, test_db, seed_paper, mock_llm):
        """Truthfulness is the verifier's job, not the validator's."""
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(make_valid_classify(is_offtopic=True)))
        assert set_log(1)[-1]["valid"] is True

    def test_llm_down_logs_invalid_and_corrupts_nothing(self, test_db, seed_paper,
                                                        mock_llm):
        """Mirrors the real-world 'started without vLLM' incident."""
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, None)                                    # content=None
        assert set_log(1)[-1]["valid"] is False
        assert paper()["set_1_llm"] is None
        assert json.loads(paper()["classification"]) == {}


class TestVerifyOutputInjection:

    def test_verify_merges_into_existing_blob(self, test_db, seed_paper, mock_llm):
        classify_blob = make_valid_classify()
        seed_blobs(classify_blob)
        run_task(VerificationStateMachine("p1", 1, config.VERIFIER_TEMPLATE, "mock"),
                 mock_llm, json.dumps(VALID_VERIFY))

        saved = json.loads(paper()["set_1_llm"])
        assert saved["verified"] is True                           # merged in
        assert saved["estimated_score"] == 8
        assert saved["is_offtopic"] is False                       # classify fields kept
        assert set_log(1)[-1]["type"] == "verifier"

    def test_invalid_verify_leaves_blob_untouched(self, test_db, seed_paper, mock_llm):
        classify_blob = make_valid_classify()
        seed_blobs(classify_blob)
        run_task(VerificationStateMachine("p1", 1, config.VERIFIER_TEMPLATE, "mock"),
                 mock_llm, json.dumps({"verified": True}))          # missing score
        assert json.loads(paper()["set_1_llm"]) == classify_blob
        assert set_log(1)[-1]["valid"] is False


# ============================================================================
# TIER B - Consensus state machine transitions
# ============================================================================

def make_consensus_sm():
    sm = ConsensusStateMachine("p1", 1, config.PROMPT_TEMPLATE, config.VERIFIER_TEMPLATE,
                               config.RECLASSIFY_PROMPT_TEMPLATE, "mock")
    sm.max_iterations = 5          # instance attrs, safe to override in tests
    sm.fresh_fallback = 99
    return sm


def complete(sm, ok, data):
    sm.on_task_complete(ok, data, "mock", "", json.dumps(data) if data else "")


def drain_enqueued():
    """The task the state machine enqueued as follow-up (None if it stopped).
    Also asserts the invariant: consensus enqueues exactly ONE task per step."""
    task = state.dequeue()
    assert not state.task_queue
    return task


class TestConsensusTransitions:
    """The consensus state machine is SELF-DRIVING: on_task_complete() internally
    calls get_next_task() and enqueues the follow-up into the real queue - the
    route only seeds the first task. These tests therefore complete a task and
    then dequeue what the SM enqueued next. Calling get_next_task() manually
    after a completion would double-step the machine (and double-increment the
    iteration counter)."""

    def test_happy_path_classify_verify_done(self, test_db, seed_paper):
        sm = make_consensus_sm()
        task = sm.get_next_task()                      # route seeds the first task
        assert task["task_type"] == TASK_CLASSIFY
        complete(sm, True, make_valid_classify())
        assert drain_enqueued()["task_type"] == TASK_VERIFY
        complete(sm, True, VALID_VERIFY)
        assert drain_enqueued() is None                # consensus reached

    def test_rejected_verification_triggers_reclassify(self, test_db, seed_paper):
        sm = make_consensus_sm()
        sm.get_next_task()
        complete(sm, True, make_valid_classify())
        assert drain_enqueued()["task_type"] == TASK_VERIFY
        complete(sm, True, {"verified": False, "estimated_score": 3})
        assert drain_enqueued()["task_type"] == TASK_RECLASSIFY

    def test_low_score_alone_triggers_reclassify(self, test_db, seed_paper):
        sm = make_consensus_sm()
        sm.get_next_task()
        complete(sm, True, make_valid_classify())
        drain_enqueued()                                # verify
        complete(sm, True, {"verified": True, "estimated_score": 7})
        assert drain_enqueued()["task_type"] == TASK_RECLASSIFY   # score <= 7

    def test_fresh_fallback_reclassifies_from_scratch(self, test_db, seed_paper):
        sm = make_consensus_sm()
        sm.fresh_fallback = 1
        sm.get_next_task()
        complete(sm, True, make_valid_classify())
        drain_enqueued()                                # verify
        complete(sm, True, {"verified": False, "estimated_score": 2})
        task = drain_enqueued()
        assert task["task_type"] == TASK_CLASSIFY       # fresh, not reclassify
        assert sm.iteration == 1

    def test_stops_at_max_iterations(self, test_db, seed_paper):
        sm = make_consensus_sm()
        sm.max_iterations = 1
        sm.get_next_task()
        complete(sm, True, make_valid_classify())
        assert drain_enqueued()["task_type"] == TASK_VERIFY
        complete(sm, True, {"verified": False, "estimated_score": 2})
        assert drain_enqueued()["task_type"] == TASK_RECLASSIFY   # iteration -> 1
        complete(sm, True, make_valid_classify())
        assert drain_enqueued() is None                 # capped: nothing more enqueued

    def test_persistent_invalid_output_retries_same_stage(self, test_db, seed_paper):
        """DOCUMENTS BEHAVIOR: a classify stage that keeps failing never
        increments the iteration counter, so it retries indefinitely rather
        than hitting max_iterations."""
        sm = make_consensus_sm()
        sm.get_next_task()
        complete(sm, False, None)
        assert drain_enqueued()["task_type"] == TASK_CLASSIFY
        complete(sm, False, None)
        assert drain_enqueued()["task_type"] == TASK_CLASSIFY
        assert sm.iteration == 0


# ============================================================================
# TIER C - Averaging contract (what the frontend is guaranteed to see)
#
# The actual contract of calculate_field_certainty:
#   - ANY Yes+No dissent -> 'conflict', even with a 2-vs-1 majority
#     (the main value still takes the majority).
#   - '80' / '60' encode MISSING votes only (one / two nulls, no dissent).
# ============================================================================

class TestRecalculateMainSet:

    def test_two_vs_one_majority_decides_but_is_flagged_conflict(self, test_db, seed_paper):
        seed_paper(
            {"is_offtopic": True,  "relevance": 6, "estimated_score": 8},
            {"is_offtopic": True,  "relevance": 8, "estimated_score": 6},
            {"is_offtopic": False, "relevance": 4, "estimated_score": 9},
        )
        db.recalculate_main_set("p1", changed_by="test")
        main = json.loads(paper()["classification"])
        cert = json.loads(paper()["main_certainty"])

        assert main["is_offtopic"] is True                         # 2 vs 1 majority decides
        assert cert["is_offtopic"] == "conflict"                   # ...but dissent is flagged
        assert main["relevance"] == pytest.approx(6.0)             # averaged
        assert main["verified"] is True                            # scores 8,6,9 -> 2x >=7
        assert main["estimated_score"] == 8                        # round(23/3)
        assert paper()["user_override_count"] == 0

    def test_two_agree_one_missing_gives_80(self, test_db, seed_paper):
        """No dissent, one set silent -> '80'. This is what '80' actually means."""
        seed_paper(
            {"is_offtopic": True},
            {"is_offtopic": True},
            {},                                                    # no opinion
        )
        db.recalculate_main_set("p1", changed_by="test")
        main = json.loads(paper()["classification"])
        cert = json.loads(paper()["main_certainty"])
        assert main["is_offtopic"] is True
        assert cert["is_offtopic"] == "80"

    def test_yes_no_tie_is_conflict_with_null_main(self, test_db, seed_paper):
        seed_paper(
            {"is_offtopic": True},
            {"is_offtopic": False},
            {},
        )
        db.recalculate_main_set("p1", changed_by="test")
        main = json.loads(paper()["classification"])
        cert = json.loads(paper()["main_certainty"])
        assert main["is_offtopic"] is None
        assert cert["is_offtopic"] == "conflict"


# ============================================================================
# TIER E - Admission control (deterministic concurrency policy, no timing)
# ============================================================================

class TestAdmissionControl:

    def test_homogeneous_limit(self):
        state.in_flight[TASK_CLASSIFY] = config.MAX_CONCURRENT_WORKERS_CLASSIFY
        assert can_admit_task(TASK_CLASSIFY) is False
        state.in_flight[TASK_CLASSIFY] -= 1
        assert can_admit_task(TASK_CLASSIFY) is True

    def test_mixed_mode_is_capped_by_min_threshold(self):
        state.in_flight[TASK_CLASSIFY] = 1                          # other type running
        state.in_flight[TASK_VERIFY] = config.MIN_CONCURRENT_WORKERS - 1
        assert can_admit_task(TASK_VERIFY) is False                 # at threshold
        state.in_flight[TASK_VERIFY] -= 1
        assert can_admit_task(TASK_VERIFY) is True


# ============================================================================
# TIER D - End-to-end: Flask route -> queue -> real dispatcher -> DB
# ============================================================================

class TestEndToEnd:

    def test_single_paper_classify_full_pipeline(self, test_db, seed_paper, make_client,
                                                 mock_llm):
        blob = json.dumps(make_valid_classify())
        mock_llm.extend([(blob, "mock", "") for _ in range(3)])     # one per set

        client = make_client(run_dispatcher=True)
        resp = client.post("/classify", json={"mode": "id", "paper_id": "p1"})
        assert resp.status_code == 200

        p = paper()
        for sn in (1, 2, 3):
            assert json.loads(p[f"set_{sn}_llm"])["is_offtopic"] is False
            assert set_log(sn)[-1]["valid"] is True
        assert json.loads(p["classification"])["is_offtopic"] is False
        assert any(e["type"] == "averaged_llm" for e in json.loads(p["llm_log"]))
        assert wait_until(lambda: state.get_total_in_flight() == 0
                          and not state.task_queue)

    def test_single_paper_classify_with_llm_down(self, test_db, seed_paper, make_client,
                                                 mock_llm):
        """The exact 1200-paper incident: request completes, entries are invalid,
        nothing is corrupted, the paper can simply be re-classified later."""
        mock_llm.extend([(None, "mock", "Connection Error") for _ in range(3)])

        client = make_client(run_dispatcher=True)
        resp = client.post("/classify", json={"mode": "id", "paper_id": "p1"})
        assert resp.status_code == 200                              # route still completes

        p = paper()
        assert json.loads(p["classification"]) == {}
        for sn in (1, 2, 3):
            assert p[f"set_{sn}_llm"] is None
            assert set_log(sn)[-1]["valid"] is False
        assert wait_until(lambda: state.get_total_in_flight() == 0)

    def test_single_paper_consensus_reaches_verified(self, test_db, seed_paper,
                                                     make_client, mock_llm):
        """/consensus mode='id' runs ONE consensus state machine PER SET (3 total),
        so the mock needs 3 classify + 3 verify responses. The dispatcher admits
        all three classify tasks first (homogeneous mode), so the first three
        canned responses are always consumed by classify tasks."""
        mock_llm.extend([(json.dumps(make_valid_classify()), "mock", "") for _ in range(3)])
        mock_llm.extend([(json.dumps(VALID_VERIFY), "mock", "") for _ in range(3)])

        client = make_client(run_dispatcher=True)
        resp = client.post("/consensus", json={"mode": "id", "paper_id": "p1"})
        assert resp.status_code == 200

        main = json.loads(paper()["classification"])
        assert main["verified"] is True
        assert main["estimated_score"] == 8
        assert wait_until(lambda: state.get_total_in_flight() == 0
                          and not state.task_queue)

    def test_batch_remaining_only_queues_unclassified_sets(self, test_db, seed_paper,
                                                           make_client):
        seed_blobs(make_valid_classify(), None, None)               # set 1 done; 2,3 real NULLs
        client = make_client(run_dispatcher=False)                  # inspect queue only
        resp = client.post("/classify", json={"mode": "remaining"})
        data = resp.get_json()
        assert data["papers_queued"] == 2                           # sets 2 and 3 only
        assert data["tasks_queued"] == 2

    def test_batch_verify_remaining_requires_classified_sets(self, test_db, seed_paper,
                                                             make_client):
        seed_blobs(make_valid_classify(), make_valid_classify(), None)
        client = make_client(run_dispatcher=False)
        resp = client.post("/verify", json={"mode": "remaining"})
        assert resp.get_json()["papers_queued"] == 2                # classified, unverified


# ============================================================================
# ROUND 2 - filling the audit gaps
# ============================================================================

def seed_blob_for(pid, set_num, blob):
    with db.get_db() as conn:
        conn.execute(f"UPDATE papers SET set_{set_num}_llm = ? WHERE id = ?",
                     (json.dumps(blob) if blob is not None else None, pid))


class TestVerifyTypeHoles:
    """The verify-side mirror of the proven classify string-boolean gap."""

    def test_string_verified_true_is_normalized_at_write(self, test_db, seed_paper, mock_llm):
        seed_blobs(make_valid_classify())
        run_task(VerificationStateMachine("p1", 1, config.VERIFIER_TEMPLATE, "mock"),
                 mock_llm, json.dumps({"verified": "true", "estimated_score": "9"}))
        saved = json.loads(paper()["set_1_llm"])
        assert saved["verified"] is True
        assert saved["estimated_score"] == 9

    def test_string_verified_false_triggers_reclassify(self, test_db, seed_paper):
        """The state machine must agree with the /consensus SQL gate, which treats
        verified IN (0, 'false', 'False') as unsettled. Pre-fix this returned None:
        a verifier rejection silently read as an approval."""
        blob = make_valid_classify()
        blob.update({"verified": "false", "estimated_score": 9})
        seed_blobs(blob)
        sm = make_consensus_sm()
        task = sm.get_next_task()
        assert task is not None
        assert task["task_type"] == TASK_RECLASSIFY



class TestConsensusBatchGate:
    """The /consensus batch SQL is the gate behind the frontend's
    'Classify Until Consensus' button. It duplicates the state machine's
    transition conditions in SQL - so the two can drift."""

    def test_gate_selects_exactly_the_unsettled_pairs(self, test_db, make_client):
        with db.get_db() as conn:
            conn.execute("INSERT INTO papers (id, title, year) VALUES "
                         "('p2', 'P2', 2024), ('p3', 'P3', 2024)")

        settled       = make_valid_classify(); settled.update({"verified": True,  "estimated_score": 8})
        classified    = make_valid_classify()                                    # no verified key
        rejected      = make_valid_classify(); rejected.update({"verified": False, "estimated_score": 3})
        low_score     = make_valid_classify(); low_score.update({"verified": True, "estimated_score": 5})
        string_false  = make_valid_classify(); string_false.update({"verified": "false", "estimated_score": 9})

        # p1: fully settled -> 0 pairs
        seed_blob_for("p1", 1, settled); seed_blob_for("p1", 2, settled); seed_blob_for("p1", 3, settled)
        # p2: unclassified + classified-unverified + rejected -> 3 pairs
        seed_blob_for("p2", 1, None);    seed_blob_for("p2", 2, classified); seed_blob_for("p2", 3, rejected)
        # p3: low score + string 'false' + unclassified -> 3 pairs
        seed_blob_for("p3", 1, low_score); seed_blob_for("p3", 2, string_false); seed_blob_for("p3", 3, None)

        client = make_client(run_dispatcher=False)
        data = client.post("/consensus", json={"mode": "all"}).get_json()

        assert data["papers_queued"] == 6                       # SQL gate counts all unsettled pairs
        assert data["tasks_queued"] == 6                        # was 5: the SM disagreed with its own SQL gate

class TestTextFieldMerging:

    def test_text_fields_merge_unique_preserving_set1_capitalization(self, test_db, seed_paper):
        seed_paper(
            make_valid_classify(technique_notes="CNN, RNN"),
            make_valid_classify(technique_notes="cnn,rnn"),       # same after normalization
            make_valid_classify(technique_notes="Transformer"),
        )
        db.recalculate_main_set("p1", changed_by="test")
        main = json.loads(paper()["classification"])
        assert main["technique_notes"] == "CNN, RNN; Transformer"

    def test_stringified_booleans_do_not_become_text(self, test_db, seed_paper):
        """Pins the _is_real_text guard: 'false'/'0'/'null' strings must vote as
        boolean-null, not be merged into a text field ('solid' certainty of None)."""
        seed_paper(
            make_valid_classify(methods="false"),
            make_valid_classify(methods="false"),
            make_valid_classify(methods="false"),
        )
        db.recalculate_main_set("p1", changed_by="test")
        main = json.loads(paper()["classification"])
        cert = json.loads(paper()["main_certainty"])
        assert main["methods"] is None
        assert cert["methods"] == "solid"


class TestTraceReview:
    """/review_traces: real frontend button, inline LLM call, audit-only write."""

    def test_appends_log_entry_without_touching_classification(self, test_db, seed_paper,
                                                               make_client, mock_llm):
        seed_blobs(make_valid_classify())
        db.recalculate_main_set("p1", changed_by="test")
        before = paper()["classification"]

        mock_llm.append(("All three sets converged cleanly.", "mock", "review thinking"))
        client = make_client(run_dispatcher=False)
        resp = client.post("/review_traces", json={"paper_id": "p1"})
        assert resp.status_code == 200

        p = paper()
        assert p["classification"] == before                  # audit-only: no recalc, no writes
        entry = json.loads(p["llm_log"])[-1]
        assert entry["type"] == "trace_review"
        assert entry["valid"] is True
        assert "report" in json.loads(entry["output"])


#####################################################################################
# the classes below should be moved to a new test file tests/test_llm_validation.py
#####################################################################################
class TestTriStateVerdict:
    """Fixture-independent unit tests for the core classifier."""
    @pytest.mark.parametrize("value,expected", [
        (True, "true"), ("true", "true"), ("True", "true"), ("TRUE", "true"),
        (1, "true"), ("1", "true"), ("yes", "true"), ("on", "true"),
        (False, "false"), ("false", "false"), (0, "false"), ("0", "false"),
        ("no", "false"), ("off", "false"),
        (None, "null"), ("null", "null"), ("none", "null"), ("unknown", "null"), ("", "null"),
        ("maybe", "unusable"), ("2", "unusable"), (2, "unusable"), (7, "unusable"),
        (0.5, "unusable"), ("mostly", "unusable"), ([], "unusable"), ({}, "unusable"),
    ])
    def test_verdicts(self, value, expected):
        assert config._tri_state_verdict(value) == expected


class TestMandatoryFieldRejection:
    """Universal fields are mandatory answers: null and unusable values are
    rejected so the run is retried."""

    def test_null_is_offtopic_is_rejected(self, test_db, seed_paper, mock_llm):
        blob = make_valid_classify(is_offtopic=None)
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        entry = set_log(1)[-1]
        assert entry["valid"] is False
        assert "is_offtopic" in entry["invalid_reason"]
        assert paper()["set_1_llm"] is None

    def test_null_relevance_is_rejected(self, test_db, seed_paper, mock_llm):
        blob = make_valid_classify(relevance=None)
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        entry = set_log(1)[-1]
        assert entry["valid"] is False
        assert "relevance" in entry["invalid_reason"]

    @pytest.mark.parametrize("bad", ["maybe", "2", 7, "unknown"])
    def test_unusable_is_offtopic_is_rejected(self, test_db, seed_paper, mock_llm, bad):
        blob = make_valid_classify(is_offtopic=bad)
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        assert set_log(1)[-1]["valid"] is False

    @pytest.mark.parametrize("good", [True, "true", 1, False, "false", 0])
    def test_lenient_is_offtopic_accepted(self, test_db, seed_paper, mock_llm, good):
        blob = make_valid_classify(is_offtopic=good)
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        assert set_log(1)[-1]["valid"] is True


class TestDomainFieldTriState:
    """Domain boolean fields accept null as a legitimate 'unknown' third state
    (never cast to False), while still rejecting unusable values."""

    def test_null_domain_boolean_is_accepted_as_unknown(self, test_db, seed_paper, mock_llm):
        domain_bools = [p for p in config.get_boolean_classification_fields() if p != 'is_offtopic']
        path = domain_bools[0]
        blob = make_valid_classify()
        cur = blob
        for k in path.split('.')[:-1]:
            cur = cur.setdefault(k, {})
        cur[path.split('.')[-1]] = None
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        assert set_log(1)[-1]["valid"] is True
        saved = json.loads(paper()["set_1_llm"])
        assert db._get_val_by_path(saved, path) is None      # kept as unknown, NOT False

    def test_unusable_domain_boolean_is_rejected(self, test_db, seed_paper, mock_llm):
        domain_bools = [p for p in config.get_boolean_classification_fields() if p != 'is_offtopic']
        path = domain_bools[0]
        blob = make_valid_classify()
        cur = blob
        for k in path.split('.')[:-1]:
            cur = cur.setdefault(k, {})
        cur[path.split('.')[-1]] = "maybe"
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        assert set_log(1)[-1]["valid"] is False


class TestNullAnswerValidation:
    """Presence is not an answer. A required field answered with null must be
    stamped invalid (and retried), never saved as a valid blob."""

    def test_null_required_field_is_rejected(self, test_db, seed_paper, mock_llm):
        blob = make_valid_classify(is_offtopic=None)
        run_task(ClassificationStateMachine("p1", 1, config.PROMPT_TEMPLATE, "mock"),
                 mock_llm, json.dumps(blob))
        entry = set_log(1)[-1]
        assert entry["valid"] is False
        assert "is_offtopic" in entry["invalid_reason"]
        assert paper()["set_1_llm"] is None

    def test_null_estimated_score_is_rejected_not_crashed(self, test_db, seed_paper,
                                                          mock_llm):
        """Pre-fix this raises TypeError (float(None)) inside the callback, killing
        the worker thread mid-task - in single-paper mode the HTTP request then
        hangs forever on its completion event."""
        seed_blobs(make_valid_classify())
        run_task(VerificationStateMachine("p1", 1, config.VERIFIER_TEMPLATE, "mock"),
                 mock_llm, json.dumps({"verified": True, "estimated_score": None}))
        entry = set_log(1)[-1]
        assert entry["valid"] is False
        assert json.loads(paper()["set_1_llm"]) == make_valid_classify()   # untouched
