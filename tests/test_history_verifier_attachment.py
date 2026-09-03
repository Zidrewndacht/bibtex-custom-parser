import json

from web.export_logic import prepare_history_log_data


def test_verifier_attaches_to_preceding_valid_classifier():
    paper = {
        'llm_log': json.dumps([
            {"type": "classifier", "timestamp": "T1", "valid": True, "output": "{}"},
            {"type": "verifier", "timestamp": "T2", "valid": True, "output": {"verified": 1, "estimated_score": 8}, "trace": "", "model": "v1"},
        ])
    }
    res = prepare_history_log_data(paper)
    # Result is reversed (newest first)
    assert res[0]['type'] == 'verifier'
    assert res[1]['type'] == 'classifier'
    assert res[1]['verification_data']['verified'] == 1

def test_verifier_skips_invalid_classifier():
    paper = {
        'llm_log': json.dumps([
            {"type": "classifier", "timestamp": "T1", "valid": True, "output": "{}"},
            {"type": "classifier", "timestamp": "T2", "valid": False, "output": "{}"},
            {"type": "verifier", "timestamp": "T3", "valid": True, "output": {"verified": 1}, "trace": "", "model": "v1"},
        ])
    }
    res = prepare_history_log_data(paper)
    # Reversed: T3(verifier), T2(invalid), T1(valid)
    assert res[1]['valid'] is False
    assert res[1]['verification_data'] is None # Invalid doesn't consume
    assert res[2]['valid'] is True
    assert res[2]['verification_data'] is not None # Consumes it!

def test_averaged_llm_does_not_consume_verifier():
    paper = {
        'llm_log': json.dumps([
            {"type": "classifier", "timestamp": "T1", "valid": True, "output": "{}"},
            {"type": "averaged_llm", "timestamp": "T2", "valid": True, "output": "{}"},
            {"type": "verifier", "timestamp": "T3", "valid": True, "output": {"verified": 1}, "trace": "", "model": "v1"},
        ])
    }
    res = prepare_history_log_data(paper)
    assert res[1]['type'] == 'averaged_llm'
    assert res[1]['verification_data'] is None
    assert res[2]['type'] == 'classifier'
    assert res[2]['verification_data'] is not None

def test_multiple_verifiers_drops_latest_bug():
    """PINS CURRENT BUG: If verified twice, the loop overwrites the cache 
    with the older verifier, dropping the newest one."""
    paper = {
        'llm_log': json.dumps([
            {"type": "classifier", "timestamp": "T1", "valid": True, "output": "{}"},
            {"type": "verifier", "timestamp": "T2", "valid": True, "output": {"verified": 0, "estimated_score": 2}, "trace": "", "model": "v1"},
            {"type": "verifier", "timestamp": "T3", "valid": True, "output": {"verified": 1, "estimated_score": 9}, "trace": "", "model": "v2"},
        ])
    }
    res = prepare_history_log_data(paper)
    classifier_entry = next(e for e in res if e['type'] == 'classifier')
    
    # PIN CURRENT BEHAVIOR: It attaches T2 (score 2) instead of T3 (score 9)
    assert classifier_entry['verification_data']['estimated_score'] == 2