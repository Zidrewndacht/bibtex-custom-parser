// static/comms.js
/** For detail row retrieval and any functionality that reads/writes to the server (DB query/updates, etc). 
 * Some functions here are reimplemented as a client-side version in ghpages.js for the HTML export.
 * */
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
    // If user sees Computer (🖥️), next is User:
    // We assume the user wants to override/review it, not set it to computer.
    '🖥️': { next: '👤', value: 'user' } 
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
                    const estimatedScoreCell = mainRow.cells[estScoreCellIndex];
                    if (estimatedScoreCell) {
                        estimatedScoreCell.textContent = data.estimated_score !== null && data.estimated_score !== undefined ? data.estimated_score : '';
                    }
                }
                // Update user_override_count cell
                const userOverrideCountCell = mainRow.querySelector('[data-field="user_override_count"]');
                if (userOverrideCountCell && data.user_override_count !== undefined) {
                    userOverrideCountCell.textContent = data.user_override_count !== null && data.user_override_count !== undefined ? data.user_override_count : '0';
                }
                // Update verified cell
                const verifiedCell = mainRow.querySelector('.editable-status[data-field="verified"]');
                if (verifiedCell && data.verified !== undefined) {
                    verifiedCell.textContent = renderStatus(data.verified);
                }
                // Update verified_by cell
                const verifiedByCell = mainRow.querySelector('.editable-verify[data-field="verified_by"]');
                if (verifiedByCell && data.verified_by !== undefined) {
                    verifiedByCell.innerHTML = renderVerifiedBy(data.verified_by);
                }
                
                // Refresh history row if it's expanded
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
                        .catch(error => {
                            console.error(`Error refreshing history row for paper ${paperId}:`, error);
                        });
                    }
                }
            }
            updateCounts();
            //console.log(`Quick save successful for ${paperId} field ${field}`);
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

    // --- NEW: Collect Relevance Field ---
    const relevanceInput = form.querySelector('input[name="relevance"]');
    let relevanceValue = relevanceInput ? relevanceInput.value : '';
    // Convert empty string to NULL for the database consistency (optional but good practice)
    if (relevanceValue === '') {
        relevanceValue = null;
    } else {
        // If you want to ensure it's a number, uncomment the next lines:
        const parsedRelevance = parseFloat(relevanceValue); // or parseInt if it's an integer
        if (isNaN(parsedRelevance)) {
            relevanceValue = null; // Or handle error
        } else {
            relevanceValue = parsedRelevance;
        }
    }


    // --- Collect Additional Fields ---
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
        // --- NEW: Add Relevance Field to Payload ---
        relevance: relevanceValue,
        // --- Add Additional Fields to Payload ---
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
                
                const userOverrideCountCell = row.querySelector('[data-field="user_override_count"]');
                if (userOverrideCountCell) {
                    userOverrideCountCell.textContent = data.user_override_count !== null && data.user_override_count !== undefined ? data.user_override_count : '0';
                }
                // Update verified cell
                const verifiedCell = row.querySelector('.editable-status[data-field="verified"]');
                if (verifiedCell && data.verified !== undefined) {
                    verifiedCell.textContent = renderStatus(data.verified);
                }
                // Update verified_by cell
                const verifiedByCell = row.querySelector('.editable-verify[data-field="verified_by"]');
                if (verifiedByCell && data.verified_by !== undefined) {
                    verifiedByCell.innerHTML = renderVerifiedBy(data.verified_by);
                }
                // Update displayed page count if returned
                const pageCountCell = row.cells[pageCountCellIndex];
                if (pageCountCell) {
                     pageCountCell.textContent = data.page_count !== null && data.page_count !== undefined ? data.page_count : '';
                }
                // --- NEW: Update displayed relevance if returned ---
                // Find the relevance cell in the main row (adjust selector if needed)
                const relevanceCell = row.cells[relevanceCellIndex]; // Or better, add a class like .relevance-cell to the <td> and use '.relevance-cell'
                if (relevanceCell) {
                     relevanceCell.textContent = data.relevance !== null && data.relevance !== undefined ? data.relevance : '';
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
            saveButton.textContent = 'Saved!';
            setTimeout(() => {
                if (saveButton) {
                    saveButton.textContent = originalText;
                    saveButton.disabled = false;
                }
            }, 1500);
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
        saveButton.textContent = originalText;
        saveButton.disabled = false;
    });
}

