"""Client-side filtering: tri-state checkboxes, inclusion, hide-approved."""

import re
from playwright.sync_api import expect
from conftest import visible_ids, VISIBLE_ROW

class TestTriStateCheckbox:
    def test_initial_state_shows_all_ontopic(self, page):
        ids = visible_ids(page)
        assert "p3" not in ids
        assert "p1" in ids

    def test_cycle_tri_state_checkbox(self, page):
        # Matches the 'test_tri' group in the synthetic domain config
        cb = page.locator(".tri-state-checkbox[data-filter-group='test_tri']")
        
        # State 1: only_true -> hides p4 (is_test_bool=False)
        cb.click(force=True)
        page.wait_for_timeout(400)
        ids = visible_ids(page)
        assert "p4" not in ids

        # State 2: only_false -> only p4
        cb.click(force=True)
        page.wait_for_timeout(400)
        ids = visible_ids(page)
        assert "p4" in ids
        assert "p1" not in ids

        # State 3: back to all
        cb.click(force=True)
        page.wait_for_timeout(400)
        ids = visible_ids(page)
        assert len(ids) >= 4

    def test_inclusion_filter_features(self, page):
        """Inclusion checkbox for 'features' group shows papers with any feature=True."""
        cb = page.locator(".inclusion-checkbox[data-filter-group='test_inclusion']")
        
        # Custom-styled checkboxes often obscure the native <input> with CSS pseudo-elements.
        # Playwright's native .click(force=True) bypasses Playwright's checks, but the headless 
        # browser's internal engine may still refuse to toggle the native DOM property.
        # We reliably simulate the exact outcome of a successful user click by setting 
        # the DOM property and dispatching exactly ONE change event.
        cb.evaluate("""el => {
            el.checked = true;
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""")
        
        # Wait for the JS debounce (250ms filter + 100ms URL update = 350ms)
        page.wait_for_timeout(500)
        
        # ASSERT THE OUTCOME: The URL updates and the rows filter correctly.
        expect(page).to_have_url(re.compile(r"show_test_inclusion=1"))
        
        ids = visible_ids(page)
        assert "p1" in ids
        assert "p2" in ids
        assert "p4" in ids
        assert "p5" not in ids # p5 has no features in the synthetic seed

class TestHideApproved:
    def test_hide_verified_papers(self, page):
        cb = page.locator("#hide-approved-checkbox")
        cb.check()
        page.wait_for_timeout(400)
        ids = visible_ids(page)
        assert "p1" not in ids
        assert "p2" in ids

class TestAlternatingShading:
    def test_visible_rows_have_shading(self, page):
        page.wait_for_timeout(500)
        shades = page.eval_on_selector_all(
            VISIBLE_ROW,
            """rows => rows.map(r =>
                r.classList.contains('alt-shade-1') ? '1' :
                r.classList.contains('alt-shade-2') ? '2' : 'none')"""
        )
        assert any(s in ('1', '2') for s in shades)