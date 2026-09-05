# tests/e2e/test_pdf_annotator.py

"""
PDF.js annotator autosave E2E.
Flow under test (autosave.js):
  annotation change -> 5s debounce -> POST /upload_annotated_pdf/<id>
  -> server saves to ANNOTATED_PDF_STORAGE_DIR -> DB pdf_state='annotated'
Verified server-side (disk + SQLite), not just in the browser.
"""

import os
import pytest
from playwright.sync_api import expect

from conftest import goto_live

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
def pdf_env():
    from shared import config as app_config
    os.makedirs(app_config.PDF_STORAGE_DIR, exist_ok=True)
    os.makedirs(app_config.ANNOTATED_PDF_STORAGE_DIR, exist_ok=True)
    original = os.path.join(app_config.PDF_STORAGE_DIR, "p1.pdf")
    annotated = os.path.join(app_config.ANNOTATED_PDF_STORAGE_DIR, "p1.pdf")
    with open(original, "wb") as f:
        f.write(MINIMAL_PDF)
    yield app_config
    for path in (original, annotated):
        if os.path.exists(path):
            os.unlink(path)


def open_viewer(page, app_server):
    page.goto(f"{app_server}/static/pdfjs/web/viewer.html?file=%2Fserve_pdf%2Fp1")
    page.wait_for_selector("#viewer .page canvas", timeout=30000)


def draw_ink_stroke(page):
    ink_btn = page.locator("#editorInkButton")
    expect(ink_btn).to_be_enabled(timeout=20000)
    ink_btn.click()
    page.wait_for_timeout(500)
    box = page.locator("#viewerContainer").bounding_box()
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x - 90, y - 40)
    page.mouse.down()
    for i in range(1, 14):
        page.mouse.move(x - 90 + i * 12, y - 40 + (i % 3) * 9, steps=3)
    page.mouse.up()

    # CRITICAL FIX: Commit the annotation to the PDF's internal structure.
    # Without this, the editor remains "active" and PDF.js's saveDocument() 
    # will silently return the original, unmodified PDF bytes.
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

AUTOSAVE_PRED = (lambda r: "/upload_annotated_pdf/p1" in r.url and r.status == 200)


class TestServeOriginal:
    def test_serve_pdf_returns_original_file(self, page, app_server, pdf_env, db_reader):
        resp = page.request.get(f"{app_server}/serve_pdf/p1")
        assert resp.status == 200
        assert resp.body() == MINIMAL_PDF
        # Serving must not mutate state when it is already correct
        assert db_reader("p1")["pdf_state"] == "PDF"


class TestAutosave:
    def test_annotation_autosaves_and_updates_server(self, page, app_server, pdf_env, db_reader):
        open_viewer(page, app_server)
        draw_ink_stroke(page)

        # Debounce is 5s; capture the upload response while waiting it out.
        with page.expect_response(AUTOSAVE_PRED, timeout=30000) as info:
            page.wait_for_timeout(9000)
        assert info.value.json()["status"] == "success"

        # Autosave toast shown in the annotator UI
        assert page.locator("#autosave-notification").count() >= 1

        # --- Server-side truth ---
        paper = db_reader("p1")
        assert paper["pdf_state"] == "annotated", "DB state not updated"
        annotated_path = os.path.join(pdf_env.ANNOTATED_PDF_STORAGE_DIR, "p1.pdf")
        assert os.path.exists(annotated_path), "annotated file missing"
        
        # Original must be untouched
        with open(os.path.join(pdf_env.PDF_STORAGE_DIR, "p1.pdf"), "rb") as f:
            assert f.read() == MINIMAL_PDF

        # --- Main UI reflects the new state (📗) ---
        goto_live(page, app_server)
        pdf_cell = page.locator("tr[data-paper-id='p1'] td.pdf-status")
        assert "📗" in pdf_cell.text_content()

    def test_annotation_persists_across_viewer_reload(self, page, app_server, pdf_env, db_reader):
        """Full round-trip: annotate → autosave → close → reopen → annotation
        is part of the served document, not just editor state."""

        # --- Phase 1: Annotate and autosave ---
        open_viewer(page, app_server)
        draw_ink_stroke(page)

        with page.expect_response(AUTOSAVE_PRED, timeout=30000) as info:
            page.wait_for_timeout(9000)
        assert info.value.json()["status"] == "success"

        # --- Phase 2: Verify server-side persistence ---
        paper = db_reader("p1")
        assert paper["pdf_state"] == "annotated"

        annotated_path = os.path.join(pdf_env.ANNOTATED_PDF_STORAGE_DIR, "p1.pdf")
        assert os.path.exists(annotated_path), "Annotated file not written to disk"

        with open(annotated_path, "rb") as f:
            annotated_bytes = f.read()

        # The annotated file must differ from the original (it contains ink data)
        assert annotated_bytes != MINIMAL_PDF, \
            "Annotated file is identical to original — annotation was not embedded"
        assert len(annotated_bytes) > len(MINIMAL_PDF), \
            "Annotated file is smaller than original — corruption suspected"

        # --- Phase 3: Verify serve_pdf now returns the annotated file ---
        resp = page.request.get(f"{app_server}/serve_pdf/p1")
        assert resp.status == 200
        served_bytes = resp.body()
        assert served_bytes == annotated_bytes, \
            "serve_pdf is not returning the annotated file after autosave"
        assert served_bytes != MINIMAL_PDF, \
            "serve_pdf still returns the original — annotated file not picked up"

        # --- Phase 4: Reopen the viewer and verify the annotation is embedded ---
        open_viewer(page, app_server)

        # Wait for PDF.js to fully load the document
        page.wait_for_function(
            "() => window.PDFViewerApplication && window.PDFViewerApplication.pdfDocument",
            timeout=15000
        )

        # Query PDF.js for annotations on page 1.
        # Ink annotations saved by saveDocument() appear as 'Ink' subtype.
        annotations = page.evaluate("""async () => {
            const app = window.PDFViewerApplication;
            const pdfDoc = app.pdfDocument;
            if (!pdfDoc) return [];
            const page = await pdfDoc.getPage(1);
            const annots = await page.getAnnotations();
            return annots.map(a => ({
                subtype: a.subtype || a.annotationType || 'unknown',
                hasInkList: !!(a.inkLists && a.inkLists.length > 0)
            }));
        }""")

        # At least one annotation must exist (the ink stroke we drew)
        assert len(annotations) >= 1, \
            f"No annotations found in reloaded document. Got: {annotations}"

        # Verify it's an ink-type annotation with actual stroke data
        ink_annotations = [
            a for a in annotations
            if a.get("subtype") == "Ink" or a.get("hasInkList")
        ]
        assert len(ink_annotations) >= 1, \
            f"No ink annotation found among: {annotations}"

    def test_no_autosave_without_edits(self, page, app_server, pdf_env):
        requests_made = []
        page.on("request", lambda r: requests_made.append(r.url)
                if "/upload_annotated_pdf" in r.url else None)
        open_viewer(page, app_server)
        page.wait_for_timeout(8000)
        assert requests_made == []