/**
 * Toggles the visibility of the history row for a given paper.
 * @param {HTMLElement} element - The button element clicked to trigger the toggle.
 */
function toggleHistory(element) {
    const row = element.closest('tr'); // Main paper row
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
        row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
        row.nextElementSibling.nextElementSibling : null;
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
        row.nextElementSibling : null;
    
    const isHistoryExpanded = historyRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');
    
    if (isHistoryExpanded) {
        // Hiding the history row
        historyRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');  // Remove pressed state from THIS button
        openHistoryIds.delete(paperId);
        updateUrlWithDetailState();
    } else {
        // Showing the history row
        // First, check if the detail row is open for the same paper, close it if necessary
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
            const detailToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            detailToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
            detailToggleBtn.classList.remove('toggle-pressed');  // FIX: Remove from detailToggleBtn, not element

            openDetailIds.delete(paperId);
        }
        
        openHistoryIds.add(paperId);
        updateUrlWithDetailState();
        
        const contentPlaceholder = historyRow.querySelector('.detail-content-placeholder');
        fetch(`/get_history_row?paper_id=${encodeURIComponent(paperId)}`)
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' && data.html) {
                contentPlaceholder.innerHTML = data.html;
                requestAnimationFrame(() => {
                    historyRow.offsetHeight;
                    historyRow.classList.add('expanded');
                });
                element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                element.classList.add('toggle-pressed');
            } else {
                console.error(`Error loading history row for paper ${paperId}:`, data.message);
                contentPlaceholder.innerHTML = `<p>Error loading history: ${data.message || 'Unknown error'}</p>`;
            }
        })
        .catch(error => {
            console.error(`Error fetching history row for paper ${paperId}:`, error);
            contentPlaceholder.innerHTML = `<p>Error loading history: ${error.message}</p>`;
        });
    }
}

/**
 * Toggles the visibility of the detail row for a given paper.
 * @param {HTMLElement} element - The button element clicked to trigger the toggle.
 */
function toggleDetails(element) {
    const row = element.closest('tr'); // Main paper row
    // The detail row is the first sibling after the main row
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
                      row.nextElementSibling : null;

    // The history row is the second sibling after the main row (detail row is the first)
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
                       row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
                       row.nextElementSibling.nextElementSibling : null;

    const isExpanded = detailRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        // Hiding the detail row
        detailRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');  // Remove pressed state
        openDetailIds.delete(paperId); // Remove from set
        updateUrlWithDetailState(); // Update URL
    } else {
        // Showing the detail row
        // First, check if the history row is open for the same paper, close it if necessary
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
            // Find the corresponding history toggle button in the main row and update its text
            // The history button is in the main row itself
            const historyToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            historyToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
            historyToggleBtn.classList.remove('toggle-pressed');  // Remove pressed state
            openHistoryIds.delete(paperId); // Remove history ID from set
        }

        // Now proceed to show the detail row
        openDetailIds.add(paperId); // Add ID to set
        updateUrlWithDetailState(); // Update URL immediately

        const contentPlaceholder = detailRow.querySelector('.detail-content-placeholder');
        fetch(`/get_detail_row?paper_id=${encodeURIComponent(paperId)}`)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success' && data.html) {
                    contentPlaceholder.innerHTML = data.html;

                    // --- Event Delegation for Clickable Items (Authors/Keywords) ---
                    const detailContainer = contentPlaceholder; // Use the placeholder as the container
                    detailContainer.addEventListener('click', function(event) {
                        if (event.target.classList.contains('clickable-item')) {
                            event.preventDefault();
                            const searchTerm = event.target.getAttribute('data-search-term');
                            if (searchTerm) {
                                searchInput.value = searchTerm.trim();
                                applyLocalFilters();
                            }
                        }
                    });
                    // --- End Event Delegation Setup ---

                    requestAnimationFrame(() => {
                        detailRow.offsetHeight; // Trigger reflow
                        detailRow.classList.add('expanded');
                    });
                    element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                    element.classList.add('toggle-pressed');  // Add pressed state
                } else {
                    console.error(`Error loading detail row for paper ${paperId}:`, data.message);
                    if (contentPlaceholder) {
                        contentPlaceholder.innerHTML = `<p>Error loading details: ${data.message || 'Unknown error'}</p>`;
                    }
                }
            })
            .catch(error => {
                console.error(`Error fetching detail row for paper ${paperId}:`, error);
                if (contentPlaceholder) {
                    contentPlaceholder.innerHTML = `<p>Error loading details: ${error.message}</p>`;
                }
            });
    }
}


