# tests/e2e/test_deep_links.py
"""Tests for deep-link (focus_paper) functionality.

Deep links are used by the Agreement Report to open a specific paper
in a new tab, pre-filtered to show only that paper.

URL format: /?focus_paper=<id>&search_query=<id>&hide_offtopic=0&year_from=<year>&year_to=<year>
"""
from playwright.sync_api import expect


class TestDeepLinkNavigation:
    def test_focus_paper_shows_target_row(self, page, app_server):
        """Navigating to a focus_paper URL shows the target paper."""
        page.goto(f"{app_server}/?focus_paper=p1&search_query=p1&hide_offtopic=0&min_page_count=0")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)  # Allow focus_paper.js to run

        # The target row should be visible
        p1_row = page.locator("tr[data-paper-id='p1']")
        expect(p1_row).to_be_visible()

        # Other rows should be hidden (filtered by search_query=p1)
        visible_ids = page.eval_on_selector_all(
            "tr[data-paper-id]:not(.filter-hidden)",
            "rows => rows.map(r => r.getAttribute('data-paper-id'))"
        )
        assert "p1" in visible_ids
        # With search_query=p1, other papers should be filtered out
        assert len(visible_ids) <= 2, f"Expected mostly p1 visible, got {visible_ids}"

    def test_focus_paper_opens_history(self, page, app_server):
        """Deep link auto-expands the history row of the target paper."""
        page.goto(f"{app_server}/?focus_paper=p1&search_query=p1&hide_offtopic=0&min_page_count=0")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)  # Give time for history to expand

        # The history row should be expanded
        page.locator("tr[data-paper-id='p1']")
        history_expanded = page.evaluate("""() => {
            const main = document.querySelector("tr[data-paper-id='p1']");
            if (!main) return false;
            const detail = main.nextElementSibling;
            const hist = detail ? detail.nextElementSibling : null;
            return hist ? hist.classList.contains('expanded') : false;
        }""")
        assert history_expanded, "History row should be auto-expanded for focused paper"


    def test_focus_paper_year_filter_applied(self, page, app_server):
        """Deep link applies year filter to narrow the server query."""
        page.goto(f"{app_server}/?focus_paper=p1&hide_offtopic=0&min_page_count=0")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        
        # Check the actual input values instead of the URL, as client-side JS 
        # strips server-side params from the browser's address bar.
        year_from = page.locator("#year-from").input_value()
        year_to = page.locator("#year-to").input_value()
        assert year_from == "2024" and year_to == "2024", \
            f"Expected year filter to be 2024, got from={year_from}, to={year_to}"

    def test_focus_paper_nonexistent_shows_alert(self, page, app_server):
        """Focusing on a non-existent paper shows an alert.
        The dialog handler MUST be registered before navigation, otherwise
        Playwright auto-dismisses the alert and the test observes nothing."""
        dialog_appeared = []

        def handle_dialog(dialog):
            dialog_appeared.append(dialog.message)
            dialog.dismiss()

        page.on("dialog", handle_dialog)
        try:
            page.goto(f"{app_server}/?focus_paper=nonexistent999"
                      f"&hide_offtopic=0&min_page_count=0")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)  # focus_paper.js alerts ~150ms after load
            assert any("nonexistent999" in msg for msg in dialog_appeared), \
                "Expected a not-found alert for a nonexistent focus_paper id"
        finally:
            page.remove_listener("dialog", handle_dialog)
        # And the page must still be usable after the alert
        assert page.locator("#papersTable").count() == 1

    def test_focus_paper_offtopic_paper_visible(self, page, app_server):
        """Deep link with hide_offtopic=0 shows off-topic papers."""
        # p3 is off-topic
        page.goto(f"{app_server}/?focus_paper=p3&search_query=p3&hide_offtopic=0&min_page_count=0")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        p3_row = page.locator("tr[data-paper-id='p3']")
        expect(p3_row).to_be_visible()


class TestDeepLinkFromAgreementReport:
    """Test that the agreement report page links work."""

    def test_agreement_report_loads(self, page, app_server):
        """The agreement report page loads without error."""
        page.goto(f"{app_server}/agreement_report")
        page.wait_for_load_state("networkidle")

        # Should have the report title
        title = page.locator(".report-titlebar")
        assert title.count() >= 1

    def test_agreement_report_has_sections(self, page, app_server):
        """The agreement report contains expected sections."""
        page.goto(f"{app_server}/agreement_report")
        page.wait_for_load_state("networkidle")

        # Check for key sections
        sections = page.locator(".report-section")
        assert sections.count() >= 3, "Report should have multiple sections"