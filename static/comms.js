// static/comms.js
/** For functionality that communicates with the server (DB updates, etc).
 * Any purely client-side functionality goes to filtering.js instead.
 */
// --- New Global Variables for Batch Status ---
let isBatchRunning = false; // Simple flag to prevent multiple simultaneous batches

// --- Status Cycling Logic ---
const STATUS_CYCLE = {
    '❔': { next: '✔️', value: 'true' },
    '✔️': { next: '❌', value: 'false' },
    '❌': { next: '❔', value: 'unknown' }
};
const VERIFIED_BY_CYCLE = {
    '👤': { next: '❔', value: 'unknown' }, 
    '❔': { next: '👤', value: 'user' },   
    // If user sees Computer (🖥️), next is Unknown (sending 'unknown' triggers server to set DB to NULL)
    // We assume the user wants to override/review it, not set it to computer.
    '🖥️': { next: '❔', value: 'unknown' } 
};
/**
 * Helper to update a cell's status symbol based on boolean/null value.
 * @param {Element} row - The main table row element.
 * @param {string} selector - The CSS selector for the cell within the row.
 * @param {*} value - The value (true, false, null, undefined) to determine the symbol.
 */
function updateRowCell(row, selector, value) {
    const cell = row.querySelector(selector);
    if (cell) {
        cell.textContent = renderStatus(value); // Use the renderStatus function
    }
}

/**
 * Renders a status value (true, false, null, etc.) as an emoji.
 * Replicates Python's render_status logic on the client.
 * @param {*} value - The value to render.
 * @returns {string} The emoji string.
 */
function renderStatus(value) {
    if (value === 1 || value === true) {
        return '✔️';
    } else if (value === 0 || value === false) {
        return '❌';
    } else {
        return '❔';
    }
}

/**
 * Renders a verified_by value (user, model_name, null) as an emoji with tooltip.
 * Replicates Python's render_verified_by logic on the client.
 * @param {*} value - The raw database value.
 * @returns {string} The HTML string for the emoji span.
 */
