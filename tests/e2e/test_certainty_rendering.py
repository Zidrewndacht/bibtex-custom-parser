
class TestCertaintyRendering:
    def test_conflict_shows_warning(self, page):
        """p2 is_test_bool has certainty='conflict' → shows ⚠️."""
        cell = page.locator("tr[data-paper-id='p2'] [data-field='is_test_bool']")
        
        # The conflict warning is rendered
        assert cell.locator(".conflict-warning").count() == 1
        
        # The Jinja template completely OMITS the .emoji-content span when 
        # certainty is 'conflict'. It is not hidden via CSS; it doesn't exist.
        assert cell.locator(".emoji-content").count() == 0

    def test_partial_certainty_has_class(self, page):
        cell = page.locator("tr[data-paper-id='p5'] [data-field='is_test_bool']")
        assert cell.evaluate("el => el.classList.contains('certainty-80')")

    def test_solid_certainty_no_warning(self, page):
        cell = page.locator("tr[data-paper-id='p1'] [data-field='is_offtopic']")
        assert cell.locator(".conflict-warning").count() == 0
        emoji = cell.locator(".emoji-content")
        assert emoji.text_content() == "❌"

    def test_pdf_state_icons(self, page):
        p1_pdf = page.locator("tr[data-paper-id='p1'] td.pdf-status")
        assert "📕" in p1_pdf.text_content()
        p4_pdf = page.locator("tr[data-paper-id='p4'] td.pdf-status")
        assert "💰" in p4_pdf.text_content()
        p5_pdf = page.locator("tr[data-paper-id='p5'] td.pdf-status")   
        assert "📗" in p5_pdf.text_content()