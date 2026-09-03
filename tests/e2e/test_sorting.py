"""Column sorting: click headers, verify order and indicators."""
from conftest import visible_ids


class TestBasicSorting:
    def test_sort_by_year_desc_then_asc(self, page):
        """Click Year header → DESC, click again → ASC."""
        header = page.locator("th[data-sort='year']")

        # First click: DESC (newest first)
        header.click()
        page.wait_for_timeout(600)
        visible_ids(page)
        years = page.eval_on_selector_all(
            "tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.cells[2].textContent.trim())"
        )
        assert years == sorted(years, reverse=True), f"DESC failed: {years}"

        # Second click: ASC
        header.click()
        page.wait_for_timeout(600)
        years = page.eval_on_selector_all(
            "tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.cells[2].textContent.trim())"
        )
        assert years == sorted(years), f"ASC failed: {years}"

    def test_sort_indicator_shown(self, page):
        """After sorting, the header shows ▲ or ▼."""
        header = page.locator("th[data-sort='year']")
        header.click()
        page.wait_for_timeout(600)
        indicator = header.locator(".sort-indicator")
        assert indicator.text_content() in ("▲", "▼")

    def test_sort_by_title_alphabetical(self, page):
        header = page.locator("th[data-sort='title']")
        
        # First click: DESC (newest/Z first)
        header.click()
        page.wait_for_timeout(300)
        
        # Second click: ASC (oldest/A first)
        header.click()
        page.wait_for_timeout(600)
        
        titles = page.eval_on_selector_all(
            "tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.cells[1].textContent.trim())"
        )
        assert titles == sorted(titles, key=str.lower)

    def test_detail_rows_follow_main_row(self, page):
        """When sorting, detail/history placeholder rows stay attached."""
        # Expand p1's detail first
        toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        toggle.click()
        page.wait_for_timeout(800)

        # Now sort by year
        page.locator("th[data-sort='year']").click()
        page.wait_for_timeout(600)

        # The detail row should still immediately follow p1's main row
        is_followed = page.evaluate("""() => {
            const main = document.querySelector("tr[data-paper-id='p1']");
            const next = main ? main.nextElementSibling : null;
            return next && next.classList.contains('detail-row');
        }""")
        assert is_followed, "Detail row detached from main row after sort"