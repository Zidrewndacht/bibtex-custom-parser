"""URL serialization: filters, sort, and detail state survive reload."""


class TestURLState:
    def test_search_persisted_in_url(self, page):
        page.fill("#search-input", "solder")
        page.wait_for_timeout(600)

        url = page.url
        assert "search=solder" in url or "search_query=solder" in url

    def test_sort_persisted_in_url(self, page):
        page.locator("th[data-sort='year']").click()
        page.wait_for_timeout(600)

        url = page.url
        assert "sort_by=year" in url

    def test_detail_state_persisted(self, page):
        """Opening a detail row adds open_details to URL."""
        toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        toggle.click()
        page.wait_for_timeout(1000)

        url = page.url
        assert "open_details=" in url
        assert "p1" in url

    def test_reload_restores_detail_state(self, page):
        """After reload, previously opened detail rows re-expand."""
        toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        toggle.click()
        page.wait_for_timeout(1000)

        # Reload
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1500)

        # Detail row for p1 should be expanded again
        is_expanded = page.evaluate("""() => {
            const main = document.querySelector("tr[data-paper-id='p1']");
            if (!main) return false;
            const detail = main.nextElementSibling;
            return detail ? detail.classList.contains('expanded') : false;
        }""")
        assert is_expanded, "Detail state not restored after reload"