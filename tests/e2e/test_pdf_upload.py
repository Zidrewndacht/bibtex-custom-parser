import os
import tempfile
import pytest
from playwright.sync_api import expect

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<< /Size 4 /Root 1 0 R >>
startxref
190
%%EOF
"""


@pytest.fixture
def temp_pdf_file():
    """Create a temporary PDF file for upload."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(MINIMAL_PDF)
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


def _upload_and_wait(page, upload_link, file_path, paper_id="p3"):
    """Click the upload link, choose a file, and wait for the server response."""
    with page.expect_file_chooser() as fc_info:
        upload_link.click()
    with page.expect_response(
        lambda resp: f"/upload_pdf/{paper_id}" in resp.url and resp.status == 200,
        timeout=10000,
    ):
        fc_info.value.set_files(file_path)


class TestPDFUpload:
    def test_upload_pdf_updates_state(self, page, temp_pdf_file):
        """Uploading a PDF changes pdf_state to 'PDF' and shows 📕."""
        # p3 has pdf_state='none' and no pdf_filename
        # First, unhide off-topic papers to see p3
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)

        p3_row = page.locator("tr[data-paper-id='p3']")
        pdf_cell = p3_row.locator("td").first
        # Should show ❔ initially
        expect(pdf_cell).to_have_text("❔")

        # Click the upload link and handle the file chooser
        upload_link = pdf_cell.locator(".pdf-upload-link")
        _upload_and_wait(page, upload_link, temp_pdf_file)


        # The cell should now show 📕 with a link
        expect(pdf_cell).to_contain_text("📕")
        pdf_link = pdf_cell.locator("a") # REMOVED .pdf-link
        assert pdf_link.count() >= 1

    def test_upload_pdf_persists_after_reload(self, page, temp_pdf_file):
        """Uploaded PDF state persists after page reload."""
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)

        p3_row = page.locator("tr[data-paper-id='p3']")
        upload_link = p3_row.locator("td .pdf-upload-link")
        _upload_and_wait(page, upload_link, temp_pdf_file)


        # Reload and verify state persisted
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)

        # p3 is off-topic, so unhide again
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)

        p3_row = page.locator("tr[data-paper-id='p3']")
        pdf_cell = p3_row.locator("td").first
        expect(pdf_cell).to_contain_text("📕")

    def test_upload_replaces_existing_none_state(self, page, temp_pdf_file):
        """Uploading to a paper with pdf_state='none' works correctly."""
        # p3 starts with pdf_state='none'
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)

        p3_pdf = page.locator("tr[data-paper-id='p3'] td").first
        initial_text = p3_pdf.text_content()
        assert "❔" in initial_text, "p3 should start with no PDF"

        upload_link = p3_pdf.locator(".pdf-upload-link")
        _upload_and_wait(page, upload_link, temp_pdf_file)

        # Verify it changed to PDF
        expect(p3_pdf).to_contain_text("📕")


class TestPDFUploadEdgeCases:
    def test_upload_invalid_file_rejected(self, page):
        """Uploading a non-PDF file should be rejected."""
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)

        # Create a non-PDF file
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a pdf")
            txt_path = f.name
        try:
            p3_row = page.locator("tr[data-paper-id='p3']")
            upload_link = p3_row.locator("td .pdf-upload-link")

            with page.expect_file_chooser() as fc_info:
                upload_link.click()
            fc_info.value.set_files(txt_path)
            page.wait_for_timeout(1000)

            pdf_cell = p3_row.locator("td").first
            expect(pdf_cell).to_have_text("❔")
        finally:
            os.unlink(txt_path)

    def test_pdf_cell_not_orphaned_after_upload(self, page, temp_pdf_file):
        """After upload, the cell must show a working link, not remain as ❔."""
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)

        p3_row = page.locator("tr[data-paper-id='p3']")
        upload_link = p3_row.locator("td .pdf-upload-link")
        _upload_and_wait(page, upload_link, temp_pdf_file)

        assert upload_link.count() == 0, \
            "Upload link should be replaced after successful upload"
        pdf_link = p3_row.locator("td a")
        assert pdf_link.count() >= 1, \
            "A working PDF link should exist after upload"