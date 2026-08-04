// static/js/comms_save.js
/**
 * Server writes: AJAX cell updates, full-form save, status/verify cycling,
 * per-row LLM classify/verify, and Ctrl+S shortcut.
 * Depends on: comms_rendering.js (render helpers, applyCertaintyAndUpdates)
 *             comms_views.js (toggleDetails — called after successful save)
 *             filtering.js (pageCountCellIndex, updateCounts, APP_CONFIG)
 */

function sendAjaxRequest(cell, dataToSend, currentText, row, paperId, field) {
    const saveButton = row.querySelector('.save-btn');
    const wasSaveButtonDisabled = saveButton ? saveButton.disabled : false;
    if (saveButton) saveButton.disabled = true;

    fetch('/update_paper', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataToSend)
    })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const mainRow = document.querySelector(`tr[data-paper-id="${paperId}"]`);
                if (mainRow) {
                    // 1. Clear ghosts, apply certainty, update emojis, format relevance
                    applyCertaintyAndUpdates(mainRow, data);

                    // 2. Update Audit / Universal Cells
                    if (data.changed_formatted !== undefined) mainRow.querySelector('.changed-cell').textContent = data.changed_formatted;
                    if (data.changed_by !== undefined) mainRow.querySelector('.changed-by-cell').innerHTML = renderChangedBy(data.changed_by);

                    const estScoreCell = mainRow.querySelector('[data-field="estimated_score"]');
                    if (estScoreCell) estScoreCell.textContent = data.estimated_score ?? '';

                    const userOverrideCell = mainRow.querySelector('[data-field="user_override_count"]');
                    if (userOverrideCell) userOverrideCell.textContent = data.user_override_count ?? '0';

                    const verifiedCell = mainRow.querySelector('[data-field="verified"]');
                    if (verifiedCell) verifiedCell.innerHTML = `<span class="emoji-content">${renderStatus(data.verified)}</span>`;

                    const verifiedByCell = mainRow.querySelector('[data-field="verified_by"]');
                    if (verifiedByCell) verifiedByCell.innerHTML = renderVerifiedBy(data.verified_by);

                    const pageCountCell = mainRow.cells[pageCountCellIndex];
                    if (pageCountCell && data.page_count !== undefined) pageCountCell.textContent = data.page_count ?? '';

                    // 3. Refresh history row if expanded
                    const historyRow = mainRow.nextElementSibling && mainRow.nextElementSibling.nextElementSibling &&
                        mainRow.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
                        mainRow.nextElementSibling.nextElementSibling : null;
                    if (historyRow && historyRow.classList.contains('expanded')) {
                        const historyContentPlaceholder = historyRow.querySelector('.detail-content-placeholder');
                        if (historyContentPlaceholder) {
                            fetch(`/get_history_row?paper_id=${encodeURIComponent(paperId)}`)
                                .then(response => response.json())
                                .then(historyData => {
                                    if (historyData.status === 'success' && historyData.html) {
                                        historyContentPlaceholder.innerHTML = historyData.html;
                                    }
                                })
                                .catch(error => console.error(`Error refreshing history row for paper ${paperId}:`, error));
                        }
                    }
                }
                if (typeof updateCounts === 'function') updateCounts();
            } else {
                cell.textContent = currentText;
            }
        })
        .catch(() => { cell.textContent = currentText; })
        .finally(() => { if (saveButton) saveButton.disabled = wasSaveButtonDisabled; });
}

