"""Search box: filters visible + hidden data, F3 shortcut, clear button."""
from conftest import visible_ids


class TestSearch:
    def test_search_by_title(self, page):
        page.fill("#search-input", "Deep Learning")
        page.wait_for_timeout(600)
        ids = visible_ids(page)
        assert "p1" in ids
        assert "p2" not in ids  # p2 title is "Test Systems Review"

    def test_search_by_keyword_hidden_cell(self, page):
        """Keywords are in hidden-data-cell but should be searchable."""
        page.fill("#search-input", "transformer")
        page.wait_for_timeout(600)  # was 400; debounce is 250ms + render
        ids = visible_ids(page)
        assert "p5" in ids

    def test_search_by_author(self, page):
        page.fill("#search-input", "Alice")
        page.wait_for_timeout(400)
        ids = visible_ids(page)
        assert "p2" in ids

    def test_search_by_user_trace(self, page):
        page.fill("#search-input", "paywalled")
        page.wait_for_timeout(400)
        ids = visible_ids(page)
        assert "p4" in ids

    def test_clear_button_resets(self, page):
        page.fill("#search-input", "nonexistent_term_xyz")
        page.wait_for_timeout(400)
        assert len(visible_ids(page)) == 0

        page.click("#clear-search-btn")
        page.wait_for_timeout(400)
        assert len(visible_ids(page)) >= 4

    def test_f3_focuses_search(self, page):
        page.keyboard.press("F3")
        page.wait_for_timeout(200)
        focused_id = page.evaluate("document.activeElement.id")
        assert focused_id == "search-input"