function applyServerSideFilters() {     //moved from filtering as it has server-based
    document.documentElement.classList.add('busyCursor');
    const urlParams = new URLSearchParams(window.location.search);

    const isOfftopicChecked = hideOfftopicCheckbox.checked;
    urlParams.set('hide_offtopic', isOfftopicChecked ? '1' : '0');

    const yearFromValue = document.getElementById('year-from').value.trim();
    if (yearFromValue !== '' && !isNaN(parseInt(yearFromValue))) {
        urlParams.set('year_from', yearFromValue);
    } else {
        urlParams.delete('year_from');
    }
    const yearToValue = document.getElementById('year-to').value.trim();
    if (yearToValue !== '' && !isNaN(parseInt(yearToValue))) {
        urlParams.set('year_to', yearToValue);
    } else {
        urlParams.delete('year_to');
    }

    const minPageCountValue = document.getElementById('min-page-count').value.trim();
    if (minPageCountValue !== '' && !isNaN(parseInt(minPageCountValue))) {
        urlParams.set('min_page_count', minPageCountValue);
    } else {
        urlParams.delete('min_page_count');
    }

    // const searchValue = document.getElementById('search-input').value.trim();
    // if (searchValue !== '') {
    //     urlParams.set('search_query', searchValue);
    // } else {
    //     urlParams.delete('search_query');
    // }
    // Construct the URL for the /load_table endpoint with current parameters
    const loadTableUrl = `/load_table?${urlParams.toString()}`;
    fetch(loadTableUrl)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.text();
        })
        .then(html => {
            const tbody = document.querySelector('#papersTable tbody');
            if (tbody) {
                tbody.innerHTML = html;
                const newUrl = `${window.location.pathname}?${urlParams.toString()}`;
                window.history.replaceState({ path: newUrl }, '', newUrl);
                applyLocalFilters(); //update local filters and let it remove busy state
            }
        })
        .catch(error => {
            console.error('Error fetching updated table:', error);
            document.documentElement.classList.remove('busyCursor');
        });
}





// Add a hidden file input element dynamically if it doesn't exist already
// (This avoids needing to add it to index.html)
if (!document.getElementById('pdf-file-input')) {
    const hiddenFileInput = document.createElement('input');
    hiddenFileInput.type = 'file';
    hiddenFileInput.id = 'pdf-file-input';
    hiddenFileInput.accept = '.pdf'; // Only accept PDF files
    hiddenFileInput.style.display = 'none';
    document.body.appendChild(hiddenFileInput);
}

// Reference the hidden input
const pdfFileInput = document.getElementById('pdf-file-input');

// Function to handle the actual upload
function uploadPDFForPaper(paperId) {
    const file = pdfFileInput.files[0];
    if (!file) {
        console.error("No file selected for upload.");
        alert("No file selected.");
        return;
    }

    if (!file.name.toLowerCase().endsWith('.pdf')) {
         alert("Please select a PDF file.");
         return;
    }

    const formData = new FormData();
    formData.append('pdf_file', file);

    // Show a simple loading indicator or disable interaction temporarily
    const uploadLink = document.querySelector(`.pdf-upload-link[data-paper-id="${paperId}"]`);
    if (uploadLink) {
        uploadLink.textContent = '⏳'; // Change icon to indicate processing
        uploadLink.style.pointerEvents = 'none'; // Disable clicks temporarily
    }

    fetch(`/upload_pdf/${encodeURIComponent(paperId)}`, { // Use encodeURIComponent for the string ID
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            //console.log("PDF uploaded successfully for paper ID:", paperId);
            // Update the table row with the new PDF info
            // Pass the filename and state received from the server
            updateTableRowWithPDFData(paperId, data.pdf_filename, data.pdf_state);
        } else {
            console.error("Upload failed:", data.message);
            alert(`Upload failed: ${data.message}`);
            // Re-enable the link if it failed
             if (uploadLink) {
                 uploadLink.textContent = '❔';
                 uploadLink.style.pointerEvents = 'auto';
             }
        }
    })
    .catch(error => {
        console.error("Error during upload:", error);
        alert("An error occurred during upload.");
        // Re-enable the link if it failed
        if (uploadLink) {
            uploadLink.textContent = '❔';
            uploadLink.style.pointerEvents = 'auto';
        }
    });
}

