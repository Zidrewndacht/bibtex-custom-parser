// static/scripts.js
// --- Utility Functions ---
function toggleDetails(element) {
    const row = element.closest('tr'); // Get the main row
    if (!row) return; // Safety check
    const detailRow = row.nextElementSibling; // Assume detail row is the next sibling
    const isExpanded = detailRow && detailRow.classList.contains('expanded'); // Check if detailRow exists
    if (isExpanded) {
        if (detailRow) detailRow.classList.remove('expanded');
        element.textContent = 'Expand';
    } else {
        if (detailRow) detailRow.classList.add('expanded');
        element.textContent = 'Collapse';
    }
}
// Consistent status rendering function for JS
function renderStatus(value) {
    if (value === true || value === 1) return '✔️';
    if (value === false || value === 0) return '❌';
    return '❔'; // Covers null, undefined, 'unknown'
}
// --- Status Cycling Logic ---
// Define the cycle order: unknown -> true -> false -> unknown
const STATUS_CYCLE = {
    '❔': { next: '✔️', value: 'true' },
    '✔️': { next: '❌', value: 'false' },
    '❌': { next: '❔', value: 'unknown' }
};
// --- Click Event Handler for Status Cells ---
document.addEventListener('DOMContentLoaded', function () {
    const headers = document.querySelectorAll('th[data-sort]');
    let currentClientSort = { column: null, direction: 'ASC' }; // Track current client-side sort

    // --- Single Event Listener for Headers (Handles Client-Side Sorting) ---
    headers.forEach(header => {
        header.addEventListener('click', function () {
            const sortBy = this.getAttribute('data-sort');
            if (!sortBy) return;

            // --- Determine new sort direction ---
            let newDirection = 'ASC';
            if (currentClientSort.column === sortBy) {
                // If clicking the same column, toggle direction
                newDirection = currentClientSort.direction === 'ASC' ? 'DESC' : 'ASC';
            }
            // If clicking a new column, default to ASC (or you could keep the toggle logic)
            // The logic above already handles this as newDirection starts as 'ASC'

            // --- Get the table body and rows ---
            const tbody = document.querySelector('#papersTable tbody');
            if (!tbody) {
                console.error("Table body not found!");
                return;
            }
            // Select only main rows, not detail rows
            const rows = Array.from(tbody.querySelectorAll('tr[data-paper-id]'));

            // --- Define a function to get the sort value from a row ---
            const getSortValue = (row) => {
                let cellValue = null;
                // Handle direct columns (like title, year, type)
                if (['title', 'year', 'journal', 'authors', 'changed', 'changed_by', 'research_area', 'type'].includes(sortBy)) {
                    // Find cell by data-sort attribute in the row's cells
                    // This is more robust than index mapping
                    let cell = null;
                    const headerIndex = Array.from(header.parentNode.children).indexOf(header);
                    if (headerIndex !== -1) {
                        cell = row.cells[headerIndex];
                    }
                    cellValue = cell ? cell.textContent.trim() : '';
                    // Consider type conversion for numbers (year) if needed for correct sorting
                    if (sortBy === 'year') {
                        cellValue = parseInt(cellValue, 10) || 0; // Default to 0 if not a number
                    }
                }
                // Handle boolean/status columns (is_survey, is_offtopic, etc.)
                else if (['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray'].includes(sortBy)) {
                    // Find the cell with matching data-field
                    const cell = row.querySelector(`.editable-status[data-field="${sortBy}"]`);
                    cellValue = cell ? cell.textContent.trim() : '';
                    // Convert symbols to a sortable value (e.g., ✔️ -> 2, ❌ -> 1, ❔ -> 0)
                    if (cellValue === '✔️') cellValue = 2;
                    else if (cellValue === '❌') cellValue = 1;
                    else cellValue = 0; // ❔ or unknown
                }
                // Handle JSON-based feature/technique columns
                else if (sortBy.startsWith('features_') || sortBy.startsWith('technique_')) {
                    // Find the cell with matching data-field
                    const cell = row.querySelector(`.editable-status[data-field="${sortBy}"]`);
                    cellValue = cell ? cell.textContent.trim() : '';
                    // Convert symbols to a sortable value
                    if (cellValue === '✔️') cellValue = 2;
                    else if (cellValue === '❌') cellValue = 1;
                    else cellValue = 0; // ❔ or unknown
                }
                return cellValue;
            };

            // --- Perform the sort on the array of row elements ---
            rows.sort((a, b) => {
                const aValue = getSortValue(a);
                const bValue = getSortValue(b);
                // Basic comparison (string/number)
                let comparison = 0;
                if (aValue > bValue) {
                    comparison = 1;
                } else if (aValue < bValue) {
                    comparison = -1;
                }
                // If values are equal, add a secondary sort by paper ID for stability
                if (comparison === 0) {
                    const idA = a.getAttribute('data-paper-id') || '';
                    const idB = b.getAttribute('data-paper-id') || '';
                    if (idA > idB) comparison = 1;
                    else if (idA < idB) comparison = -1;
                }
                // Apply sort direction
                return newDirection === 'DESC' ? -comparison : comparison;
            });

            // --- Crucial Fix: Re-append rows WITH their detail rows ---
            // First, get all detail rows for quick lookup
            const allDetailRows = {};
            tbody.querySelectorAll('tr.detail-row').forEach(dRow => {
                // Find the preceding main row to get its ID
                let prevRow = dRow.previousElementSibling;
                while (prevRow && !prevRow.hasAttribute('data-paper-id')) {
                    prevRow = prevRow.previousElementSibling;
                }
                if (prevRow) {
                    const paperId = prevRow.getAttribute('data-paper-id');
                    if (paperId) {
                        allDetailRows[paperId] = dRow;
                    }
                }
            });

            // Now re-append them in the sorted order
            rows.forEach(mainRow => {
                const paperId = mainRow.getAttribute('data-paper-id');
                const detailRow = paperId ? allDetailRows[paperId] : null;

                // Append main row
                tbody.appendChild(mainRow);
                // Append its corresponding detail row immediately after
                if (detailRow) {
                    tbody.appendChild(detailRow);
                }
            });

            // --- Update the global sort state ---
            currentClientSort = { column: sortBy, direction: newDirection };

            // --- Update visual sort indicators ---
            // Clear all indicators first
            document.querySelectorAll('th .sort-indicator').forEach(ind => {
                if (ind) ind.textContent = '';
            });
            // Set indicator on the clicked header
            const indicator = this.querySelector('.sort-indicator'); // 'this' is the clicked header
            if (indicator) {
                indicator.textContent = newDirection === 'ASC' ? '↑' : '↓';
            }
        });
    });
    // --- End of consolidated header click listener ---

    // --- Update sort indicators based on initial state (if needed) ---
    // If you want to reflect the initial sort state from URL params on page load
    // using client-side sorting, you'd trigger the click handler for the relevant header here.
    // For now, we'll just clear existing indicators if any (from server-side render)
    // and rely on client-side state.
    // Clear server-side rendered indicators on load if you are switching to client-side
    // document.querySelectorAll('th .sort-indicator').forEach(ind => {
    //     if (ind) ind.textContent = '';
    // });
    // Or, read URL params and trigger client-side sort:
    // const urlParams = new URLSearchParams(window.location.search);
    // const initialSortBy = urlParams.get('sort_by');
    // const initialSortOrder = urlParams.get('sort_order');
    // if (initialSortBy) {
    //     const initialHeader = document.querySelector(`th[data-sort="${initialSortBy}"]`);
    //     if (initialHeader) {
    //         // Temporarily set the initial state
    //         currentClientSort = { column: initialSortBy, direction: initialSortOrder || 'ASC' };
    //         // Trigger the click to sort
    //         initialHeader.click();
    //     }
    // }


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
                alert('Error: Could not identify the paper.'); // Fallback alert
                return;
            }
            // Find the next status in the cycle
            const nextStatusInfo = STATUS_CYCLE[currentText];
            if (!nextStatusInfo) {
                console.error('Unknown status symbol:', currentText);
                // default to unknown if symbol is unrecognized
                // Note: Fix the typo from original code: assign to nextStatusInfo, not re-declare
                // nextStatusInfo = STATUS_CYCLE['❔']; // This line was problematic in original
                // Better: Just use the default directly
                const defaultNextStatusInfo = STATUS_CYCLE['❔'];
                cell.textContent = defaultNextStatusInfo.next;
                // Prepare data for AJAX using the default value
                const dataToSend = {
                    id: paperId,
                    [field]: defaultNextStatusInfo.value
                };
                // ... (rest of AJAX logic using defaultNextStatusInfo.value) ...
                // Return early after handling the error
                sendAjaxRequest(cell, dataToSend, currentText, row, paperId, field);
                return;
            }

            const nextSymbol = nextStatusInfo.next;
            const nextValue = nextStatusInfo.value;

            // 1. Immediately update the UI
            cell.textContent = nextSymbol;
            cell.style.backgroundColor = '#f9e79f'; // Light yellow flash
            setTimeout(() => {
                 // Ensure we only reset the background if it hasn't changed again
                 if (cell.textContent === nextSymbol) {
                     cell.style.backgroundColor = ''; // Reset to default
                 }
            }, 300);

            // 2. Prepare data for the AJAX request
            const dataToSend = {
                id: paperId,
                [field]: nextValue
            };

            // 3. Send the AJAX request (extracted for reuse in error case)
            sendAjaxRequest(cell, dataToSend, currentText, row, paperId, field);
        }
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
                        mainRow.querySelector('.changed-by-cell').textContent = data.changed_by;
                    }
                }
                console.log(`Quick save successful for ${paperId} field ${field}`);
            } else {
                console.error('Quick save error:', data.message);
                cell.textContent = currentText; // Revert text
                alert('Error saving quick change: ' + data.message);
            }
        })
        .catch((error) => {
            console.error('Quick save error:', error);
            cell.textContent = currentText; // Revert text
            alert('An error occurred during quick save: ' + error.message);
        })
        .finally(() => {
            if (saveButton) saveButton.disabled = wasSaveButtonDisabled;
        });
    }
    // --- End Click Handler for Editable Status Cells ---


});
// --- Functions that might be called from inline HTML ---
function saveChanges(paperId) {
    const form = document.getElementById(`form-${paperId}`);
    if (!form) {
        console.error(`Form not found for paper ID: ${paperId}`);
        return;
    }
    const researchAreaInput = form.querySelector('input[name="research_area"]');
    const researchAreaValue = researchAreaInput ? researchAreaInput.value : '';

    const data = {
        id: paperId,
        research_area: researchAreaValue
    };

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
        body: JSON.stringify(data)
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
                if (data.changed_formatted !== undefined) {
                    row.querySelector('.changed-cell').textContent = data.changed_formatted;
                }
                if (data.changed_by !== undefined) {
                    row.querySelector('.changed-by-cell').textContent = data.changed_by;
                }
                if (data.research_area !== undefined) {
                    const raCell = row.querySelector('.research-area-cell');
                    if (raCell) raCell.textContent = data.research_area || '';
                }
            }
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
        } else {
            console.error('Save error:', data.message);
            if (saveButton) {
                saveButton.textContent = originalText;
                saveButton.disabled = false;
            }
            alert('Error saving changes: ' + data.message);
        }
    })
    .catch((error) => {
        console.error('Error:', error);
        if (saveButton) {
            saveButton.textContent = originalText;
            saveButton.disabled = false;
        }
        alert('An error occurred while saving: ' + error.message);
    });
}