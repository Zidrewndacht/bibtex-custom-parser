# tests/test_flatten_and_changed_fields.py
import json

from web.export_logic import _flatten_dict, prepare_history_log_data


class TestFlattenDict:
    def test_nested_dict_flattened_with_dots(self):
        d = {"features": {"smt": True, "tracks": False}, "is_survey": True}
        flat = _flatten_dict(d)
        assert flat == {
            "features.smt": True,
            "features.tracks": False,
            "is_survey": True,
        }

    def test_certainty_map_excluded(self):
        d = {"is_offtopic": False, "certainty_map": {"is_offtopic": "solid"}}
        flat = _flatten_dict(d)
        assert "certainty_map" not in flat
        assert "certainty_map.is_offtopic" not in flat
        assert flat["is_offtopic"] is False

    def test_deeply_nested(self):
        d = {"a": {"b": {"c": 42}}}
        assert _flatten_dict(d) == {"a.b.c": 42}

    def test_non_dict_returns_parent_key(self):
        assert _flatten_dict("hello", "root") == {"root": "hello"}


class TestChangedFieldsDetection:
    def _make_paper(self, entries):
        return {"llm_log": json.dumps(entries)}

    def test_identical_outputs_no_changes(self):
        paper = self._make_paper([
            {"type": "classifier", "timestamp": "T1", "valid": True,
             "output": '{"is_offtopic": false}'},
            {"type": "classifier", "timestamp": "T2", "valid": True,
             "output": '{"is_offtopic": false}'},
        ])
        result = prepare_history_log_data(paper)
        # Reversed: T2 first, T1 second
        assert result[0]["changed_fields"] == set()  # T2 vs T1: no change

    def test_single_field_change_detected(self):
        paper = self._make_paper([
            {"type": "classifier", "timestamp": "T1", "valid": True,
             "output": '{"is_offtopic": false, "relevance": 5}'},
            {"type": "classifier", "timestamp": "T2", "valid": True,
             "output": '{"is_offtopic": true, "relevance": 5}'},
        ])
        result = prepare_history_log_data(paper)
        assert "is_offtopic" in result[0]["changed_fields"]
        assert "relevance" not in result[0]["changed_fields"]

    def test_nested_field_change_detected(self):
        paper = self._make_paper([
            {"type": "classifier", "timestamp": "T1", "valid": True,
             "output": '{"features": {"smt": true}}'},
            {"type": "classifier", "timestamp": "T2", "valid": True,
             "output": '{"features": {"smt": false}}'},
        ])
        result = prepare_history_log_data(paper)
        assert "features.smt" in result[0]["changed_fields"]

    def test_malformed_output_treated_as_empty(self):
        paper = self._make_paper([
            {"type": "classifier", "timestamp": "T1", "valid": True,
             "output": '{"is_offtopic": false}'},
            {"type": "classifier", "timestamp": "T2", "valid": True,
             "output": "NOT VALID JSON"},
        ])
        result = prepare_history_log_data(paper)
        # T2 output becomes {} → all fields from T1 appear as "changed" (removed)
        assert "is_offtopic" in result[0]["changed_fields"]

    def test_invalid_entries_excluded_from_change_tracking(self):
        paper = self._make_paper([
            {"type": "classifier", "timestamp": "T1", "valid": True,
             "output": '{"is_offtopic": false}'},
            {"type": "classifier", "timestamp": "T2", "valid": False,
             "output": '{"is_offtopic": true}'},
            {"type": "classifier", "timestamp": "T3", "valid": True,
             "output": '{"is_offtopic": false}'},
        ])
        result = prepare_history_log_data(paper)
        # T3 is compared to T1 (T2 is invalid, skipped)
        t3_entry = result[0]  # reversed: T3, T2, T1
        assert t3_entry["changed_fields"] == set()  # T3 == T1