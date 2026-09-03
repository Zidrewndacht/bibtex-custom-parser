class TestStatusCycling:
    def test_cycle_tri_state_status(self, page):
        # p1 is_test_bool is True (✔️)
        cell = page.locator("tr[data-paper-id='p1'] [data-field='is_test_bool'] .emoji-content")
        initial = cell.text_content()
        assert initial == "✔️"

        cell.click()
        page.wait_for_timeout(800)
        assert cell.text_content() == "❌"

        cell.click()
        page.wait_for_timeout(800)
        assert cell.text_content() == "❔"

        cell.click()
        page.wait_for_timeout(800)
        assert cell.text_content() == "✔️"

    def test_conflict_cell_not_editable(self, page):
        cell = page.locator("tr[data-paper-id='p2'] [data-field='is_test_bool']")
        warning = cell.locator(".conflict-warning")
        assert warning.count() == 1

    def test_verified_by_cycle(self, page):
        cell = page.locator("tr[data-paper-id='p1'] .editable-verify[data-field='verified_by']")
        initial_html = cell.inner_html()
        assert "🖥️" in initial_html
        cell.click()
        page.wait_for_timeout(800)
        assert "👤" in cell.inner_html()