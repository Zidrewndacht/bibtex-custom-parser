# tests/e2e/test_server_consistency.py
from playwright.sync_api import expect

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer << /Size 4 /Root 1 0 R >>
startxref
190
%%EOF
"""

class TestCellCyclingServerSide:
    def test_status_cycle_writes_db_log_and_resets_verification(self, page, db_reader):
        cell = page.locator("tr[data-paper-id='p1'] [data-field='is_test_bool'] .emoji-content")
        assert cell.text_content() == "✔️"
        cell.click()
        with page.expect_response(lambda r: "/update_paper" in r.url and r.status == 200):
            page.wait_for_timeout(1200)

        paper = db_reader("p1")
        assert paper["classification"]["is_test_bool"] is False
        assert paper["main_certainty"]["is_test_bool"] == "solid"
        assert paper["changed_by"] == "user"
        assert paper["verified"] is None
        assert paper["verified_by"] in (None, "")
        assert paper["llm_log"][-1]["type"] == "user"
        
        expect(page.locator("tr[data-paper-id='p1'] [data-field='is_test_bool'] .emoji-content")).to_have_text("❌")
        expect(page.locator("tr[data-paper-id='p1'] [data-field='verified'] .emoji-content")).to_have_text("❔")

    def test_dot_notation_cycle_writes_nested_json(self, page, db_reader):
        cell = page.locator("tr[data-paper-id='p1'] [data-field='features.feat_a'] .emoji-content")
        cell.click()
        with page.expect_response(lambda r: "/update_paper" in r.url):
            page.wait_for_timeout(1200)
        paper = db_reader("p1")
        assert paper["classification"]["features"]["feat_a"] is False
        assert paper["classification"]["features"]["feat_b"] is False

    def test_verified_by_cycle_writes_db(self, page, db_reader):
        # Use p2 which reliably has verified_by="computer" in the seed
        cell = page.locator("tr[data-paper-id='p2'] .editable-verify[data-field='verified_by']")
        assert "🖥️" in cell.inner_html()
        cell.click()
        with page.expect_response(lambda r: "/update_paper" in r.url):
            page.wait_for_timeout(1200)
        assert db_reader("p2")["verified_by"] == "user"

    def test_conflict_cell_click_resolves_to_true(self, page, db_reader):
        requests_made = []
        page.on("request", lambda r: requests_made.append(r.url) if "/update_paper" in r.url else None)
        cell = page.locator("tr[data-paper-id='p2'] [data-field='is_test_bool']")
        assert cell.locator(".conflict-warning").count() == 1
        cell.click()
        page.wait_for_timeout(1500)
        assert len(requests_made) == 1
        paper = db_reader("p2")
        assert paper["classification"]["is_test_bool"] is True
        assert paper["main_certainty"]["is_test_bool"] == "solid"

class TestFormSavesServerSide:
    def test_trace_only_save_keeps_existing_conflicts(self, page, db_reader):
        page.locator("tr[data-paper-id='p2'] .toggle-btn:not(.history-btn)").click()
        form = page.locator("form[data-paper-id='p2']")
        expect(form).to_be_visible(timeout=5000) # Wait for AJAX detail row to load
        form.locator("textarea[name='user_trace']").fill("comment only")
        with page.expect_response(lambda r: "/update_paper" in r.url and r.status == 200):
            form.locator(".save-btn").click()
        paper = db_reader("p2")
        assert paper["user_trace"] == "comment only"
        assert paper["main_certainty"]["is_test_bool"] == "conflict"

    def test_full_form_save_writes_all_fields(self, page, db_reader):
        # Use p4 which is safely within default year ranges
        page.locator("tr[data-paper-id='p4'] .toggle-btn:not(.history-btn)").click()
        form = page.locator("form[data-paper-id='p4']")
        expect(form).to_be_visible(timeout=5000) # Wait for AJAX detail row to load
        
        form.locator("input[name='page_count']").fill("33")
        form.locator("input[name='relevance']").fill("5.5")
        form.locator("textarea[name='user_trace']").fill("e2e server check")
        
        with page.expect_response(lambda r: "/update_paper" in r.url and r.status == 200):
            form.locator(".save-btn").click()
            
        paper = db_reader("p4")
        assert paper["page_count"] == 33
        assert abs(paper["classification"]["relevance"] - 5.5) < 1e-9
        assert paper["user_trace"] == "e2e server check"
        assert paper["changed_by"] == "user"

class TestPdfUploadServerSide:
    def test_upload_writes_file_and_db(self, page, db_reader, tmp_path):
        import os
        from shared import config as app_config
        
        # Ensure directories exist (also handled in conftest, but safe to double check)
        os.makedirs(app_config.PDF_STORAGE_DIR, exist_ok=True)
        
        pdf_file = tmp_path / "upload.pdf"
        pdf_file.write_bytes(MINIMAL_PDF)

        # p4 is safely within default year ranges and has pdf_state='paywalled'
        upload_link = page.locator("tr[data-paper-id='p4'] td .pdf-upload-link")
        expect(upload_link).to_be_visible(timeout=5000)
        
        with page.expect_file_chooser() as fc_info:
            upload_link.click()
        fc_info.value.set_files(str(pdf_file))
        
        # Wait for the upload response
        page.wait_for_timeout(1500)

        paper = db_reader("p4")
        assert paper["pdf_state"] == "PDF"
        assert paper["pdf_filename"] == "p4.pdf"
        stored = os.path.join(app_config.PDF_STORAGE_DIR, "p4.pdf")
        assert os.path.exists(stored)
        with open(stored, "rb") as f:
            assert f.read() == MINIMAL_PDF
        os.unlink(stored)