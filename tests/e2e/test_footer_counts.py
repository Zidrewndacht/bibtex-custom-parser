from conftest import visible_ids

class TestFooterCounts:
    def test_visible_count_matches_rows(self, page):
        page.wait_for_timeout(600)
        visible_count_text = page.locator("#visible-papers-count").text_content()
        actual_visible = len(visible_ids(page))
        assert int(visible_count_text) == actual_visible

    def test_loaded_count_matches_total_rows(self, page):
        loaded_text = page.locator("#loaded-papers-count").text_content()
        total_rows = page.locator("tr[data-paper-id]").count()
        assert int(loaded_text) == total_rows

    def test_pdf_count_correct(self, page):
        page.wait_for_timeout(600)
        # The footer cell for pdf_present uses ID, not data-count-field
        pdf_count_text = page.locator("#count-pdf_present").text_content()
        actual_pdf = page.evaluate("""() => {
            const rows = document.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
            let count = 0;
            for (const r of rows) {
                const cell = r.cells[0];
                const txt = cell ? cell.textContent.trim() : '';
                if (txt === '📕' || txt === '📗') count++;
            }
            return count;
        }""")
        assert int(pdf_count_text) == actual_pdf

    def test_counts_update_after_filter(self, page):
        before = int(page.locator("#visible-papers-count").text_content())
        page.fill("#search-input", "Transformer")
        page.wait_for_timeout(500)
        after = int(page.locator("#visible-papers-count").text_content())
        assert after < before