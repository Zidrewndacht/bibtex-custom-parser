# tests/e2e/test_backup_restore.py

"""Tests for backup and restore functionality.
Verifies that:
- Backup creates a valid downloadable file
- Backup archive contains all expected components (DB, PDFs, exports, config)
- The database inside the backup is valid and contains the seed data
- Restore from backup restores data correctly
- The round-trip (backup → modify → restore) works
"""

import io
import os
import sqlite3
import tarfile
import tempfile

import zstandard as zstd
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
        os.unlink(save_path)

    def test_backup_contains_valid_database_with_seed_data(self, page, e2e_db_path):
        """The backup archive must contain a valid SQLite database
        with the papers table populated with the seed data."""
        page.click("#export-btn")
        page.wait_for_timeout(500)
        with page.expect_download(timeout=30000) as download_info:
            page.click("#backup-btn")
        download = download_info.value
        save_path = os.path.join(tempfile.gettempdir(), "db_verify_backup.parsa.tzst")
        download.save_as(save_path)

        try:
            # Decompress the zstd-compressed tar
            dctx = zstd.ZstdDecompressor()
            with open(save_path, 'rb') as compressed_file:
                with dctx.stream_reader(compressed_file) as decomp_stream:
                    tar_bytes = decomp_stream.read()

            tar_buffer = io.BytesIO(tar_bytes)
            with tarfile.open(fileobj=tar_buffer, mode='r') as tar:
                member_names = tar.getnames()

                # --- Verify expected members exist ---
                assert 'data/new.sqlite' in member_names, \
                    f"Database missing from backup. Members: {member_names}"
                assert 'export.html' in member_names, \
                    "HTML export missing from backup"
                assert 'export.xlsx' in member_names, \
                    "XLSX export missing from backup"
                assert 'domain_config.yaml' in member_names, \
                    "Domain config missing from backup"

                # --- Extract and validate the database ---
                db_member = tar.getmember('data/new.sqlite')
                db_file = tar.extractfile(db_member)
                assert db_file is not None, "Could not extract database from backup"
                db_bytes = db_file.read()
                assert len(db_bytes) > 0, "Extracted database is empty"

                # Write to a temp file so sqlite3 can open it
                temp_db_path = os.path.join(tempfile.gettempdir(), "backup_verify.sqlite")
                with open(temp_db_path, 'wb') as f:
                    f.write(db_bytes)

                try:
                    conn = sqlite3.connect(temp_db_path)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    # Verify the papers table exists
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='papers'"
                    )
                    assert cursor.fetchone() is not None, \
                        "papers table missing from backup database"

                    # Verify seed papers are present
                    cursor.execute("SELECT id, title, year FROM papers ORDER BY id")
                    rows = cursor.fetchall()
                    paper_ids = {row['id'] for row in rows}

                    # All six seed papers must be in the backup
                    expected_ids = {'p1', 'p2', 'p3', 'p4', 'p5', 'p6'}
                    assert expected_ids.issubset(paper_ids), \
                        f"Missing papers in backup DB. Found: {paper_ids}, expected: {expected_ids}"

                    # Spot-check specific seed values
                    p1 = next(r for r in rows if r['id'] == 'p1')
                    assert p1['title'] == 'Meridian Inspection Study'
                    assert p1['year'] == 2024

                    p6 = next(r for r in rows if r['id'] == 'p6')
                    assert p6['title'] == 'Beacon Solder Methods'
                    assert p6['year'] == 2019

                    # Verify classification JSON is intact
                    cursor.execute(
                        "SELECT classification FROM papers WHERE id = 'p1'"
                    )
                    cls_raw = cursor.fetchone()['classification']
                    import json
                    cls = json.loads(cls_raw)
                    assert cls['is_offtopic'] is False
                    assert cls['is_test_bool'] is True
                    assert cls['features']['feat_a'] is True

                    conn.close()
                finally:
                    if os.path.exists(temp_db_path):
                        os.unlink(temp_db_path)

        finally:
            if os.path.exists(save_path):
                os.unlink(save_path)

    def test_backup_contains_prompt_manifest(self, page):
        """The backup should contain prompt_manifest.json listing user prompt files."""
        page.click("#export-btn")
        page.wait_for_timeout(500)
        with page.expect_download(timeout=30000) as download_info:
            page.click("#backup-btn")
        download = download_info.value
        save_path = os.path.join(tempfile.gettempdir(), "manifest_backup.parsa.tzst")
        download.save_as(save_path)

        try:
            dctx = zstd.ZstdDecompressor()
            with open(save_path, 'rb') as compressed_file:
                with dctx.stream_reader(compressed_file) as decomp_stream:
                    tar_bytes = decomp_stream.read()

            tar_buffer = io.BytesIO(tar_bytes)
            with tarfile.open(fileobj=tar_buffer, mode='r') as tar:
                member_names = tar.getnames()
                assert 'prompt_manifest.json' in member_names, \
                    f"prompt_manifest.json missing. Members: {member_names}"

                # Parse the manifest and verify it references real files in the archive
                import json
                manifest_file = tar.extractfile(tar.getmember('prompt_manifest.json'))
                manifest = json.loads(manifest_file.read())
                assert isinstance(manifest, list), "Manifest should be a list"
                assert len(manifest) > 0, "Manifest should not be empty"

                for entry in manifest:
                    assert 'key' in entry, f"Manifest entry missing 'key': {entry}"
                    assert 'arcname' in entry, f"Manifest entry missing 'arcname': {entry}"
                    # The referenced file must actually exist in the archive
                    assert entry['arcname'] in member_names, \
                        f"Manifest references '{entry['arcname']}' but it's not in the archive"
        finally:
            if os.path.exists(save_path):
                os.unlink(save_path)

    def test_backup_html_export_is_nontrivial(self, page):
        """The HTML export inside the backup should be a substantial file,
        not an empty or error page."""
        page.click("#export-btn")
        page.wait_for_timeout(500)
        with page.expect_download(timeout=30000) as download_info:
            page.click("#backup-btn")
        download = download_info.value
        save_path = os.path.join(tempfile.gettempdir(), "html_check_backup.parsa.tzst")
        download.save_as(save_path)

        try:
            dctx = zstd.ZstdDecompressor()
            with open(save_path, 'rb') as compressed_file:
                with dctx.stream_reader(compressed_file) as decomp_stream:
                    tar_bytes = decomp_stream.read()

            tar_buffer = io.BytesIO(tar_bytes)
            with tarfile.open(fileobj=tar_buffer, mode='r') as tar:
                html_file = tar.extractfile(tar.getmember('export.html'))
                html_content = html_file.read().decode('utf-8')

                # The export is a loader page with compressed content,
                # so it should be substantial (contains base64 gzip data)
                assert len(html_content) > 10000, \
                    f"HTML export suspiciously small ({len(html_content)} bytes)"
                # It should contain the pako decompression script
                assert 'pako' in html_content.lower() or 'inflate' in html_content.lower(), \
                    "HTML export doesn't appear to be the compressed loader format"
        finally:
            if os.path.exists(save_path):
                os.unlink(save_path)


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

        # Set up the response listener BEFORE triggering the file selection,
        # so the single set_files call is captured cleanly.
        with page.expect_response(
            lambda resp: "/restore" in resp.url and resp.status == 200,
            timeout=10000
        ):
            file_chooser.set_files(backup_path)

        # Step 4: Verify data was restored (modification should be gone)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1000)
        hidden_cell = page.locator("tr[data-paper-id='p1'] td.hidden-data-cell[data-field='user_trace']")
        text = hidden_cell.text_content()
        assert "MODIFIED_FOR_RESTORE_TEST" not in text, \
            "Restore should have reverted the modification"

        # Cleanup
        if os.path.exists(backup_path):
            os.unlink(backup_path)

    def test_restore_rejects_invalid_file(self, page):
        """Restoring a non-backup file should fail gracefully."""
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