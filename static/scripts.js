// static/scripts.js
// --- Utility Functions ---
function toggleDetails(element) {
    const row = element.closest('tr'); // Get the main row
    if (!row) return; // Safety check
    const detailRow = row.nextElementSibling; // Assume detail row is the next sibling
    const isExpanded = detailRow.classList.contains('expanded');

    if (isExpanded) {
        detailRow.classList.remove('expanded');
        element.textContent = 'Expand';
    } else {
        detailRow.classList.add('expanded');
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
    headers.forEach(header => { //server-side table sorting:
        header.addEventListener('click', function () {
            const sortBy = this.getAttribute('data-sort');
            let newOrder = 'ASC';
            const currentIndicator = this.querySelector('.sort-indicator').textContent.trim();
            if (currentIndicator === '↑') {
                newOrder = 'DESC';
            } else if (currentIndicator === '↓') {
                newOrder = 'ASC';
            } else {
                newOrder = 'ASC';
            }
            window.location.href = `?sort_by=${sortBy}&sort_order=${newOrder}`;
        });
    });

    // Update sort indicators based on current URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const currentSortBy = urlParams.get('sort_by');
    const currentSortOrder = urlParams.get('sort_order');

    if (currentSortBy) {
        const sortedHeader = document.querySelector(`th[data-sort="${currentSortBy}"]`);
        if (sortedHeader) {
            const indicator = sortedHeader.querySelector('.sort-indicator');
            if (indicator) {
                if (currentSortOrder && currentSortOrder.toUpperCase() === 'DESC') {
                    indicator.textContent = '↓';
                } else {
                    indicator.textContent = '↑';
                }
            }
        }
    }

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
                nextStatusInfo = STATUS_CYCLE['❔'];
                return;
            }
            const nextSymbol = nextStatusInfo.next;
            const nextValue = nextStatusInfo.value; // This will be 'true', 'false', or 'unknown'

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
            // The backend expects the field name as the key (e.g., 'is_survey', 'features_solder')
            // and the value as 'true', 'false', or 'unknown'.
            const dataToSend = {
                id: paperId, // Include the paper ID
                [field]: nextValue // Use computed property name
            };

            // 3. Send the AJAX request to save the change
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
                    // This ensures consistency if other fields were affected or audit info needs updating
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

                    // Optional: Provide user feedback (though the UI update is immediate)
                    console.log(`Quick save successful for ${paperId} field ${field}`);
                } else {
                    // 5. Handle errors: Revert the UI change and show an error
                    console.error('Quick save error:', data.message);
                    cell.textContent = currentText; // Revert text
                    alert('Error saving quick change: ' + data.message); // Alert user
                }
            })
            .catch((error) => {
                // 5. Handle network/other errors: Revert the UI change and show an error
                console.error('Quick save error:', error);
                cell.textContent = currentText; // Revert text
                alert('An error occurred during quick save: ' + error.message); // Alert user
            })
            .finally(() => {
                // 6. Re-enable the main save button if it was disabled
                if (saveButton) saveButton.disabled = wasSaveButtonDisabled;
            });
        }
    });
    // --- End Click Handler for Editable Status Cells ---
    let currentClientSort = { column: null, direction: 'ASC' }; // Track current client-side sort

    headers.forEach(header => {
        header.addEventListener('click', function () {
            const sortBy = this.getAttribute('data-sort');
            if (!sortBy) return;

            // Determine new sort direction
            let newDirection = 'ASC';
            if (currentClientSort.column === sortBy && currentClientSort.direction === 'ASC') {
                newDirection = 'DESC';
            } // else defaults to ASC

            // Get the table body and rows
            const tbody = document.querySelector('#papersTable tbody');
            // Select only main rows, not detail rows
            const rows = Array.from(tbody.querySelectorAll('tr[data-paper-id]')); 

            // Define a function to get the sort value from a row
            const getSortValue = (row) => {
                let cellValue = null;
                // Handle direct columns (like title, year, type)
                if (['title', 'year', 'journal', 'authors', 'changed', 'changed_by', 'research_area', 'type'].includes(sortBy)) {
                    // Map sortBy to cell index or use a more robust method like data attributes
                    const cellIndexMap = { /* Define mapping based on your table structure */ };
                    const cellIndex = cellIndexMap[sortBy];
                    if (cellIndex !== undefined) {
                        const cell = row.cells[cellIndex];
                        cellValue = cell ? cell.textContent.trim() : '';
                        // Consider type conversion for numbers (year) if needed for correct sorting
                        if (sortBy === 'year') {
                            cellValue = parseInt(cellValue, 10) || 0; // Default to 0 if not a number
                        }
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

            // Perform the sort on the array of row elements
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
                // If values are equal, you might add a secondary sort (e.g., by ID)
                if (comparison === 0) {
                    const idA = parseInt(a.getAttribute('data-paper-id'), 10) || 0;
                    const idB = parseInt(b.getAttribute('data-paper-id'), 10) || 0;
                    comparison = idA - idB; // ASC by ID as tie-breaker
                }

                // Apply sort direction
                return newDirection === 'DESC' ? -comparison : comparison;
            });

            // Re-append sorted rows to the tbody
            rows.forEach(row => tbody.appendChild(row));
            // Also re-append the corresponding detail rows if they exist and need to follow
            // This part requires careful handling to ensure detail rows stay with their main rows
            // You might need to move the detail row immediately after appending its main row
            // e.g., 
            // rows.forEach(row => {
            //    tbody.appendChild(row);
            //    const detailRow = row.nextElementSibling; // Assumes detail row follows immediately
            //    if (detailRow && detailRow.classList.contains('detail-row')) {
            //       tbody.appendChild(detailRow);
            //    }
            // });

            // Update the global sort state
            currentClientSort = { column: sortBy, direction: newDirection };

            // Update visual sort indicators
            // Clear all indicators first
            document.querySelectorAll('th .sort-indicator').forEach(ind => ind.textContent = '');
            // Set indicator on the clicked header
            const indicator = this.querySelector('.sort-indicator');
            if (indicator) {
                indicator.textContent = newDirection === 'ASC' ? '↑' : '↓';
            }
        });
    });

    // Potentially remove or simplify the URL-based indicator update on page load
    // since sorting state is now client-side.
    // Or, you could still use URL params to trigger an initial client-side sort on load.
});