function saveChanges(paperId) {
    const form = document.getElementById(`form-${paperId}`);
    if (!form) return;

    const data = { id: paperId };

    // Universal fields
    const pageCountInput = form.querySelector('input[name="page_count"]');
    data.page_count = pageCountInput ? (pageCountInput.value === '' ? null : parseInt(pageCountInput.value)) : null;

    const relevanceInput = form.querySelector('input[name="relevance"]');
    data.relevance = relevanceInput ? (relevanceInput.value === '' ? null : parseFloat(relevanceInput.value)) : null;

    const userTraceInput = form.querySelector('textarea[name="user_trace"]');
    data.user_trace = userTraceInput ? userTraceInput.value : '';

    // Domain specific fields (from YAML)
    for (const field of APP_CONFIG.editable_fields) {
        const input = form.querySelector(`[name="${field.json_path}"]`) || form.querySelector(`[name="${field.json_path.replace(/\./g, '_')}"]`);
        if (input) data[field.json_path] = input.value;
    }

    const saveButton = form.querySelector('.save-btn');
    const originalText = saveButton ? saveButton.textContent : 'Save Changes';
    if (saveButton) { saveButton.textContent = 'Saving...'; saveButton.disabled = true; }

    fetch('/update_paper', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const row = document.querySelector(`tr[data-paper-id="${paperId}"]`);
                if (row) {
                    // 1. Clear ghosts, apply certainty, update emojis, format relevance
                    applyCertaintyAndUpdates(row, data);

                    // 2. Update Audit / Universal Cells
                    if (data.changed_formatted !== undefined) row.querySelector('.changed-cell').textContent = data.changed_formatted;
                    if (data.changed_by !== undefined) row.querySelector('.changed-by-cell').innerHTML = renderChangedBy(data.changed_by);

                    const userOverrideCell = row.querySelector('[data-field="user_override_count"]');
                    if (userOverrideCell) userOverrideCell.textContent = data.user_override_count ?? '0';

                    const verifiedCell = row.querySelector('[data-field="verified"]');
                    if (verifiedCell) verifiedCell.innerHTML = `<span class="emoji-content">${renderStatus(data.verified)}</span>`;

                    const verifiedByCell = row.querySelector('[data-field="verified_by"]');
                    if (verifiedByCell) verifiedByCell.innerHTML = renderVerifiedBy(data.verified_by);

                    const pageCountCell = row.cells[pageCountCellIndex]; // Use the constant from filtering.js
                    if (pageCountCell && data.page_count !== undefined) pageCountCell.textContent = data.page_count ?? '';

                    // User Comment State
                    const userCommentStateCell = row.querySelector('[data-field="user_comment_state"]');
                    if (userCommentStateCell && data.user_trace !== undefined) {
                        const hasTrace = data.user_trace && String(data.user_trace).trim();
                        userCommentStateCell.innerHTML = `<span class="emoji-content">${hasTrace ? '✔️' : '❌'}</span>`;
                    }

                    // PDF State (if paywalled logic triggered via user comments)
                    if (data.pdf_state !== undefined) {
                        const pdfCell = row.cells[0];
                        if (pdfCell) {
                            pdfCell.innerHTML = '';
                            pdfCell.title = "PDF Status";
                            if (data.pdf_filename) {
                                const extRemoved = data.pdf_filename.replace(/\.pdf$/i, '');
                                const pdfLink = document.createElement('a');
                                pdfLink.href = `/static/pdfjs/web/viewer.html?file=/serve_pdf/${encodeURIComponent(extRemoved)}`;
                                pdfLink.target = '_blank';
                                pdfLink.className = 'pdf-link';
                                pdfLink.textContent = data.pdf_state === 'annotated' ? '📗' : '📕';
                                pdfLink.title = data.pdf_state === 'annotated'
                                    ? 'Open this annotated PDF in the Annotator'
                                    : 'Open this PDF in the Annotator';
                                pdfCell.appendChild(pdfLink);
                            } else {
                                const uploadLink = document.createElement('a');
                                uploadLink.href = '#';
                                uploadLink.className = 'pdf-upload-link';
                                uploadLink.setAttribute('data-paper-id', paperId);
                                const isPaywalled = data.pdf_state === 'paywalled';
                                uploadLink.title = isPaywalled
                                    ? 'Article is paywalled. Click to upload if a copy is available'
                                    : 'No PDF stored yet. Click to upload PDF for this article';
                                uploadLink.textContent = isPaywalled ? '💰' : '❔';
                                pdfCell.appendChild(uploadLink);
                            }
                        }
                    }
                }

                // Collapse details row after successful save
                const toggleBtn = row ? row.querySelector('.toggle-btn:not(.history-btn)') : null;
                if (toggleBtn && row && row.nextElementSibling && row.nextElementSibling.classList.contains('expanded')) {
                    toggleDetails(toggleBtn);
                }

                saveButton.textContent = 'Saved!';
                setTimeout(() => { if (saveButton) { saveButton.textContent = originalText; saveButton.disabled = false; } }, 1500);

                if (typeof updateCounts === 'function') updateCounts();
            } else {
                if (saveButton) { saveButton.textContent = originalText; saveButton.disabled = false; }
            }
        })
        .catch(() => { if (saveButton) { saveButton.textContent = originalText; saveButton.disabled = false; } });
}

