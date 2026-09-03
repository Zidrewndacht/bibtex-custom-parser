# tests/e2e/test_search.py
"""Search box: filters visible + hidden data, F3 shortcut, clear button."""
from playwright.sync_api import expect

from conftest import VISIBLE_ROW, visible_ids


class TestSearch:
    def test_search_by_title(self, page):
        page.fill("#search-input", "Deep Learning")
        # Wait for DOM to update, then assert
        expect(page.locator(VISIBLE_ROW)).to_have_count(1)
        assert "p1" in visible_ids(page)

    def test_search_by_keyword_hidden_cell(self, page):
        """Keywords are in hidden-data-cell but should be searchable."""
        page.fill("#search-input", "transformer")
        expect(page.locator(VISIBLE_ROW)).to_have_count(1)
        assert "p5" in visible_ids(page)

    def test_search_by_author(self, page):
        page.fill("#search-input", "Alice")
        expect(page.locator(VISIBLE_ROW)).to_have_count(1)
        assert "p2" in visible_ids(page)

    def test_search_by_user_trace(self, page):
        page.fill("#search-input", "paywalled")
        expect(page.locator(VISIBLE_ROW)).to_have_count(1)
        assert "p4" in visible_ids(page)

    def test_clear_button_resets(self, page):
        page.fill("#search-input", "nonexistent_term_xyz")
        expect(page.locator(VISIBLE_ROW)).to_have_count(0)
        
        page.click("#clear-search-btn")
        # 4 on-topic papers in seed data (p3 is off-topic and hidden by default)
        expect(page.locator(VISIBLE_ROW)).to_have_count(4)

    def test_f3_focuses_search(self, page):
        page.keyboard.press("F3")
        expect(page.locator("#search-input")).to_be_focused()