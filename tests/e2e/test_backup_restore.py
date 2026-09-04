# tests/e2e/test_backup_restore.py
"""Tests for backup and restore functionality.

Verifies that:
- Backup creates a valid downloadable file
- Restore from backup restores data correctly
- The round-trip (backup → modify → restore) works
"""
import os
import tempfile

from playwright.sync_api import expect


class TestBackup:
    def test_backup_creates_download(self, page):
        """Clicking backup triggers a file download."""
        # Open the export/backup modal
        page.click("#export-btn")
        page.wait_for_timeout(500)

        backup_btn = page.locator("#backup-btn")
        expect(backup_btn).to_be_visible()

        with page.expect_download(timeout=30000) as download_info:
            backup_btn.click()

        download = download_info.value
        assert download.suggested_filename.endswith(".parsa.tzst")

        # Save to temp file for potential restore testing
        save_path = os.path.join(tempfile.gettempdir(), "test_backup.parsa.tzst")
        download.save_as(save_path)
        assert os.path.exists(save_path)
        assert os.path.getsize(save_path) > 0


class TestRestore:
    def test_restore_from_backup(self, page, e2e_db_path):
        """Full round-trip: backup → modify → restore → verify."""
        # Step 1: Create a backup
        page.click("#export-btn")
        page.wait_for_timeout(500)

        with page.expect_download(timeout=30000) as download_info:
            page.click("#backup-btn")
        download = download_info.value

        backup_path = os.path.join(tempfile.gettempdir(), "roundtrip_backup.parsa.tzst")
        download.save_as(backup_path)

        # Step 2: Modify a paper (change user_trace)
        page.goto(page.url.split("?")[0])
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)

        details_btn = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        details_btn.click()
        form = page.locator("form[data-paper-id='p1']")
        expect(form).to_be_visible()

        form.locator("textarea[name='user_trace']").fill("MODIFIED_FOR_RESTORE_TEST")
        with page.expect_response(
            lambda resp: "/update_paper" in resp.url and resp.status == 200
        ):
            form.locator(".save-btn").click()
        page.wait_for_timeout(500)

        # Verify modification took effect
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)
        hidden_cell = page.locator("tr[data-paper-id='p1'] td.hidden-data-cell[data-field='user_trace']")
        expect(hidden_cell).to_have_text("MODIFIED_FOR_RESTORE_TEST")

        # Step 3: Restore from backup
        page.click("#export-btn")
        page.wait_for_timeout(500)

        restore_btn = page.locator("#restore-btn")
        expect(restore_btn).to_be_visible()

        
        with page.expect_file_chooser() as fc_info:
            restore_btn.click()
        file_chooser = fc_info.value
        file_chooser.set_files(backup_path)

        # Wait for the actual restore response before proceeding
        with page.expect_response(
            lambda resp: "/restore" in resp.url and resp.status == 200,
            timeout=10000
        ):
            file_chooser.set_files(backup_path) #wtf

        # Step 4: Verify data was restored (modification should be gone)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1000)

        hidden_cell = page.locator("tr[data-paper-id='p1'] td.hidden-data-cell[data-field='user_trace']")
        # After restore, the user_trace should be back to original (empty for p1)
        text = hidden_cell.text_content()
        assert "MODIFIED_FOR_RESTORE_TEST" not in text, "Restore should have reverted the modification"

        # Cleanup
        if os.path.exists(backup_path):
            os.unlink(backup_path)

    def test_restore_rejects_invalid_file(self, page):
        """Restoring a non-backup file should fail gracefully."""
        # Create a fake file
        with tempfile.NamedTemporaryFile(suffix=".parsa.tzst", delete=False) as f:
            f.write(b"this is not a valid backup")
            fake_path = f.name

        try:
            page.click("#export-btn")
            page.wait_for_timeout(500)

            restore_btn = page.locator("#restore-btn")
            with page.expect_file_chooser() as fc_info:
                restore_btn.click()
            fc_info.value.set_files(fake_path)

            page.wait_for_timeout(2000)

            # The page should still be functional (not crashed)
            # Check that we can still interact with the UI
            table = page.locator("#papersTable")
            assert table.count() >= 1
        finally:
            os.unlink(fake_path)

    # nonsensical implementation that doesn't actually evaluate the contents at all:
    # def test_backup_contains_database(self, page, e2e_db_path):
    #     """The backup file should contain the database (non-empty download)."""
    #     page.click("#export-btn")
    #     page.wait_for_timeout(500)

    #     with page.expect_download(timeout=30000) as download_info:
    #         page.click("#backup-btn")
    #     download = download_info.value

    #     save_path = os.path.join(tempfile.gettempdir(), "db_check_backup.parsa.tzst")
    #     download.save_as(save_path)

    #     # File should be non-trivially sized (contains DB + exports)
    #     size = os.path.getsize(save_path)
    #     assert size > 1000, f"Backup file too small ({size} bytes), likely missing content"

    #     os.unlink(save_path)