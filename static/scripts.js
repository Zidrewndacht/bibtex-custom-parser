// static/scripts.js

// --- Utility Functions ---

// --- Utility Functions ---
function toggleDetails(element) {
    const row = element.closest('tr'); // Get the main row
    if (!row) return; // Safety check
    const detailRow = row.nextElementSibling; // Assume detail row is the next sibling

    // Safety check for detail row existence and class
    if (!detailRow || !detailRow.classList.contains('detail-row')) {
        console.error('Detail row not found or incorrect structure.');
        return;
    }

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
    headers.forEach(header => {
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
            // Optional: Add a brief visual feedback (e.g., flash)
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
});

// --- Functions that might be called from inline HTML ---

function saveChanges(paperId) {
    // Ensure it uses `renderStatus` correctly and updates cells.
    // You might want to refactor it slightly to share update logic with the quick save.
    const form = document.getElementById(`form-${paperId}`);
    if (!form) {
        console.error(`Form not found for paper ID: ${paperId}`);
        return;
    }
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());
    data['id'] = paperId; // Include paper ID

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

                // Update classification summary cells
                if (data.is_survey !== undefined) row.querySelector('.status-cell[data-field="is_survey"]').textContent = renderStatus(data.is_survey === 'true' ? true : data.is_survey === 'false' ? false : null);
                if (data.is_offtopic !== undefined) row.querySelector('.status-cell[data-field="is_offtopic"]').textContent = renderStatus(data.is_offtopic === 'true' ? true : data.is_offtopic === 'false' ? false : null);
                if (data.is_through_hole !== undefined) row.querySelector('.status-cell[data-field="is_through_hole"]').textContent = renderStatus(data.is_through_hole === 'true' ? true : data.is_through_hole === 'false' ? false : null);
                if (data.is_smt !== undefined) row.querySelector('.status-cell[data-field="is_smt"]').textContent = renderStatus(data.is_smt === 'true' ? true : data.is_smt === 'false' ? false : null);
                if (data.is_x_ray !== undefined) row.querySelector('.status-cell[data-field="is_x_ray"]').textContent = renderStatus(data.is_x_ray === 'true' ? true : data.is_x_ray === 'false' ? false : null);

                if (data.research_area !== undefined) {
                    const raCell = row.cells[5]; // Assuming index 5 is research_area
                    if (raCell) raCell.textContent = data.research_area || '';
                }

                // Update features summary cells
                for (const [key, value] of Object.entries(data.features || {})) {
                    if (key !== 'other') {
                        const cell = row.querySelector(`.status-cell[data-field="features_${key}"]`);
                        if (cell) {
                            cell.textContent = renderStatus(value === 'true' ? true : value === 'false' ? false : null);
                        }
                    }
                }

                // Update techniques summary cells
                for (const [key, value] of Object.entries(data.technique || {})) {
                    if (key !== 'model') {
                        const cell = row.querySelector(`.status-cell[data-field="technique_${key}"]`);
                        if (cell) {
                            cell.textContent = renderStatus(value === 'true' ? true : value === 'false' ? false : null);
                        }
                    }
                }
            }

            // Collapse the detail row
            const toggleBtn = row ? row.querySelector('.toggle-btn') : null;
            if (toggleBtn && row && row.nextElementSibling && row.nextElementSibling.style.display === 'table-row') {
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