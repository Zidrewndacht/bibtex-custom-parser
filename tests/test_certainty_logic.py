import pytest

from shared.db import calculate_field_certainty


# values: 1 = Yes, 0 = No, None = Unknown
@pytest.mark.parametrize(
    "values, expected_value, expected_certainty",
    [
        # Unanimous
        ([1, 1, 1],       1,    "solid"),
        ([0, 0, 0],       0,    "solid"),
        # "solid unknown" – This is not a bug. 
        # Three unknowns mean the data is for sure unknown (e.g. not provided by the source)
        ([None, None, None], None, "solid"),   
        # Partial agreement (no Yes↔No conflict) → translucent emoji
        ([1, 1, None],    1,    "80"),
        ([1, None, None], 1,    "60"),
        ([0, 0, None],    0,    "80"),
        ([0, None, None], 0,    "60"),
        # Any Yes AND No present → conflict, even with a 2-vs-1 majority
        ([1, 1, 0],       1,    "conflict"),
        ([1, 0, 0],       0,    "conflict"),
        ([1, 0, None],    None, "conflict"),   # chaotic: no majority at all
    ],
)
def test_calculate_field_certainty_full_truth_table(values, expected_value, expected_certainty):
    val, cert = calculate_field_certainty(values)
    assert val == expected_value
    assert cert == expected_certainty

# This is a nonsense test for a case that would never haappen at all.
# Left commented here because removing it could make someone else write it again:
# def test_wrong_length_returns_none_solid():
#     assert calculate_field_certainty([1, 1]) == (None, "solid")
#     assert calculate_field_certainty([]) == (None, "solid")