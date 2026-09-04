# tests/e2e/test_html_export.py
import re

import pytest
from playwright.sync_api import expect


class TestHTMLExportLoads:
    def test_export_page_loads(self, page, app_server):
        # Added hide_offtopic=0 to ensure all 5 seed papers are included
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        # Wait for the decompressed page to render the table (handles document.write delay)
        page.wait_for_selector("#papersTable", timeout=15000)
        
        table = page.locator("#papersTable")
        expect(table).to_be_visible()
        rows = page.locator("#papersTable tbody tr[data-paper-id]")
        assert rows.count() >= 5

    def test_export_contains_all_papers(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        
        ids = page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]",
            "rows => rows.map(r => r.getAttribute('data-paper-id'))"
        )
        for pid in ["p1", "p2", "p3", "p4", "p5"]:
            assert pid in ids

    def test_export_hides_offtopic_by_default(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=1")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)  # Let client-side filters apply
        
        visible = page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.getAttribute('data-paper-id'))"
        )
        assert "p3" not in visible


class TestHTMLExportFiltering:
    def test_search_filters_rows(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.fill("#search-input", "Transformer")
        page.wait_for_timeout(600)
        
        visible = page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.getAttribute('data-paper-id'))"
        )
        assert "p5" in visible
        assert len(visible) == 1

    def test_search_by_hidden_data(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.fill("#search-input", "transformer")
        page.wait_for_timeout(600)
        
        visible = page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.getAttribute('data-paper-id'))"
        )
        assert "p5" in visible

    def test_clear_search_shows_all(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.fill("#search-input", "nonexistent_xyz")
        page.wait_for_timeout(600)
        assert page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.length"
        ) == 0
        
        page.click("#clear-search-btn")
        page.wait_for_timeout(600)
        assert page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.length"
        ) >= 5

    def test_tri_state_checkbox_cycles(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        cb = page.locator(".tri-state-checkbox[data-filter-group='test_tri']")
            
        cb.click(force=True)
        page.wait_for_timeout(600)
        
        visible = page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.getAttribute('data-paper-id'))"
        )
        assert "p4" not in visible

    def test_inclusion_checkbox_filters(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        cb = page.locator(".inclusion-checkbox[data-filter-group='test_inclusion']")
        if cb.count() == 0: 
            pytest.skip("test_inclusion group not in export")
            
        cb.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); }")
        page.wait_for_timeout(600)
        
        visible = page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.getAttribute('data-paper-id'))"
        )
        assert "p1" in visible
        assert "p5" not in visible


class TestHTMLExportSorting:
    def test_sort_by_year(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.locator("th[data-sort='year']").click()
        page.wait_for_timeout(600)
        
        years = page.eval_on_selector_all(
            "#papersTable tbody tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.cells[2].textContent.trim())"
        )
        assert years == sorted(years, reverse=True)

    def test_sort_indicator_appears(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.locator("th[data-sort='year']").click()
        page.wait_for_timeout(600)
        
        assert page.locator("th[data-sort='year'] .sort-indicator").text_content() in ("▲", "▼")


class TestHTMLExportRowExpansion:
    def test_detail_row_expands(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)").click()
        page.wait_for_timeout(800)
        
        assert page.locator("tr[data-paper-id='p1'] + tr.detail-row").evaluate("el => el.classList.contains('expanded')")

    def test_history_row_expands(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.locator("tr[data-paper-id='p1'] .history-btn").click()
        page.wait_for_timeout(800)
        
        assert page.evaluate("""() => {
            const main = document.querySelector("tr[data-paper-id='p1']");
            const hist = main.nextElementSibling.nextElementSibling;
            return hist ? hist.classList.contains('expanded') : false;
        }""")

    def test_history_tab_switching(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        page.locator("tr[data-paper-id='p1'] .history-btn").click()
        page.wait_for_timeout(800)
        
        page.locator(".history-tab-btn[data-paper-id='p1']").nth(1).click()
        page.wait_for_timeout(300)
        
        assert page.locator(".history-tab-panel.active[data-paper-id='p1']").get_attribute("data-tab-panel") == "set1"

class TestHTMLExportFooter:
    def test_visible_count_updates_on_filter(self, page, app_server):
        page.goto(f"{app_server}/static_export?download=0&hide_offtopic=0")
        page.wait_for_selector("#papersTable", timeout=15000)
        page.wait_for_timeout(600)
        
        # In the HTML export, stats_core.js overwrites the innerHTML of 
        # #visible-count-cell with "<strong>N</strong> papers", destroying 
        # the original #visible-papers-count span. We must read the cell directly.
        before_text = page.locator("#visible-count-cell").text_content()
        before_match = re.search(r'(\d+)', before_text)
        before = int(before_match.group(1)) if before_match else 0
        
        page.fill("#search-input", "nonexistent_xyz")
        page.wait_for_timeout(600)
        
        after_text = page.locator("#visible-count-cell").text_content()
        after_match = re.search(r'(\d+)', after_text)
        after = int(after_match.group(1)) if after_match else 0
        
        assert after < before, f"Expected count to decrease, but went from {before} to {after}"