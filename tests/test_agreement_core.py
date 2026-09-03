import pytest

from meta.agreement_core import classify_3run_agreement


@pytest.mark.parametrize("values, expected", [
    ([2, 2, 2], "perfect"),
    ([1, 1, 1], "perfect"),
    ([0, 0, 0], "perfect"),
    ([2, 2, 1], "contradiction_biased_yes"),
    ([2, 1, 1], "contradiction_biased_no"),
    ([2, 1, 0], "contradiction_chaotic"),
    ([2, 2, 0], "uncertain_biased_certain"),
    ([1, 1, 0], "uncertain_biased_certain"),
    ([2, 0, 0], "uncertain_biased_uncertain"),
    ([1, 0, 0], "uncertain_biased_uncertain"),
])
def test_all_ten_vote_patterns(values, expected):
    assert classify_3run_agreement(values) == expected


def test_permutation_invariance():
    """Order of the 3 sets must not matter."""
    import itertools
    for combo in ([2,2,1], [2,1,0], [2,2,0]):
        results = {classify_3run_agreement(list(p))
                   for p in itertools.permutations(combo)}
        assert len(results) == 1, f"order-sensitive result for {combo}"