function renderVerifiedBy(value) {
     if (value === 'user') {
        return '<span title="User">👤</span>';
    } else if (value === null || value === undefined || value === '') {
        return '<span title="Unverified">❔</span>';
    } else {
        // Escape the model name for HTML attribute safety (basic escaping)
        let escapedModelName = String(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        return `<span title="${escapedModelName}">🖥️</span>`;
    }
}

// --- Helper function to render changed_by value as emoji (Client-Side) ---
function renderChangedBy(value) {
    // This replicates the logic from Python's render_changed_by function
    if (value === 'user') {
        return '<span title="User">👤</span>';
    } else if (value === null || value === undefined || value === '') {
        return '<span title="Unknown">❔</span>';
    } else {
        // Escape the model name for HTML attribute safety (basic escaping)
        // Using a simple replace for quotes. For more robust escaping, consider a library.
        let escapedModelName = String(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        return `<span title="${escapedModelName}">🖥️</span>`;
    }
}


document.addEventListener('DOMContentLoaded', function () {
    
    // Click Handler for Editable Status Cells
    document.addEventListener('click', function (event) {
        // Check if the clicked element is an editable status cell
        if (event.target.classList.contains('editable-status')) {
            const cell = event.target;
            const currentText = cell.textContent.trim();
            const field = cell.getAttribute('data-field');
            const row = cell.closest('tr[data-paper-id]'); // Find the parent row with the paper ID
            const paperId = row ? row.getAttribute('data-paper-id') : null;
            if (!paperId) {
                console.error('Paper ID not found for clicked cell.');
                return;
            }
            // Find the next status in the general cycle
            const nextStatusInfo = STATUS_CYCLE[currentText];
            if (!nextStatusInfo) {
                console.error('Unknown status symbol:', currentText);
                // default to unknown if symbol is unrecognized
                const defaultNextStatusInfo = STATUS_CYCLE['❔'];
                cell.textContent = defaultNextStatusInfo.next;
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

            // 1. Immediately update the UI (for general fields)
            cell.textContent = nextSymbol;
            cell.style.backgroundColor = '#f9e79f'; // Light yellow flash
            setTimeout(() => {
                 // Ensure we only reset the background if it hasn't changed again
                 if (cell.textContent === nextSymbol) {
                     cell.style.backgroundColor = ''; // Reset to default
                 }
            }, 300);

            // 2. Prepare data for the AJAX request (for general fields)
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

    // --- Batch Action Button Event Listeners ---
    const classifyAllBtn = document.getElementById('classify-all-btn');
    const classifyRemainingBtn = document.getElementById('classify-remaining-btn');
    const verifyAllBtn = document.getElementById('verify-all-btn');
    const verifyRemainingBtn = document.getElementById('verify-remaining-btn');
    const batchStatusMessage = document.getElementById('batch-status-message');

    function runBatchAction(mode, actionType) { // actionType: 'classify' or 'verify'
        if (isBatchRunning) {
            alert(`A ${actionType} batch is already running.`);
            return;
        }

        if (!confirm(`Are you sure you want to ${actionType} ${mode === 'all' ? 'ALL' : 'REMAINING'} papers? This might take a while.`)) {
            return;
        }

        isBatchRunning = true;
        const btnToDisable = mode === 'all' ? (actionType === 'classify' ? classifyAllBtn : verifyAllBtn) :
                                              (actionType === 'classify' ? classifyRemainingBtn : verifyRemainingBtn);
        const otherBtns = [classifyAllBtn, classifyRemainingBtn, verifyAllBtn, verifyRemainingBtn].filter(btn => btn !== btnToDisable);

        if (btnToDisable) btnToDisable.disabled = true;
        otherBtns.forEach(btn => btn.disabled = true);
        if (batchStatusMessage) batchStatusMessage.textContent = `Starting ${actionType} (${mode})...`;

        const endpoint = actionType === 'classify' ? '/classify' : '/verify';

        fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ mode: mode })
        })
        .then(response => {
             if (!response.ok) {
                 return response.json().then(errData => {
                     throw new Error(errData.message || `HTTP error! status: ${response.status}`);
                 }).catch(() => {
                     throw new Error(`HTTP error! status: ${response.status}`);
                 });
             }
             return response.json();
        })
        .then(data => {
            if (data.status === 'started') {
                if (batchStatusMessage) batchStatusMessage.textContent = data.message;
                // Batch started, it's running in the background.
                // To re-enable buttons after a short delay or assume user knows it's running
                //  setTimeout(() => {
                //      isBatchRunning = false; // Allow new batches after a short time
                //      if (btnToDisable) btnToDisable.disabled = false;
                //      otherBtns.forEach(btn => btn.disabled = false);
                //     //  if (batchStatusMessage) batchStatusMessage.textContent += " (Background task running)";
                //  }, 2000); // Assume it started successfully after 2s
            } else {
                 // This shouldn't happen for batch actions, but handle if it does
                 console.error(`Unexpected response for batch ${actionType}:`, data);
                 if (batchStatusMessage) batchStatusMessage.textContent = `Error initiating ${actionType} (${mode}).`;
                 isBatchRunning = false;
                 if (btnToDisable) btnToDisable.disabled = false;
                 otherBtns.forEach(btn => btn.disabled = false);
            }
        })
        .catch(error => {
            console.error(`Error initiating batch ${actionType} (${mode}):`, error);
            alert(`Failed to start ${actionType} (${mode}): ${error.message}`);
            isBatchRunning = false;
            if (btnToDisable) btnToDisable.disabled = false;
            otherBtns.forEach(btn => btn.disabled = false);
            if (batchStatusMessage) batchStatusMessage.textContent = '';
        });
    }

    classifyAllBtn.addEventListener('click', () => runBatchAction('all', 'classify'));
    classifyRemainingBtn.addEventListener('click', () => runBatchAction('remaining', 'classify'));
    verifyAllBtn.addEventListener('click', () => runBatchAction('all', 'verify'));
    verifyRemainingBtn.addEventListener('click', () => runBatchAction('remaining', 'verify'));

    // --- Per-Row Action Button Event Listeners ---
    document.addEventListener('click', function(event) {
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

            // Disable the button temporarily
            (classifyBtn || verifyBtn).disabled = true;
            (classifyBtn || verifyBtn).textContent = 'Running...';

            // Send AJAX request
            fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ mode: 'id', paper_id: paperId })
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(errData => {
                         throw new Error(errData.message || `HTTP error! status: ${response.status}`);
                    }).catch(() => {
                         throw new Error(`HTTP error! status: ${response.status}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success') {
                    // Update the row with the received data
                    const row = document.querySelector(`tr[data-paper-id="${paperId}"]`);
                    const detailRow = row ? row.nextElementSibling : null;
                    if (row) {
                        // Update main row cells
                        updateRowCell(row, '.editable-status[data-field="is_offtopic"]', data.is_offtopic);
                        updateRowCell(row, '.editable-status[data-field="is_survey"]', data.is_survey);
                        updateRowCell(row, '.editable-status[data-field="is_through_hole"]', data.is_through_hole);
                        updateRowCell(row, '.editable-status[data-field="is_smt"]', data.is_smt);
                        updateRowCell(row, '.editable-status[data-field="is_x_ray"]', data.is_x_ray);

                        updateRowCell(row, '.editable-status[data-field="features_solder"]', data.features?.solder);
                        updateRowCell(row, '.editable-status[data-field="features_polarity"]', data.features?.polarity);
                        updateRowCell(row, '.editable-status[data-field="features_wrong_component"]', data.features?.wrong_component);
                        updateRowCell(row, '.editable-status[data-field="features_missing_component"]', data.features?.missing_component);
                        updateRowCell(row, '.editable-status[data-field="features_tracks"]', data.features?.tracks);
                        updateRowCell(row, '.editable-status[data-field="features_holes"]', data.features?.holes);

                        updateRowCell(row, '.editable-status[data-field="technique_classic_computer_vision_based"]', data.technique?.classic_computer_vision_based);
                        updateRowCell(row, '.editable-status[data-field="technique_machine_learning_based"]', data.technique?.machine_learning_based);
                        updateRowCell(row, '.editable-status[data-field="technique_hybrid"]', data.technique?.hybrid);
                        updateRowCell(row, '.editable-status[data-field="technique_available_dataset"]', data.technique?.available_dataset);

                        // Update audit/other fields
                        const changedCell = row.querySelector('.changed-cell');
                        if (changedCell) changedCell.textContent = data.changed_formatted || '';

                        const changedByCell = row.querySelector('.changed-by-cell');
                        if (changedByCell) changedByCell.innerHTML = renderChangedBy(data.changed_by);

                        const verifiedCell = row.querySelector('.editable-status[data-field="verified"]');
                        if (verifiedCell) {
                            // Assuming render_status function exists or create one
                            verifiedCell.textContent = renderStatus(data.verified);
                        }

                        const verifiedByCell = row.querySelector('.editable-verify[data-field="verified_by"]');
                        if (verifiedByCell) {
                             // Assuming render_verified_by function exists or create one based on Python logic
                             verifiedByCell.innerHTML = renderVerifiedBy(data.verified_by);
                        }
                        const estimatedScoreCell = row.cells[28];   //why is there special treatment for that one?
                        if (estimatedScoreCell) estimatedScoreCell.textContent = data.estimated_score !== null && data.estimated_score !== undefined ? data.estimated_score : ''; // Example formatting

                        const pageCountCell = row.cells[4]; //moved afer hiding authors column
                        if (pageCountCell) pageCountCell.textContent = data.page_count !== null && data.page_count !== undefined ? data.page_count : '';

                        // Update detail row traces if expanded
                        if (detailRow && detailRow.classList.contains('expanded')) {
                            const evalTraceDiv = detailRow.querySelector('.detail-evaluator-trace .trace-content');
                            if (evalTraceDiv) evalTraceDiv.textContent = data.reasoning_trace || 'No trace available.';
                            const verifyTraceDiv = detailRow.querySelector('.detail-verifier-trace .trace-content');
                            if (verifyTraceDiv) verifyTraceDiv.textContent = data.verifier_trace || 'No trace available.';
                            // Update form fields if needed (e.g., model name, other defects might have changed)
                            const form = detailRow.querySelector(`form[data-paper-id="${paperId}"]`);
                            if(form){
                                const modelNameInput = form.querySelector('input[name="technique_model"]');
                                if(modelNameInput) modelNameInput.value = data.technique?.model || '';
                                const otherDefectsInput = form.querySelector('input[name="features_other"]');
                                if(otherDefectsInput) otherDefectsInput.value = data.features?.other || '';
                                const researchAreaInput = form.querySelector('input[name="research_area"]');
                                if(researchAreaInput) researchAreaInput.value = data.research_area || '';
                                // const pageCountInput = form.querySelector('input[name="page_count"]');
                                // if(pageCountInput) pageCountInput.value = data.page_count !== null && data.page_count !== undefined ? data.page_count : '';
                                // const userTraceTextarea = form.querySelector('textarea[name="user_trace"]');
                                // if(userTraceTextarea) userTraceTextarea.value = data.user_trace || ''; // Update textarea value
                            }
                        }
                        updateCounts();
                        console.log(`${actionType.charAt(0).toUpperCase() + actionType.slice(1)} successful for paper ${paperId}`);
                    }
                } else {
                    console.error(`${actionType.charAt(0).toUpperCase() + actionType.slice(1)} error for paper ${paperId}:`, data.message);
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
});

// --- Extracted AJAX logic for reuse ---
function sendAjaxRequest(cell, dataToSend, currentText, row, paperId, field) {
    // Use the same endpoint as the form save
    const saveButton = row.querySelector('.save-btn'); // Find save button in details if needed for disabling
    const wasSaveButtonDisabled = saveButton ? saveButton.disabled : false;
    if (saveButton) saveButton.disabled = true; // Optional: disable main save while quick save happens

    fetch('/update_paper', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(dataToSend)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(errData.message || `HTTP error! status: ${response.status}`);
            }).catch(() => {
                throw new Error(`HTTP error! status: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.status === 'success') {
            // 4. Update other relevant cells in the row based on the response
            const mainRow = document.querySelector(`tr[data-paper-id="${paperId}"]`);
            if (mainRow) {
                // Update audit fields (using formatted timestamp sent back)
                if (data.changed_formatted !== undefined) {
                    mainRow.querySelector('.changed-cell').textContent = data.changed_formatted;
                }
                if (data.changed_by !== undefined) {
                    mainRow.querySelector('.changed-by-cell').innerHTML = renderChangedBy(data.changed_by);
                }
                if (data.estimated_score !== undefined) {
                     const estimatedScoreCell = mainRow.cells[24]; 
                     if (estimatedScoreCell) {
                         estimatedScoreCell.textContent = data.estimated_score !== null && data.estimated_score !== undefined ? data.estimated_score : ''; // Example formatting
                     }
                }
            }
            updateCounts();
            console.log(`Quick save successful for ${paperId} field ${field}`);
        } else {
            console.error('Quick save error:', data.message);
            cell.textContent = currentText; // Revert text
        }
    })
    .catch((error) => {
        console.error('Quick save error:', error);
        cell.textContent = currentText; // Revert text
    })
    .finally(() => {
        if (saveButton) saveButton.disabled = wasSaveButtonDisabled;
    });
}

// --- Functions that might be called from inline HTML ---
function saveChanges(paperId) {
    const form = document.getElementById(`form-${paperId}`);
    if (!form) {
        console.error(`Form not found for paper ID: ${paperId}`);
        return;
    }

    // --- Collect Main Fields ---
    const researchAreaInput = form.querySelector('input[name="research_area"]');
    const researchAreaValue = researchAreaInput ? researchAreaInput.value : '';

    const pageCountInput = form.querySelector('input[name="page_count"]');
    let pageCountValue = pageCountInput ? pageCountInput.value : '';
    // Convert empty string or invalid input to NULL for the database
    if (pageCountValue === '') {
        pageCountValue = null;
    } else {
        const parsedValue = parseInt(pageCountValue, 10);
        if (isNaN(parsedValue)) {
            pageCountValue = null; // Or handle error as needed
        } else {
            pageCountValue = parsedValue;
        }
    }

    // --- NEW: Collect Additional Fields ---
    // Model Name -> technique_model
    const modelNameInput = form.querySelector('input[name="model_name"]');
    const modelNameValue = modelNameInput ? modelNameInput.value : '';

    // Other Defects -> features_other
    const otherDefectsInput = form.querySelector('input[name="features_other"]');
    const otherDefectsValue = otherDefectsInput ? otherDefectsInput.value : '';

    // User Comments -> user_trace (stored in main table column, not features/technique JSON)
    const userCommentsTextarea = form.querySelector('textarea[name="user_trace"]');
    const userCommentsValue = userCommentsTextarea ? userCommentsTextarea.value : '';


    // --- Prepare Data Payload ---
    const data = {
        id: paperId,
        research_area: researchAreaValue,
        page_count: pageCountValue,
        // --- NEW: Add Additional Fields to Payload ---
        // Prefix 'technique_' and 'features_' are handled by the backend
        technique_model: modelNameValue,
        features_other: otherDefectsValue,
        user_trace: userCommentsValue // This one is a direct column update
    };

    // --- UI Feedback and AJAX Call (Remains Largely the Same) ---
    const saveButton = form.querySelector('.save-btn');
    const originalText = saveButton ? saveButton.textContent : 'Save Changes';
    if (saveButton) {
        saveButton.textContent = 'Saving...';
        saveButton.disabled = true;
    }

    fetch('/update_paper', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data) // <-- Send the updated data object
    })
    .then(response => {
        if (!response.ok) {
             return response.json().then(errData => {
                 throw new Error(errData.message || `HTTP error! status: ${response.status}`);
             }).catch(() => {
                 throw new Error(`HTTP error! status: ${response.status}`);
             });
        }
        return response.json();
    })
    .then(data => {
        if (data.status === 'success') {
            const row = document.querySelector(`tr[data-paper-id="${paperId}"]`);
            if (row) {
                // Update displayed audit fields if returned
                if (data.changed_formatted !== undefined) {
                    row.querySelector('.changed-cell').textContent = data.changed_formatted;
                }
                if (data.changed_by !== undefined) {
                    row.querySelector('.changed-by-cell').innerHTML = renderChangedBy(data.changed_by);
                }
                // Update displayed page count if returned
                const pageCountCell = row.cells[4]; // Adjusted index if authors column is hidden
                if (pageCountCell) {
                     pageCountCell.textContent = data.page_count !== null && data.page_count !== undefined ? data.page_count : '';
                }
                // Note: The UI fields (model_name, features_other, user_trace) are NOT updated here
                // from the server response because update_paper_custom_fields doesn't return them.
                // They retain the user-entered value after saving.
            }
            // Collapse details row after successful save
            const toggleBtn = row ? row.querySelector('.toggle-btn') : null;
            if (toggleBtn && row && row.nextElementSibling && row.nextElementSibling.classList.contains('expanded')) {
                 toggleDetails(toggleBtn);
            }
            if (saveButton) {
                saveButton.textContent = 'Saved!';
                setTimeout(() => {
                    if (saveButton) {
                        saveButton.textContent = originalText;
                        saveButton.disabled = false;
                    }
                }, 1500);
            }
            updateCounts();
        } else {
            console.error('Save error:', data.message);
            if (saveButton) {
                saveButton.textContent = originalText;
                saveButton.disabled = false;
            }
        }
    })
    .catch((error) => {
        console.error('Error:', error);
        if (saveButton) {
            saveButton.textContent = originalText;
            saveButton.disabled = false;
        }
    });
}