# tests/test_normalize_llm_blob.py
"""Unit tests for the write-time blob normalization function."""
import pytest
from shared.db import normalize_llm_blob

BOOL_FIELDS = ["is_offtopic", "features.smt"]


class TestBooleanNormalization:
    @pytest.mark.parametrize("raw, expected", [
        (1, True), (0, False),
        ("1", True), ("0", False),
        ("true", True), ("false", False),
        ("True", True), ("False", False),
        ("TRUE", True), ("FALSE", False),
        ("yes", True), ("no", False),
    ])
    def test_coerces_to_bool(self, raw, expected):
        blob = {"is_offtopic": raw}
        result = normalize_llm_blob(blob, BOOL_FIELDS)
        assert result["is_offtopic"] is expected

    def test_already_bool_untouched(self):
        blob = {"is_offtopic": True, "features": {"smt": False}}
        result = normalize_llm_blob(blob, BOOL_FIELDS)
        assert result["is_offtopic"] is True
        assert result["features"]["smt"] is False

    def test_none_untouched(self):
        blob = {"is_offtopic": None}
        result = normalize_llm_blob(blob, BOOL_FIELDS)
        assert result["is_offtopic"] is None

    def test_unrecognized_value_left_alone(self):
        blob = {"is_offtopic": "maybe"}
        result = normalize_llm_blob(blob, BOOL_FIELDS)
        assert result["is_offtopic"] == "maybe"

    def test_nested_boolean_normalized(self):
        blob = {"features": {"smt": 1}}
        result = normalize_llm_blob(blob, BOOL_FIELDS)
        assert result["features"]["smt"] is True

    def test_missing_path_ignored(self):
        blob = {"other": "data"}
        result = normalize_llm_blob(blob, BOOL_FIELDS)
        assert result == {"other": "data"}


class TestNumericNormalization:
    @pytest.mark.parametrize("raw, expected", [
        ("10", 10), ("7.5", 7.5), ("0", 0),
    ])
    def test_string_numbers_coerced(self, raw, expected):
        blob = {"relevance": raw}
        result = normalize_llm_blob(blob, [], numeric_paths=["relevance"])
        assert result["relevance"] == expected

    def test_int_untouched(self):
        blob = {"relevance": 8}
        result = normalize_llm_blob(blob, [], numeric_paths=["relevance"])
        assert result["relevance"] == 8

    def test_unparseable_string_left_alone(self):
        blob = {"relevance": "high"}
        result = normalize_llm_blob(blob, [], numeric_paths=["relevance"])
        assert result["relevance"] == "high"