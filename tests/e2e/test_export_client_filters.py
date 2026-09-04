# tests/e2e/test_export_client_filters.py
"""
The static HTML export implements year / min-page-count / hide-offtopic as
PURE CLIENT-SIDE filters (ghpages.js), unlike the live app where they are
server-side (apply button -> /load_table -> rows re-fetched).

These behaviors are structurally different and must be tested separately.
"""
from conftest import goto_export, goto_live, visible_ids

class TestExportClientYearFilter:
    def test_year_from_narrows_client_side(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        assert len(visible_ids(page)) == 6
        page.fill("#year-from", "2023")
        page.wait_for_timeout(700)
        assert set(visible_ids(page)) == {"p1", "p2", "p5"}
        # Rows remain in DOM, hidden by class (client-side filtering)
        assert page.locator("tr[data-paper-id='p6']").count() == 1
        assert page.locator("tr[data-paper-id='p6']").evaluate("el => el.classList.contains('filter-hidden')")

    def test_year_range_both_bounds(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#year-from", "2021")
        page.fill("#year-to", "2023")
        page.wait_for_timeout(700)
        assert set(visible_ids(page)) == {"p2", "p3", "p4"}

    def test_clearing_year_inputs_restores_all(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#year-from", "2025")
        page.wait_for_timeout(600)
        assert visible_ids(page) == ["p5"]
        page.fill("#year-from", "")
        page.wait_for_timeout(600)
        assert len(visible_ids(page)) == 6

class TestExportClientMinPageCount:
    def test_min_page_count_filters(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#min-page-count", "9")
        page.wait_for_timeout(700)
        assert set(visible_ids(page)) == {"p1", "p4", "p6"}

    def test_min_page_count_zero_disables(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#min-page-count", "9")
        page.wait_for_timeout(500)
        page.fill("#min-page-count", "0")
        page.wait_for_timeout(600)
        assert len(visible_ids(page)) == 6

class TestExportClientHideOfftopic:
    def test_checkbox_hides_and_restores_offtopic(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        assert "p3" in visible_ids(page)
        page.locator("#hide-offtopic-checkbox").check(force=True)
        page.wait_for_timeout(600)
        assert "p3" not in visible_ids(page)
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)
        assert "p3" in visible_ids(page)

    def test_exported_with_hide_offtopic_1_starts_checked_and_disabled(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=1)
        cb = page.locator("#hide-offtopic-checkbox")
        assert cb.is_checked()
        assert cb.is_disabled()
        assert "p3" not in visible_ids(page)

class TestExportCombinedClientFilters:
    def test_year_minpages_and_offtopic_together(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#year-from", "2021")
        page.fill("#min-page-count", "9")
        page.locator("#hide-offtopic-checkbox").check(force=True)
        page.wait_for_timeout(800)
        assert set(visible_ids(page)) == {"p1", "p4"}

class TestServerVsExportStructuralDifference:
    """The same filter must REMOVE rows server-side in the live app but only
    HIDE them client-side in the export. This divergence has regressed."""

    def test_live_year_filter_removes_rows_from_dom(self, page, app_server):
        goto_live(page, app_server)
        page.fill("#year-from", "2023")
        # Force the button to be clickable via JS to avoid race conditions 
        # with the 'change' event listener that enables the button in comms_views.js
        page.evaluate("""() => {
            const btn = document.getElementById('apply-serverside-filters');
            if (btn) {
                btn.style.opacity = '1';
                btn.style.pointerEvents = 'auto';
            }
        }""")
        
        with page.expect_response(lambda r: "/load_table" in r.url and r.status == 200):
            page.click("#apply-serverside-filters")
        page.wait_for_timeout(600)
        assert page.locator("tr[data-paper-id='p6']").count() == 0
        assert page.locator("tr[data-paper-id='p4']").count() == 0
        assert set(visible_ids(page)) == {"p1", "p2", "p5"}

    def test_export_year_filter_keeps_rows_hidden(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=1)
        page.fill("#year-from", "2023")
        page.wait_for_timeout(700)
        # p4 is 2021, so it should be hidden but still in DOM
        assert page.locator("tr[data-paper-id='p4']").count() == 1
        assert page.locator("tr[data-paper-id='p4']").evaluate("el => el.classList.contains('filter-hidden')")

    def test_live_enter_key_triggers_server_filter(self, page, app_server):
        goto_live(page, app_server)
        page.fill("#year-to", "2024")
        with page.expect_response(lambda r: "/load_table" in r.url):
            page.locator("#year-to").press("Enter")
        page.wait_for_timeout(600)
        assert page.locator("tr[data-paper-id='p5']").count() == 0  # 2025

    def test_live_hide_offtopic_checkbox_is_server_side(self, page, app_server):
        goto_live(page, app_server)
        assert page.locator("tr[data-paper-id='p3']").count() == 0
        with page.expect_response(lambda r: "/load_table" in r.url):
            page.locator("#hide-offtopic-checkbox").uncheck()
        page.wait_for_timeout(600)
        assert page.locator("tr[data-paper-id='p3']").count() == 1