// --- Functions that might be called from inline HTML ---
function saveChanges(paperId) { //currently used only for "research area" text field
    const form = document.getElementById(`form-${paperId}`);
    if (!form) {
        console.error(`Form not found for paper ID: ${paperId}`);
        return;
    }
    const researchAreaInput = form.querySelector('input[name="research_area"]');
    const researchAreaValue = researchAreaInput ? researchAreaInput.value : '';

    // --- Prepare data to send (only ID and research_area) ---
    const data = {
        id: paperId,
        research_area: researchAreaValue
    };

    const saveButton = form.querySelector('.save-btn');
    const originalText = saveButton ? saveButton.textContent : 'Save Changes';

    if (saveButton) {
        saveButton.textContent = 'Saving...';
        saveButton.disabled = true; // Disable button during save
    }

    fetch('/update_paper', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data) // Send only the filtered data
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
            // Update the main table row cells dynamically
            const row = document.querySelector(`tr[data-paper-id="${paperId}"]`);
            if (row) {
                // Update audit fields (using formatted timestamp)
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

            // Collapse the detail row
            const toggleBtn = row ? row.querySelector('.toggle-btn') : null;
            if (toggleBtn && row && row.nextElementSibling && row.nextElementSibling.classList.contains('expanded')) {
                 toggleDetails(toggleBtn); // Re-use the toggle function
            }

            // Provide user feedback
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
            alert('Error saving changes: ' + data.message); // Fallback alert for errors
        }
    })
    .catch((error) => {
        console.error('Error:', error);
        if (saveButton) {
            saveButton.textContent = originalText;
            saveButton.disabled = false;
        }
        alert('An error occurred while saving: ' + error.message); // Fallback alert for errors
    });
}