function updateTableRowWithPDFData(paperId, filename) {
    const row = document.querySelector(`tr[data-paper-id="${paperId}"]`);
    if (!row) {
        console.error(`Row for paper ID ${paperId} not found.`);
        return;
    }

    const pdfCell = row.cells[pdfCellIndex]; // PDF cell is the second cell (index 1)
    if (!pdfCell) {
        console.error(`PDF cell for paper ID ${paperId} not found.`);
        return;
    }

    // Remove .pdf extension from filename for the viewer URL
    const filenameWithoutExtension = filename.replace(/\.pdf$/i, '');
    
    // Create the new link element for the PDF.js viewer
    const pdfLink = document.createElement('a');
    pdfLink.href = `/static/pdfjs/web/viewer.html?file=/serve_pdf/${encodeURIComponent(filenameWithoutExtension)}`;
    pdfLink.target = '_blank';
    pdfLink.title = `Open PDF.js Annotator for: ${filename}`;
    pdfLink.textContent = '📕';

    // Replace the cell content with the new link
    pdfCell.innerHTML = ''; // Clear existing content (like '⏳')
    pdfCell.appendChild(pdfLink);
    pdfCell.title = "PDF Status"; // Set title back
}

// Event delegation for the PDF upload links
document.addEventListener('click', function(event) {
    if (event.target.classList.contains('pdf-upload-link')) {
        event.preventDefault(); // Prevent default link behavior
        // Get the paper ID as a string directly
        const paperId = event.target.getAttribute('data-paper-id');
        if (!paperId) { // Check if the ID string is empty or null
            console.error("Invalid or missing paper ID for PDF upload link.");
            return;
        }

        //console.log("Attempting upload for paper ID:", paperId); // Debug log

        // Reset the file input to allow selecting the same file again
        pdfFileInput.value = '';

        // Add event listener for when a file is selected
        pdfFileInput.onchange = function(e) {
            if (e.target.files.length > 0) {
                uploadPDFForPaper(paperId);
            }
        };

        // Trigger the hidden file input click
        pdfFileInput.click();
    }
});


/** Functionality below is exclusive to server-based implementation (e.g, not HTML exports) */
//globals.js
const batchModal = document.getElementById("batchModal");
const importModal = document.getElementById("importModal");
const exportModal = document.getElementById("exportModal");

//Checkboxes:  

const minPageCountInput = document.getElementById('min-page-count');
const yearFromInput = document.getElementById('year-from');
const yearToInput = document.getElementById('year-to');
const applyButton = document.getElementById('apply-serverside-filters');
// const totalPapersCountCell = document.getElementById('total-papers-count');


// --- Batch Action Button Event Listeners ---
const parçaToolsBtn = document.getElementById('parça-tools-btn');
const classifyAllBtn = document.getElementById('classify-all-btn');
const classifyMisclassifiedBtn = document.getElementById('classify-misclassified-btn');
const classifyImplBtn = document.getElementById('classify-impl-btn');
const classifyRemainingBtn = document.getElementById('classify-remaining-btn');
const classifyConsensusBtn = document.getElementById('classify-consensus-btn');
const verifyAllBtn = document.getElementById('verify-all-btn');
const verifyRemainingBtn = document.getElementById('verify-remaining-btn');
const batchStatusMessage = document.getElementById('batch-status-message');
const backupStatusMessage = document.getElementById('backup-status-message');

const importActionsBtn = document.getElementById('import-btn');
const exportActionsBtn = document.getElementById('export-btn');

const backupBtn = document.getElementById('backup-btn');
const restoreBtn = document.getElementById('restore-btn');

//show/hide modals:

function showBatchActions(){
    batchModal.offsetHeight;
    batchModal.classList.add('modal-active');
}
function closeBatchModal() { batchModal.classList.remove('modal-active'); }

function showImportActions(){
    importModal.offsetHeight;
    importModal.classList.add('modal-active');
}
function closeImportModal() { importModal.classList.remove('modal-active'); }

function showExportActions(){
    exportModal.offsetHeight;
    exportModal.classList.add('modal-active');   
    backupStatusMessage.innerHTML = 'Backups include the database, original and annotated PDFs, HTML export and a XLSX spreadsheet.<br><br>Restoring from a backup overwrites all existing data!';
    backupStatusMessage.style.color = '';
}
function closeExporthModal() { exportModal.classList.remove('modal-active'); }