// ============================================================================
// DOMContentLoaded — Save / Write wiring
// ============================================================================
document.addEventListener('DOMContentLoaded', function () {
    //server-side search removed for now as FTS is broken. Using full-client-side search instead (filtering.js, shared with HTML export):

    // Click Handler for Editable Status Cells
    document.addEventListener('click', function (event) {
        const cell = event.target.closest('.editable-status');
        if (cell) {
            const currentText = cell.querySelector('.emoji-content')?.textContent.trim()
                || cell.textContent.trim();
            const field = cell.getAttribute('data-field');
            const row = cell.closest('tr[data-paper-id]');
            const paperId = row ? row.getAttribute('data-paper-id') : null;

            if (!paperId) {
                console.error('Paper ID not found for clicked cell.');
                return;
            }

            // Find the next status in the general cycle
            const nextStatusInfo = STATUS_CYCLE[currentText];
            if (!nextStatusInfo) {
                console.error('Unknown status symbol:', currentText);
                const defaultNextStatusInfo = STATUS_CYCLE['❔'];

                // Update display
                const emojiSpan = cell.querySelector('.emoji-content');
                if (emojiSpan) {
                    emojiSpan.textContent = defaultNextStatusInfo.next;
                } else {
                    cell.textContent = defaultNextStatusInfo.next;
                }

                // Prepare data for AJAX using the default value
                const dataToSend = {
                    id: paperId,
                    [field]: defaultNextStatusInfo.value
                };
                sendAjaxRequest(cell, dataToSend, currentText, row, paperId, field);
                return;
            }

            const nextSymbol = nextStatusInfo.next;
            const nextValue = nextStatusInfo.value;

            // Update the UI immediately
            const emojiSpan = cell.querySelector('.emoji-content');
            if (emojiSpan) {
                emojiSpan.textContent = nextSymbol;
            } else {
                cell.textContent = nextSymbol;
            }

            cell.style.backgroundColor = '#f9e79f';
            setTimeout(() => {
                if ((emojiSpan?.textContent.trim() || cell.textContent.trim()) === nextSymbol) {
                    cell.style.backgroundColor = '';
                }
            }, 300);

            // Prepare data for AJAX
            const dataToSend = {
                id: paperId,
                [field]: nextValue
            };
            sendAjaxRequest(cell, dataToSend, currentText, row, paperId, field);
        }
    });

    // Click Handler for Editable Verify Cell (verified_by)
    document.addEventListener('click', function (event) {
        // Find the closest .editable-verify ancestor (handles clicks on <span> inside)
        const cell = event.target.closest('.editable-verify');
        if (!cell) return; // Not a verify cell or child thereof

        const currentSpan = cell.querySelector('span');
        if (!currentSpan) return;

        const currentSymbol = currentSpan.textContent.trim();
        const field = cell.getAttribute('data-field'); // Should be "verified_by"
        const row = cell.closest('tr[data-paper-id]');
        const paperId = row ? row.getAttribute('data-paper-id') : null;

        if (!paperId) {
            console.error('Paper ID not found for clicked cell.');
            return;
        }

        const nextStatusInfo = VERIFIED_BY_CYCLE[currentSymbol];
        if (!nextStatusInfo) {
            console.error('Unknown verified_by symbol:', currentSymbol);
            return;
        }

        const nextSymbol = nextStatusInfo.next;
        const nextValue = nextStatusInfo.value; // 'user', 'unknown'

        // 1. Immediately update the UI
        if (nextValue === 'user') {
            cell.innerHTML = '<span title="User">👤</span>';
        } else {
            cell.innerHTML = '<span title="Unverified">❔</span>';
        }

        cell.style.backgroundColor = '#f9e79f'; // Light yellow flash
        setTimeout(() => {
            if (cell.querySelector('span')?.textContent.trim() === nextSymbol) {
                cell.style.backgroundColor = '';
            }
        }, 300);

        // 2. Prepare data for AJAX
        const dataToSend = {
            id: paperId,
            [field]: nextValue === 'unknown' ? null : nextValue
        };

        // 3. Send AJAX request
        sendAjaxRequest(cell, dataToSend, currentSymbol, row, paperId, field);
    });

    // --- Per-Row Action Button Event Listeners ---
    document.addEventListener('click', function (event) {
        const classifyBtn = event.target.closest('.classify-btn');
        const verifyBtn = event.target.closest('.verify-btn');

        if (classifyBtn || verifyBtn) {
            const paperId = (classifyBtn || verifyBtn).getAttribute('data-paper-id');
            const actionType = classifyBtn ? 'classify' : 'verify';
            const endpoint = classifyBtn ? '/classify' : '/verify';

            if (!paperId) {
                console.error(`Paper ID not found for ${actionType} button.`);
                return;
            }

            (classifyBtn || verifyBtn).disabled = true;
            (classifyBtn || verifyBtn).textContent = 'Running...';

            fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'id', paper_id: paperId })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        const row = document.querySelector(`tr[data-paper-id="${paperId}"]`);
                        if (row) {
                            // 1. Clear ghosts, apply certainty, update emojis, format relevance
                            applyCertaintyAndUpdates(row, data);

                            // 2. Update Audit / Universal Cells
                            const userOverrideCountCell = row.querySelector('[data-field="user_override_count"]');
                            if (userOverrideCountCell) userOverrideCountCell.textContent = data.user_override_count ?? '0';

                            const changedCell = row.querySelector('.changed-cell');
                            if (changedCell) changedCell.textContent = data.changed_formatted || '';

                            const changedByCell = row.querySelector('.changed-by-cell');
                            if (changedByCell) changedByCell.innerHTML = renderChangedBy(data.changed_by);

                            const verifiedCell = row.querySelector('[data-field="verified"]');
                            if (verifiedCell) verifiedCell.innerHTML = `<span class="emoji-content">${renderStatus(data.verified)}</span>`;

                            const verifiedByCell = row.querySelector('[data-field="verified_by"]');
                            if (verifiedByCell) verifiedByCell.innerHTML = renderVerifiedBy(data.verified_by);

                            const estScoreCell = row.querySelector('[data-field="estimated_score"]');
                            if (estScoreCell) estScoreCell.textContent = data.estimated_score ?? '';

                            const pageCountCell = row.cells[pageCountCellIndex];
                            if (pageCountCell) pageCountCell.textContent = data.page_count ?? '';

                            // 3. Refresh history row if expanded...
                            const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
                                row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
                                row.nextElementSibling.nextElementSibling : null;
                            if (historyRow && historyRow.classList.contains('expanded')) {
                                const historyContentPlaceholder = historyRow.querySelector('.detail-content-placeholder');
                                if (historyContentPlaceholder) {
                                    fetch(`/get_history_row?paper_id=${encodeURIComponent(paperId)}`)
                                        .then(response => response.json())
                                        .then(historyData => {
                                            if (historyData.status === 'success' && historyData.html) {
                                                historyContentPlaceholder.innerHTML = historyData.html;
                                            }
                                        })
                                        .catch(error => console.error(`Error refreshing history row for paper ${paperId}:`, error));
                                }
                            }

                            updateCounts();
                        }
                    } else {
                        console.error(`${actionType} error for paper ${paperId}:`, data.message);
                        alert(`Failed to ${actionType} paper ${paperId}: ${data.message}`);
                    }
                })
                .catch(error => {
                    console.error(`Error during ${actionType} for paper ${paperId}:`, error);
                    alert(`An error occurred while ${actionType}ing paper ${paperId}: ${error.message}`);
                })
                .finally(() => {
                    (classifyBtn || verifyBtn).disabled = false;
                    if (actionType === 'classify') {
                        (classifyBtn || verifyBtn).innerHTML = 'Classify <strong>this paper</strong>';
                    } else if (actionType === 'verify') {
                        (classifyBtn || verifyBtn).innerHTML = 'Verify <strong>this paper</strong>';
                    }
                });
        }
    });

    // --- Ctrl+S Save Functionality ---
    document.addEventListener('keydown', function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key === 's') {
            event.preventDefault(); // Prevent the browser's default save action
            const focusedElement = document.activeElement;  // Get the currently focused element

            // Check if the focused element is within a form inside an expanded detail row
            // The form should have the data-paper-id attribute
            const formContainingFocus = focusedElement.closest('tr.detail-row.expanded form[data-paper-id]');
            if (formContainingFocus) {
                const paperId = formContainingFocus.getAttribute('data-paper-id');
                if (paperId) {
                    saveChanges(paperId);
                } else {
                    console.warn("Ctrl+S pressed, focused element is in an expanded detail row form, but data-paper-id is missing.");
                }
            } else {
                console.log("Ctrl+S pressed, but focus is not inside an expanded detail row form.");
            }
        }
    });
});