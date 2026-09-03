
"""Modal open/close: Stats, About, Batch, Export."""


class TestAboutModal:
    def test_open_with_button(self, page):
        page.click("#about-btn")
        page.wait_for_timeout(500)
        modal = page.locator("#aboutModal")
        assert modal.evaluate("el => el.classList.contains('modal-active')")

    def test_close_with_escape(self, page):
        page.click("#about-btn")
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        modal = page.locator("#aboutModal")
        assert not modal.evaluate("el => el.classList.contains('modal-active')")

    def test_open_with_f1(self, page):
        page.keyboard.press("F1")
        page.wait_for_timeout(500)
        modal = page.locator("#aboutModal")
        assert modal.evaluate("el => el.classList.contains('modal-active')")


class TestStatsModal:
    def test_open_with_f4(self, page):
        page.keyboard.press("F4")
        page.wait_for_timeout(1500)  # stats takes time to compute
        modal = page.locator("#statsModal")
        assert modal.evaluate("el => el.classList.contains('modal-active')")

    def test_stats_shows_counts(self, page):
        page.keyboard.press("F4")
        page.wait_for_timeout(1500)
        # The stats modal should have journal/conference lists populated
        journal_list = page.locator("#journalStatsList li")
        assert journal_list.count() > 0


class TestBatchModal:
    def test_open_batch_tools(self, page):
        page.click("#parça-tools-btn")
        page.wait_for_timeout(500)
        modal = page.locator("#batchModal")
        assert modal.evaluate("el => el.classList.contains('modal-active')")

    def test_close_batch_with_escape(self, page):
        page.click("#parça-tools-btn")
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        modal = page.locator("#batchModal")
        assert not modal.evaluate("el => el.classList.contains('modal-active')")