function showApplyButton(){  applyButton.style.opacity = '1'; applyButton.style.pointerEvents = 'visible'; }


// Define all batch buttons so they can be managed together
const allBatchButtons = [
    classifyAllBtn,
    classifyRemainingBtn,
    classifyMisclassifiedBtn,
    classifyImplBtn,         
    classifyConsensusBtn, 
    verifyAllBtn,
    verifyRemainingBtn
];

function runBatchAction(mode, actionType) { 
    if (isBatchRunning) {
        alert(`A ${actionType} batch is already running.`);
        return;
    }
    let modeDescription = mode; 
    if (mode === 'all') {
        modeDescription = 'ALL';
    } else if (mode === 'remaining') {
        modeDescription = 'remaining'; 
    } else if (mode === 'no_features') {
        modeDescription = 'misclassification suspect';
    } else if (mode === 'on_topic_implementation') {
        modeDescription = 'on-topic primary/implementation'; 
    // Add description for 'consensus' mode
    } else if (mode === 'consensus') {
        modeDescription = 'misclassifications until consensus (reclassify + verify loop)';
    }
    if (!confirm(`Are you sure you want to ${actionType} ${modeDescription} papers? This might take a while.`)) {
        return;
    }
    isBatchRunning = true;
    // Disable ALL batch buttons when any batch action starts
    allBatchButtons.forEach(btn => {
        if (btn) btn.disabled = true; // Check if btn exists before disabling
    });
    if (batchStatusMessage) batchStatusMessage.textContent = `Starting ${actionType} (${mode})...`;
    const endpoint = actionType === 'classify' ? '/classify' : '/verify';
    fetch(endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ mode: mode }) // Send the mode (including 'consensus')
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
        batchStatusMessage.innerHTML = data.message;
        // Optionally, you could add logic here to re-enable buttons after a certain time
        // or based on some other signal if the process is known to have finished.
    })
    .catch(error => {
        console.error(`Error initiating batch ${actionType} (${mode}):`, error);
        alert(`Failed to start ${actionType} (${mode}): ${error.message}`);
        isBatchRunning = false;
        // Re-enable ALL batch buttons on error
        allBatchButtons.forEach(btn => {
            if (btn) btn.disabled = false; // Check if btn exists before enabling
        });
        if (batchStatusMessage) batchStatusMessage.innerHTML = '';
    });
}


