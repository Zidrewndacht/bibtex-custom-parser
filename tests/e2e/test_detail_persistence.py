"""Tests that detail row edits are saved to the server and persist across reloads."""
import pytest
from playwright.sync_api import expect

class TestFormSaveCorners:
    def test_numeric_fields_and_paywall_trigger(self, page):
        """Tests saving page_count, relevance, and the automated paywall state machine."""
        # Unhide offtopic papers to access p3 (which has no PDF and pdf_state='none')
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(500)
        
        details_btn = page.locator("tr[data-paper-id='p3'] .toggle-btn:not(.history-btn)")
        details_btn.click()
        
        form = page.locator("form[data-paper-id='p3']")
        expect(form).to_be_visible()
        
        # Fill numeric fields and trigger the paywall keyword
        form.locator("input[name='page_count']").fill("42")
        form.locator("input[name='relevance']").fill("8.5")
        form.locator("textarea[name='user_trace']").fill("This article is paywalled")
        
        with page.expect_response(
            lambda resp: "/update_paper" in resp.url and resp.status == 200
        ) as resp_info:
            form.locator(".save-btn").click()
            
        assert resp_info.value.json()["status"] == "success"
        page.wait_for_timeout(500)
        page.reload(wait_until="networkidle")
        
        p3_row = page.locator("tr[data-paper-id='p3']")
        
        # Assert numeric fields persisted and were cast correctly
        expect(p3_row.locator("td[data-field='page_count']")).to_have_text("42")
        expect(p3_row.locator("td[data-field='relevance']")).to_have_text("8.5")
        
        # Assert paywall state machine triggered (PDF column shows 💰)
        pdf_cell = p3_row.locator("td").first
        expect(pdf_cell).to_have_text("💰")


class TestCellClickCorners:
    def test_cycle_yaml_none_and_inclusion_fields(self, page):
        """Tests clicking YAML 'none' and 'inclusion' fields to verify dot-notation JSON injection."""
        # p1 has technique.method_x = True (✔️) and features.feat_a = True (✔️)
        
        # 1. Cycle a 'none' group field
        none_cell = page.locator("tr[data-paper-id='p1'] [data-field='technique.method_x'] .emoji-content")
        assert none_cell.text_content() == "✔️"
        none_cell.click()
        page.wait_for_timeout(800)
        assert none_cell.text_content() == "❌"
        
        # 2. Cycle an 'inclusion' group field
        incl_cell = page.locator("tr[data-paper-id='p1'] [data-field='features.feat_a'] .emoji-content")
        assert incl_cell.text_content() == "✔️"
        incl_cell.click()
        page.wait_for_timeout(800)
        assert incl_cell.text_content() == "❌"
        
        # Reload to prove server-side persistence of dot-notation paths
        page.reload(wait_until="networkidle")
        p1_row = page.locator("tr[data-paper-id='p1']")
        expect(p1_row.locator("[data-field='technique.method_x'] .emoji-content")).to_have_text("❌")
        expect(p1_row.locator("[data-field='features.feat_a'] .emoji-content")).to_have_text("❌")


class TestVerificationResetLogic:
    def test_inferred_edit_resets_verification(self, page):
        """Editing an inferred field via form should auto-reset verified status."""
        # p1 is fully verified (verified=1, verified_by='computer')
        details_btn = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        details_btn.click()
        
        form = page.locator("form[data-paper-id='p1']")
        expect(form).to_be_visible()
        
        # Change an editable_field (inferred data)
        form.locator("input[name='test_text']").fill("Changed inferred data")
        
        with page.expect_response(
            lambda resp: "/update_paper" in resp.url and resp.status == 200
        ):
            form.locator(".save-btn").click()
            
        page.wait_for_timeout(500)
        page.reload(wait_until="networkidle")
        
        p1_row = page.locator("tr[data-paper-id='p1']")
        
        # Verification should be wiped (❔) because user changed inferred data 
        # without explicitly setting a new verification state in the same payload.
        expect(p1_row.locator("[data-field='verified'] .emoji-content")).to_have_text("❔")
        expect(p1_row.locator("[data-field='verified_by']")).to_contain_text("❔")

class TestDetailPersistence:
    def test_save_and_persist_after_reload(self, page):
        """Edits made in the detail row are saved to the DB and persist across reloads."""

        # 1. Expand the detail row for p1
        details_btn = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        details_btn.click()

        # 2. Wait for the AJAX form to load into the placeholder
        form = page.locator("form[data-paper-id='p1']")
        expect(form).to_be_visible()

        # 3. Fill out fields
        unique_comment = "E2E Persistence Test Comment 99"
        unique_text = "E2E Test Text Value 42"

        user_trace_input = form.locator("textarea[name='user_trace']")
        test_text_input = form.locator("input[name='test_text']")

        user_trace_input.fill(unique_comment)
        test_text_input.fill(unique_text)

        # 4. Click Save AND wait for the actual server response
        # This is the definitive proof that the DB write completed.
        with page.expect_response(
            lambda resp: "/update_paper" in resp.url and resp.status == 200
        ) as response_info:
            form.locator(".save-btn").click()

        # Verify the server reported success
        response_body = response_info.value.json()
        assert response_body["status"] == "success"

        # 5. Brief wait for any post-save UI updates (button text, collapse, etc.)
        page.wait_for_timeout(500)

        # 6. Reload the page to prove server-side persistence
        # (bypasses any local JS state/cache)
        page.reload(wait_until="networkidle")

        # 7. Verify the hidden cells contain the saved data
        # The server renders hidden data cells for the client-side search engine.
        p1_row = page.locator("tr[data-paper-id='p1']")

        saved_comment = p1_row.locator("td.hidden-data-cell[data-field='user_trace']")
        expect(saved_comment).to_have_text(unique_comment)

        saved_text = p1_row.locator(
            "td.hidden-data-cell[data-field='test_text']"
        )
        expect(saved_text).to_have_text(unique_text)

        # 8. Verify derived UI state: Commented column shows ✔️
        commented_cell = p1_row.locator("td[data-field='user_comment_state']")
        expect(commented_cell).to_have_text("✔️")

    def test_ctrl_s_shortcut_saves(self, page):
        details_btn = page.locator("tr[data-paper-id='p4'] .toggle-btn:not(.history-btn)")
        details_btn.click()
        form = page.locator("form[data-paper-id='p4']")
        expect(form).to_be_visible()

        user_trace_input = form.locator("textarea[name='user_trace']")
        user_trace_input.fill("Ctrl+S save test")

        # Set up response listener BEFORE triggering the action
        with page.expect_response(
            lambda resp: "/update_paper" in resp.url and resp.status == 200
        ):
            user_trace_input.press("Control+s")

        page.reload(wait_until="networkidle")
        p4_row = page.locator("tr[data-paper-id='p4']")
        saved = p4_row.locator("td.hidden-data-cell[data-field='user_trace']")
        expect(saved).to_have_text("Ctrl+S save test")