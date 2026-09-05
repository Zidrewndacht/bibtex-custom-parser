from conftest import goto_live, visible_ids, ON_TOPIC


class TestFooterCounts:
    """Footer counts verified against the crafted seed database.

    Seed facts (with default live params, hide_offtopic=1):
      - 5 on-topic papers loaded: p1, p2, p4, p5, p6
      - p3 is off-topic → excluded server-side
      - PDFs present: p1 (📕) and p5 (📗) → 2
      - No client-side filters active initially → visible == loaded == 5
    """

    def test_visible_count_matches_seed(self, page, app_server):
        goto_live(page, app_server)
        visible_count_text = page.locator("#visible-papers-count").text_content()
        assert int(visible_count_text) == len(ON_TOPIC)

    def test_loaded_count_matches_seed(self, page, app_server):
        goto_live(page, app_server)
        loaded_text = page.locator("#loaded-papers-count").text_content()
        # With hide_offtopic=1 the server only sends on-topic papers
        assert int(loaded_text) == len(ON_TOPIC)

    def test_pdf_count_matches_seed(self, page, app_server):
        goto_live(page, app_server)
        pdf_count_text = page.locator("#count-pdf_present").text_content()
        # p1 has pdf_state='PDF' (📕), p5 has pdf_state='annotated' (📗).
        # p2, p6 are 'none'; p4 is 'paywalled'. None of those count.
        assert int(pdf_count_text) == 2

    def test_counts_update_after_filter(self, page, app_server):
        goto_live(page, app_server)
        before = int(page.locator("#visible-papers-count").text_content())
        page.fill("#search-input", "Transformer")
        page.wait_for_timeout(500)
        after = int(page.locator("#visible-papers-count").text_content())
        assert after < before