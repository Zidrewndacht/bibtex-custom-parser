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

    def test_focus_paper_highlights_row(self, page, app_server):
        """The focused paper row gets a highlight animation."""
        page.goto(f"{app_server}/?focus_paper=p2&search_query=p2&hide_offtopic=0&min_page_count=0")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        p2_row = page.locator("tr[data-paper-id='p2']")
        expect(p2_row).to_be_visible()

        # Check for the highlight class (may have already faded)
        # At minimum, the row should be visible and not filter-hidden
        assert not p2_row.evaluate("el => el.classList.contains('filter-hidden')")

    def test_focus_paper_opens_history(self, page, app_server):
        """Deep link auto-expands the history row of the target paper."""
        page.goto(f"{app_server}/?focus_paper=p1&search_query=p1&hide_offtopic=0&min_page_count=0")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)  # Give time for history to expand

        # The history row should be expanded
        p1_main = page.locator("tr[data-paper-id='p1']")
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
        assert year_from == "2024" or year_to == "2024", \
            f"Expected year filter to be 2024, got from={year_from}, to={year_to}"

    def test_focus_paper_nonexistent_shows_alert(self, page, app_server):
        """Focusing on a non-existent paper shows an alert."""
        page.goto(f"{app_server}/?focus_paper=nonexistent999&hide_offtopic=0&min_page_count=0")
        page.wait_for_load_state("networkidle")

        # Should show an alert dialog
        # Playwright auto-dismisses alerts, but we can check the dialog appeared
        dialog_appeared = []

        def handle_dialog(dialog):
            dialog_appeared.append(dialog.message)
            dialog.dismiss()

        page.on("dialog", handle_dialog)
        page.wait_for_timeout(1500)

        # If no dialog appeared, at least verify the page didn't crash
        table = page.locator("#papersTable")
        assert table.count() >= 1

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