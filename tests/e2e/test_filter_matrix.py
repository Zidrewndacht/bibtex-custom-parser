# tests/e2e/test_filter_matrix.py
"""
Tri-state and inclusion filtering, tested on BOTH the live server-rendered
app and the client-only static HTML export.
"""
import re
from playwright.sync_api import expect
from conftest import (
    INITIAL_DOM_ORDER, ON_TOPIC, VISIBLE_ROW, cycle_tri, set_inclusion,
    visible_ids, TRI_ONLY_TRUE, TRI_ONLY_FALSEISH
)

INCLUSION_SETS = {"test_inclusion": {"p1", "p2", "p4", "p6"},
                  "test_inclusion2": {"p1", "p2", "p5"}}
INCLUSION_UNION = {"p1", "p2", "p4", "p5", "p6"}
INCLUSION_AND_WRONG = {"p1", "p2"} # what a buggy AND implementation yields

class TestTriStateFixtureSanity:
    def test_all_three_states_present_in_dom(self, page, target):
        states = page.eval_on_selector_all(
            "tr[data-paper-id]:not(.filter-hidden) [data-field='is_test_bool']",
            """cells => cells.map(c => {
                const e = c.querySelector('.emoji-content');
                const w = c.querySelector('.conflict-warning');
                if (w) return 'conflict';
                return e ? e.textContent.trim() : 'unknown';
            })"""
        )
        assert "✔️" in states and "❌" in states and ("❔" in states or "conflict" in states)

    def test_initial_state_is_unfiltered(self, page, target):
        assert sorted(visible_ids(page)) == sorted(ON_TOPIC)
        assert visible_ids(page) == INITIAL_DOM_ORDER

class TestTriStateCycling:
    def test_full_cycle_both_groups(self, page, target):
        for group in ("test_tri", "test_survey"):
            # all -> only_true
            cycle_tri(page, group)
            assert set(visible_ids(page)) == TRI_ONLY_TRUE[group]
            # only_true -> only_false (❌ AND ❔ stay visible — proves ❔ is
            # not treated as false-only)
            cycle_tri(page, group)
            assert set(visible_ids(page)) == TRI_ONLY_FALSEISH[group]
            # only_false -> all
            cycle_tri(page, group)
            assert set(visible_ids(page)) == set(ON_TOPIC)

    def test_only_true_hides_unknown_and_false(self, page, target):
        cycle_tri(page, "test_tri")
        ids = set(visible_ids(page))
        assert "p4" not in ids  # ❌ hidden
        assert "p6" not in ids  # ❔ hidden
        assert "p2" not in ids  # ⚠️ conflict hidden in only_true

    def test_only_false_keeps_unknown_and_conflict(self, page, target):
        cycle_tri(page, "test_tri")
        cycle_tri(page, "test_tri")
        ids = set(visible_ids(page))
        assert "p6" in ids  # ❔ remains
        assert "p4" in ids  # ❌ remains
        assert "p2" in ids  # ⚠️ conflict remains in only_false
        assert "p1" not in ids

    def test_state_persisted_in_url_and_survives_reload(self, page, target):
        cycle_tri(page, "test_tri")
        expect(page).to_have_url(re.compile(r"test_tri_filter=only_true"))
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(900)
        assert set(visible_ids(page)) == TRI_ONLY_TRUE["test_tri"]

    def test_two_tristate_groups_intersect(self, page, target):
        cycle_tri(page, "test_tri")      # {p1, p5}
        cycle_tri(page, "test_survey")   # {p2, p6}
        assert set(visible_ids(page)) == set()  # No intersection

class TestInclusionFilters:
    def test_no_inclusion_active_filters_nothing(self, page, target):
        assert set(visible_ids(page)) == set(ON_TOPIC)

    def test_single_inclusion_group_features(self, page, target):
        set_inclusion(page, "test_inclusion", True)
        assert set(visible_ids(page)) == INCLUSION_SETS["test_inclusion"]
        assert "p6" in visible_ids(page)
        assert "p5" not in visible_ids(page)

    def test_single_inclusion_group_methods(self, page, target):
        set_inclusion(page, "test_inclusion2", True)
        assert set(visible_ids(page)) == INCLUSION_SETS["test_inclusion2"]

    def test_two_inclusion_groups_are_or_not_and(self, page, target):
        set_inclusion(page, "test_inclusion", True)
        set_inclusion(page, "test_inclusion2", True)
        ids = set(visible_ids(page))
        assert ids == INCLUSION_UNION
        assert "p4" in ids
        assert "p5" in ids
        assert ids != INCLUSION_AND_WRONG

    def test_disabling_one_group_falls_back_to_the_other(self, page, target):
        set_inclusion(page, "test_inclusion", True)
        set_inclusion(page, "test_inclusion2", True)
        set_inclusion(page, "test_inclusion", False)
        assert set(visible_ids(page)) == INCLUSION_SETS["test_inclusion2"]

    def test_url_param_and_reload(self, page, target):
        set_inclusion(page, "test_inclusion", True)
        expect(page).to_have_url(re.compile(r"show_test_inclusion=1"))
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(900)
        assert set(visible_ids(page)) == INCLUSION_SETS["test_inclusion"]

    def test_filtered_rows_stay_in_dom_hidden(self, page, target):
        set_inclusion(page, "test_inclusion2", True)
        p4 = page.locator("tr[data-paper-id='p4']")
        assert p4.count() == 1
        assert p4.evaluate("el => el.classList.contains('filter-hidden')")

class TestFilterInteractions:
    def test_inclusion_and_tristate_intersect(self, page, target):
        set_inclusion(page, "test_inclusion", True)   # {p1,p2,p4,p6}
        cycle_tri(page, "test_tri")                   # {p1,p5}
        assert set(visible_ids(page)) == {"p1"}

    def test_hide_approved_combines_with_tristate(self, page, target):
        cycle_tri(page, "test_tri")  # {p1, p5}
        page.locator("#hide-approved-checkbox").check()
        page.wait_for_timeout(600)
        # p1 is verified, so hidden. p5 is unverified, so stays.
        assert set(visible_ids(page)) == {"p5"}

    def test_inclusion_plus_search_narrows(self, page, target):
        set_inclusion(page, "test_inclusion2", True)  # {p1,p2,p5}
        page.fill("#search-input", "transformer")
        page.wait_for_timeout(600)
        assert visible_ids(page) == ["p5"]

    def test_inclusion_excludes_search_match(self, page, target):
        set_inclusion(page, "test_inclusion2", True)
        page.fill("#search-input", "paywalled")  # only p4 matches search
        page.wait_for_timeout(600)
        assert visible_ids(page) == [], "p4 fails the active inclusion group"

    def test_visible_count_footer_tracks_filters(self, page, target):
        set_inclusion(page, "test_inclusion", True)
        page.wait_for_timeout(400)
        if target == "live":
            count = int(page.locator("#visible-papers-count").text_content())
        else:
            text = page.locator("#visible-count-cell").text_content()
            count = int(re.search(r"(\d+)", text).group(1))
        assert count == len(INCLUSION_SETS["test_inclusion"])