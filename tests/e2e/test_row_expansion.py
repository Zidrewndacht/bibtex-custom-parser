"""Detail and History row expansion via AJAX."""


class TestDetailRow:
    def test_expand_and_collapse(self, page):
        toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        assert "Show" in toggle.text_content()

        toggle.click()
        page.wait_for_timeout(1000)

        # Detail row should now be expanded
        detail = page.locator("tr[data-paper-id='p1'] + tr.detail-row")
        assert detail.evaluate("el => el.classList.contains('expanded')")

        # Button text changes to Hide
        assert "Hide" in toggle.text_content()

        # Collapse
        toggle.click()
        page.wait_for_timeout(300)
        assert not detail.evaluate("el => el.classList.contains('expanded')")

    def test_detail_loads_form_fields(self, page):
        toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        toggle.click()
        page.wait_for_timeout(1000)

        # Should contain the detail form with editable fields
        form = page.locator("tr.detail-row.expanded form")
        assert form.count() == 1

    def test_history_opens_and_closes(self, page):
        toggle = page.locator("tr[data-paper-id='p2'] .history-btn")
        toggle.click()
        page.wait_for_timeout(1000)

        history = page.locator("tr[data-paper-id='p2']")
        # History row is two siblings after main (detail + history)
        history_row = page.evaluate("""() => {
            const main = document.querySelector("tr[data-paper-id='p2']");
            const detail = main.nextElementSibling;
            const hist = detail ? detail.nextElementSibling : null;
            return hist ? hist.classList.contains('expanded') : false;
        }""")
        assert history_row

    def test_detail_and_history_mutually_exclusive(self, page):
        """Opening history should close detail for the same paper."""
        # Open detail first
        detail_btn = page.locator("tr[data-paper-id='p2'] .toggle-btn:not(.history-btn)")
        detail_btn.click()
        page.wait_for_timeout(800)

        # Now open history
        hist_btn = page.locator("tr[data-paper-id='p2'] .history-btn")
        hist_btn.click()
        page.wait_for_timeout(800)

        detail_expanded = page.evaluate("""() => {
            const main = document.querySelector("tr[data-paper-id='p2']");
            const detail = main.nextElementSibling;
            return detail ? detail.classList.contains('expanded') : false;
        }""")
        assert not detail_expanded, "Detail should close when History opens"


class TestHistoryTabs:
    def test_tab_switching(self, page):
        toggle = page.locator("tr[data-paper-id='p2'] .history-btn")
        toggle.click()
        page.wait_for_timeout(1000)
        tabs = page.locator(".history-tab-btn[data-paper-id='p2']")
        assert tabs.count() == 4
        # Scroll into view and force-click to bypass row interception
        tabs.nth(1).scroll_into_view_if_needed()
        tabs.nth(1).click(force=True)
        page.wait_for_timeout(300)
        active_panel = page.locator(".history-tab-panel.active[data-paper-id='p2']")
        assert active_panel.get_attribute("data-tab-panel") == "set1"