document.addEventListener('DOMContentLoaded', function () {
    
    yearFromInput.addEventListener('change', showApplyButton);
    yearToInput.addEventListener('change', showApplyButton);
    minPageCountInput.addEventListener('change', showApplyButton);
    hideOfftopicCheckbox.addEventListener('change', applyServerSideFilters);

    applyButton.addEventListener('click', applyServerSideFilters);

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
    
    parçaToolsBtn.addEventListener('click', showBatchActions);
    classifyAllBtn.addEventListener('click', () => runBatchAction('all', 'classify'));
    classifyRemainingBtn.addEventListener('click', () => runBatchAction('remaining', 'classify'));
    classifyMisclassifiedBtn.addEventListener('click', () => runBatchAction('no_features', 'classify'));
    classifyImplBtn.addEventListener('click', () => runBatchAction('on_topic_implementation', 'classify'));
    classifyConsensusBtn.addEventListener('click', () => runBatchAction('consensus', 'classify'));
    verifyAllBtn.addEventListener('click', () => runBatchAction('all', 'verify'));
    verifyRemainingBtn.addEventListener('click', () => runBatchAction('remaining', 'verify'));

    importActionsBtn.addEventListener('click', showImportActions);
    exportActionsBtn.addEventListener('click', showExportActions);

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

                        // Replace the existing feature updates with:
                        updateRowCell(row, '.editable-status[data-field="features_tracks"]', data.features?.tracks);
                        updateRowCell(row, '.editable-status[data-field="features_holes"]', data.features?.holes);
                        updateRowCell(row, '.editable-status[data-field="features_bare_pcb_othe"]', data.features?.bare_pcb_other);

                        updateRowCell(row, '.editable-status[data-field="features_solder_insufficient"]', data.features?.solder_insufficient);
                        updateRowCell(row, '.editable-status[data-field="features_solder_excess"]', data.features?.solder_excess);
                        updateRowCell(row, '.editable-status[data-field="features_solder_void"]', data.features?.solder_void);
                        updateRowCell(row, '.editable-status[data-field="features_solder_crack"]', data.features?.solder_crack);
                        updateRowCell(row, '.editable-status[data-field="features_solder_other"]', data.features?.solder_other);

                        updateRowCell(row, '.editable-status[data-field="features_orientation"]', data.features?.orientation);
                        updateRowCell(row, '.editable-status[data-field="features_wrong_component"]', data.features?.wrong_component);
                        updateRowCell(row, '.editable-status[data-field="features_missing_component"]', data.features?.missing_component);
                        updateRowCell(row, '.editable-status[data-field="features_component_other"]', data.features?.component_other);

                        updateRowCell(row, '.editable-status[data-field="features_cosmetic"]', data.features?.cosmetic);
                        updateRowCell(row, '.editable-status[data-field="features_other"]', data.features?.other);

                        // Replace the existing technique updates with:
                        updateRowCell(row, '.editable-status[data-field="technique_classic_cv_based"]', data.technique?.classic_cv_based);
                        updateRowCell(row, '.editable-status[data-field="technique_ml_traditional"]', data.technique?.ml_traditional);
                        updateRowCell(row, '.editable-status[data-field="technique_dl_cnn_classifier"]', data.technique?.dl_cnn_classifier);
                        updateRowCell(row, '.editable-status[data-field="technique_dl_cnn_detector"]', data.technique?.dl_cnn_detector);
                        updateRowCell(row, '.editable-status[data-field="technique_dl_rcnn_detector"]', data.technique?.dl_rcnn_detector);
                        updateRowCell(row, '.editable-status[data-field="technique_dl_transformer"]', data.technique?.dl_transformer);
                        updateRowCell(row, '.editable-status[data-field="technique_dl_other"]', data.technique?.dl_other);
                        updateRowCell(row, '.editable-status[data-field="technique_hybrid"]', data.technique?.hybrid);
                        updateRowCell(row, '.editable-status[data-field="technique_available_dataset"]', data.technique?.available_dataset);

                        const userOverrideCountCell = row.querySelector('[data-field="user_override_count"]');
                        if (userOverrideCountCell) {
                            userOverrideCountCell.textContent = data.user_override_count !== null && data.user_override_count !== undefined ? data.user_override_count : '0';
                        }
                        // Update audit/other fields
                        const changedCell = row.querySelector('.changed-cell');
                        if (changedCell) changedCell.textContent = data.changed_formatted || '';

                        const changedByCell = row.querySelector('.changed-by-cell');
                        if (changedByCell) changedByCell.innerHTML = renderChangedBy(data.changed_by);

                        const verifiedCell = row.querySelector('.editable-status[data-field="verified"]');
                        if (verifiedCell) {
                            verifiedCell.textContent = renderStatus(data.verified);
                        }

                        const verifiedByCell = row.querySelector('.editable-verify[data-field="verified_by"]');
                        if (verifiedByCell) {
                             verifiedByCell.innerHTML = renderVerifiedBy(data.verified_by);
                        }
                        const estimatedScoreCell = row.cells[estScoreCellIndex];  //Updates score dynamically after verification.
                        if (estimatedScoreCell) estimatedScoreCell.textContent = data.estimated_score !== null && data.estimated_score !== undefined ? data.estimated_score : ''; // Example formatting

                        const pageCountCell = row.cells[pageCountCellIndex]; 
                        if (pageCountCell) pageCountCell.textContent = data.page_count !== null && data.page_count !== undefined ? data.page_count : '';

                        // Refresh history row if it's expanded
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
                                    .catch(error => {
                                        console.error(`Error refreshing history row for paper ${paperId}:`, error);
                                    });
                            }
                        }
                        updateCounts();
                        //console.log(`${actionType.charAt(0).toUpperCase() + actionType.slice(1)} successful for paper ${paperId}`);
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


    // --- BibTeX Import Logic ---
    const importBibtexBtn = document.getElementById('import-bibtex-btn');
    const bibtexFileInput = document.getElementById('bibtex-file-input');

    // Clicking the button triggers the hidden file input
    importBibtexBtn.addEventListener('click', () => {
        bibtexFileInput.click();
    });

    // Handle file selection and upload
    bibtexFileInput.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (file) {
            if (!file.name.toLowerCase().endsWith('.bib') && !file.name.toLowerCase().endsWith('.csv')) {
                alert('Please select a .bib or .csv file.');
                bibtexFileInput.value = ''; // Clear the input
                return;
            }

            if (!confirm(`Are you sure you want to import '${file.name}'?`)) {
                    bibtexFileInput.value = ''; // Clear the input
                    return;
            }

            const formData = new FormData();
            formData.append('file', file);

            // Disable button and show status
            importBibtexBtn.disabled = true;
            importBibtexBtn.textContent = 'Importing...';
            if (batchStatusMessage) {
                batchStatusMessage.textContent = `Uploading and importing '${file.name}'...`;
                batchStatusMessage.style.color = ''; // Reset color
            }

            fetch('/upload_bibtex', {
                method: 'POST',
                body: formData // Use FormData for file uploads
                // Don't set Content-Type header, let browser set it with boundary
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
                    //console.log(data.message);
                    if (batchStatusMessage) {
                        batchStatusMessage.textContent = data.message;
                        batchStatusMessage.style.color = 'green'; // Success color
                    }
                    // Optional: Reload the page or fetch new data to show imported papers
                    // window.location.reload(); // Simple reload
                    // Or, fetch updated papers list (requires more JS logic)
                        setTimeout(() => { window.location.reload(); }, 1500); // Reload after delay
                } else {
                    console.error("Import Error:", data.message);
                    if (batchStatusMessage) {
                        batchStatusMessage.textContent = `Import Error: ${data.message}`;
                        batchStatusMessage.style.color = 'red'; // Error color
                    }
                    alert(`Import failed: ${data.message}`);
                }
            })
            .catch(error => {
                console.error('Error uploading BibTeX file:', error);
                if (batchStatusMessage) {
                    batchStatusMessage.textContent = `Upload Error: ${error.message}`;
                    batchStatusMessage.style.color = 'red'; // Error color
                }
                alert(`An error occurred during upload: ${error.message}`);
            })
            .finally(() => {    // Re-enable button and reset file input
                importBibtexBtn.disabled = false;
                importBibtexBtn.innerHTML = 'Import <strong>BibTeX</strong>'; // Restore original HTML
                bibtexFileInput.value = '';
            });
        }
    });
    // --- End BibTeX Import Logic ---

    // --- Export HTML Button ---
    const exportHtmlBtn = document.getElementById('export-html-btn');
    exportHtmlBtn.addEventListener('click', function() {
        //console.log("Export HTML button clicked");
        // Gather current filter values from the UI elements
        const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
        const yearFromInput = document.getElementById('year-from');
        const yearToInput = document.getElementById('year-to');
        const minPageCountInput = document.getElementById('min-page-count');
        const searchInput = document.getElementById('search-input'); // Get search input

        let exportUrl = '/static_export?'; // Start building the URL

        // Add filters to the URL query parameters
        if (hideOfftopicCheckbox) {
            exportUrl += `hide_offtopic=${hideOfftopicCheckbox.checked ? '1' : '0'}&`;
        }
        if (yearFromInput && yearFromInput.value) {
            exportUrl += `year_from=${encodeURIComponent(yearFromInput.value)}&`;
        }
        if (yearToInput && yearToInput.value) {
            exportUrl += `year_to=${encodeURIComponent(yearToInput.value)}&`;
        }
        if (minPageCountInput && minPageCountInput.value) {
            exportUrl += `min_page_count=${encodeURIComponent(minPageCountInput.value)}&`;
        }
        if (searchInput && searchInput.value) { // Add search query
            exportUrl += `search_query=${encodeURIComponent(searchInput.value)}&`;
        }

        // Remove trailing '&' or '?' if present
        exportUrl = exportUrl.replace(/&$/, '');

        //console.log("Export URL:", exportUrl);

        // --- Trigger the download asynchronously ---
        // Create a temporary invisible anchor element
        const link = document.createElement('a');
        link.href = exportUrl;
        link.style.display = 'none';
        // The filename will be suggested by the server's Content-Disposition header
        // link.download = 'PCBPapers_export.html'; // Optional: Suggest a default name if server doesn't set it
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        // Note: The browser's download manager should handle the file save dialog.
    });

    document.getElementById('export-xlsx-btn').addEventListener('click', function() {
        // Reuse the logic from exportStaticBtn or create a specific one
        // This example reuses the core logic
        const currentUrlParams = new URLSearchParams(window.location.search);
        const exportUrlParams = new URLSearchParams();

        // Copy relevant filter parameters
        const relevantParams = ['hide_offtopic', 'year_from', 'year_to', 'min_page_count', 'search_query'];
        relevantParams.forEach(param => {
            const value = currentUrlParams.get(param);
            if (value !== null) {
                exportUrlParams.set(param, value);
            }
        });

        // Construct the URL for the Excel export endpoint
        const exportUrl = `/xlsx_export?${exportUrlParams.toString()}`;
        //console.log("Exporting Excel with URL:", exportUrl);

        // Trigger the download
        window.location.href = exportUrl;
    });


    const backupBtn = document.getElementById('backup-btn');


    backupBtn.addEventListener('click', function() {
        document.documentElement.classList.add('busyCursor');
        //console.log("Backup button clicked");

        backupStatusMessage.textContent = 'Creating backup...';
        backupStatusMessage.style.color = '';

        // Create backup URL with current filters
        const currentUrlParams = new URLSearchParams(window.location.search);
        const backupUrl = `/backup?${currentUrlParams.toString()}`;
        
        // Use fetch to get the backup file
        fetch(backupUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Backup failed: ${response.status} ${response.statusText}`);
                }
                // Extract filename from Content-Disposition header
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'backup.parça.zst';
                if (contentDisposition) {
                    const filenameMatch = contentDisposition.match(/filename="([^"]+)"/);
                    if (filenameMatch) {
                        filename = filenameMatch[1];
                    }
                }
                
                return response.blob().then(blob => ({ blob, filename }));
            })
            .then(({ blob, filename }) => {
                // Create a download link for the backup file
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
            
                backupStatusMessage.textContent = 'Backup created successfully!';
                backupStatusMessage.style.color = 'green';
                
                document.documentElement.classList.remove('busyCursor');
            })
            .catch(error => {
                console.error('Backup error:', error);
                backupStatusMessage.textContent = `Backup Error: ${error.message}`;
                backupStatusMessage.style.color = 'red';
                alert(`An error occurred during backup: ${error.message}`);
                document.documentElement.classList.remove('busyCursor');
            });
    });

    restoreBtn.addEventListener('click', function() {
        // Create file input for backup selection
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.zst';
        fileInput.style.display = 'none';
        
        fileInput.addEventListener('change', function(event) {
            const file = event.target.files[0];
            if (!file) return;

            // Validate file extension
            if (!file.name.endsWith('.parça.zst')) {
                alert('Invalid backup file. Expected .parça.zst file.');
                return;
            }

            // Create FormData and send restore request
            const formData = new FormData();
            formData.append('backup_file', file);

            // Show status message
                backupStatusMessage.textContent = `Restoring from ${file.name}...`;
                backupStatusMessage.style.color = '';

            fetch('/restore', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                document.documentElement.classList.add('busyCursor');
                if (data.status === 'success') {
                    //console.log(data.message);
                    backupStatusMessage.textContent = data.message;
                    backupStatusMessage.style.color = 'green';
                    
                    // Reload page after successful restore
                    setTimeout(() => { window.location.reload(); }, 2000);
                } else {
                    console.error("Restore Error:", data.message);
                    backupStatusMessage.textContent = `Restore Error: ${data.message}`;
                    backupStatusMessage.style.color = 'red';
                    alert(`Restore failed: ${data.message}`);
                }
                document.documentElement.classList.remove('busyCursor');
            })
            .catch(error => {
                document.documentElement.classList.add('busyCursor');
                console.error('Restore error:', error);
                backupStatusMessage.textContent = `Restore Error: ${error.message}`;
                backupStatusMessage.style.color = 'red';
                alert(`An error occurred during restore: ${error.message}`);
                document.documentElement.classList.remove('busyCursor');
            });
        });

        // Trigger file selection
        document.body.appendChild(fileInput);
        fileInput.click();
        document.body.removeChild(fileInput);
    });
    
    function handleEnterKey(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            applyServerSideFilters();
        }
    }
    if (yearFromInput) {
        yearFromInput.addEventListener('keydown', handleEnterKey);
    }
    if (yearToInput) {
        yearToInput.addEventListener('keydown', handleEnterKey);
    }
    if (minPageCountInput) {
        minPageCountInput.addEventListener('keydown', handleEnterKey);
    }

    document.addEventListener('keydown', function(event) {      // --- Ctrl+S Save Functionality ---
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