// static/scripts.js
// --- Utility Functions ---
function toggleDetails(element) {   //OK
    const row = element.closest('tr'); // Get the main row
    // if (!row) return; // Safety check
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

// --- Count Logic ---
// Define the fields for which we want to count '✔️'
const COUNT_FIELDS = [
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', // Classification
    'features_solder', 'features_polarity', 'features_wrong_component',
    'features_missing_component', 'features_tracks', 'features_holes', // Features
    'technique_classic_computer_vision_based', 'technique_machine_learning_based',
    'technique_hybrid', 'technique_available_dataset' // Techniques
];

function updateCounts() {
    const counts = {};
    // Initialize counts for status fields
    COUNT_FIELDS.forEach(field => counts[field] = 0);

    // --- Paper Count Logic ---
    // Get all main rows (both visible and hidden by filters)
    const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
    const totalPaperCount = allRows.length;

    // Select only VISIBLE main rows for counting '✔️' and calculating visible count
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const visiblePaperCount = visibleRows.length;
    // --- End Paper Count Logic ---

    // Count '✔️' symbols in visible rows only
    visibleRows.forEach(row => {
        COUNT_FIELDS.forEach(field => {
            const cell = row.querySelector(`.editable-status[data-field="${field}"]`);
            if (cell && cell.textContent.trim() === '✔️') {
                counts[field]++;
            }
        });
    });

    // --- Update the Visible Count Cell ---
    const visibleCountCell = document.getElementById('visible-count-cell');
    if (visibleCountCell) {
        // Use textContent to prevent potential HTML injection issues if counts were user input (they aren't here, but good practice)
        visibleCountCell.textContent = `${visiblePaperCount} paper${visiblePaperCount !== 1 ? 's' : ''} of ${totalPaperCount}`;
    }
    // --- End Update Visible Count Cell ---

    // Update the individual status count footer cells
    COUNT_FIELDS.forEach(field => {
        const countCell = document.getElementById(`count-${field}`);
        if (countCell) {
            countCell.textContent = counts[field]; // This will be the count of '✔️' in visible rows
        }
    });
}

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




// --- Journal Shading Logic ---

/**
 * Calculates the frequency of each journal/conference name among visible rows.
 * @param {NodeList} rows - The main table rows (filtered or unfiltered).
 * @returns {Map<string, number>} A map of journal names to their counts.
 */
function calculateJournalFrequencies(rows) {
    const journalCounts = new Map();

    rows.forEach(row => {
        // Only count visible rows (not hidden by filters)
        if (!row.classList.contains('filter-hidden')) {
            // Assuming Journal/Conf is the 5th column (index 4)
            const journalCell = row.cells[4];
            if (journalCell) {
                const journalName = journalCell.textContent.trim();
                // Only count non-empty journal names
                if (journalName) {
                    journalCounts.set(journalName, (journalCounts.get(journalName) || 0) + 1);
                }
            }
        }
    });

    return journalCounts;
}




/**
 * Applies alternating row shading to visible main rows.
 * Ensures detail rows follow their main row's shading.
 * Each "paper group" (main row + detail row) gets a single alternating color.
 */
function applyAlternatingShading() {
    // Select only visible main rows
    const visibleMainRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');

    // Iterate through the visible main rows. The index 'index' now represents the paper group index.
    visibleMainRows.forEach((mainRow, groupIndex) => {
        // Determine the shade class based on the paper group index (groupIndex)
        // This ensures each paper group (main + detail) gets one color, alternating per group.
        const shadeClass = (groupIndex % 2 === 0) ? 'alt-shade-1' : 'alt-shade-2';

        // --- Apply shading to the main row ---
        // Remove any existing alternating shade classes from the main row
        mainRow.classList.remove('alt-shade-1', 'alt-shade-2');
        // Add the calculated shade class to the main row
        mainRow.classList.add(shadeClass);
        // --- End Apply shading to the main row ---

        // --- Handle Detail Row Shading ---
        let detailRow = mainRow.nextElementSibling;
        // Find the associated detail row, skipping potential intervening elements if necessary
        while (detailRow && !detailRow.classList.contains('detail-row')) {
            // Safety check: stop if another main row is encountered
            if (detailRow.hasAttribute('data-paper-id')) {
                detailRow = null;
                break;
            }
            detailRow = detailRow.nextElementSibling;
        }

        if (detailRow) {
            // Remove any existing alternating shade classes from detail row
            detailRow.classList.remove('alt-shade-1', 'alt-shade-2');
            // Apply the SAME shade class as the main row to the detail row
            detailRow.classList.add(shadeClass);
            // Note: Ensure CSS .detail-row has background-color: inherit; or no background-color set
            // so it uses the one from the .alt-shade-* class.
        }
        // --- End Handle Detail Row Shading ---
    });
}





/**
 * Applies background shading to Journal/Conf cells based on frequency.
 * @param {Map<string, number>} journalCounts - The map of journal names to counts.
 * @param {NodeList} rows - The main table rows.
 * @param {number} maxCount - The highest frequency count for normalization (optional, calculated if not provided).
 */
function applyJournalShading(journalCounts, rows) {
    // Determine the maximum count for scaling
    let maxCount = 0;
    for (const count of journalCounts.values()) {
        if (count > maxCount) maxCount = count;
    }

    // Define base shade color (light blue/greenish tint)
    // You can adjust the HSL values for different base colors or intensity
    const baseHue = 210; // Blueish
    const baseSaturation = 70;
    const minLightness = 97; // Lightest shade (almost white)
    const maxLightness = 80; // Darkest shade when maxCount is high

    rows.forEach(row => {
        // Reset shading first for all rows/cells
        const journalCell = row.cells[4];
        if (journalCell) {
             // Reset to default background (inherits from row)
             journalCell.style.backgroundColor = '';

            // Only apply shading if the row is visible and has a journal name
            if (!row.classList.contains('filter-hidden')) {
                const journalName = journalCell.textContent.trim();
                if (journalName) {
                    const count = journalCounts.get(journalName) || 0;
                    if (count > 1) { // Only shade if appears more than once
                        // Calculate lightness: higher count -> lower lightness (darker)
                        // Scale lightness between maxLightness and minLightness
                        let lightness;
                        if (maxCount <= 1) {
                             lightness = minLightness; // Avoid division by zero or negative
                        } else {
                            // Interpolate lightness based on count relative to maxCount
                            lightness = maxLightness + (minLightness - maxLightness) * (1 - (count - 1) / (maxCount - 1));
                            // Ensure lightness stays within bounds
                            lightness = Math.max(maxLightness, Math.min(minLightness, lightness));
                        }
                        journalCell.style.backgroundColor = `hsl(${baseHue}, ${baseSaturation}%, ${lightness}%)`;
                    }
                }
            }
        }
    });
}












document.addEventListener('DOMContentLoaded', function () {
    const headers = document.querySelectorAll('th[data-sort]');
    let currentClientSort = { column: null, direction: 'ASC' }; 

    // --- Filtering Logic ---
    const searchInput = document.getElementById('search-input');
    const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
    const hideShortCheckbox = document.getElementById('hide-short-checkbox');
    const minPageCountInput = document.getElementById('min-page-count');

    if (hideOfftopicCheckbox) hideOfftopicCheckbox.checked = false;
    if (hideShortCheckbox) hideShortCheckbox.checked = false;

    function applyFilters() {
        const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const hideOfftopic = hideOfftopicCheckbox ? hideOfftopicCheckbox.checked : false;
        const hideShort = hideShortCheckbox ? hideShortCheckbox.checked : false;
        const minPageCountValue = minPageCountInput ? parseInt(minPageCountInput.value, 10) || 0 : 0;

        const tbody = document.querySelector('#papersTable tbody');
        if (!tbody) return;
        const rows = tbody.querySelectorAll('tr[data-paper-id]');

        rows.forEach(row => {
            let showRow = true;
            const paperId = row.getAttribute('data-paper-id');
            let detailRow = null;
            if (paperId) {
                let nextSibling = row.nextElementSibling;
                while (nextSibling && !nextSibling.classList.contains('detail-row')) {
                   if (nextSibling.hasAttribute('data-paper-id')) break; // Stop if another main row is found
                   nextSibling = nextSibling.nextElementSibling;
                }
                if (nextSibling && nextSibling.classList.contains('detail-row')) {
                    detailRow = nextSibling;
                }
            }
            if (showRow && searchTerm) {
                let rowText = (row.textContent || '').toLowerCase();
                let detailText = (detailRow ? detailRow.textContent || '' : '').toLowerCase();
                if (!rowText.includes(searchTerm) && !detailText.includes(searchTerm)) {
                    showRow = false;
                }
            }
            if (showRow && hideOfftopic) {
                const offtopicCell = row.querySelector('.editable-status[data-field="is_offtopic"]');
                if (offtopicCell && offtopicCell.textContent.trim() === '✔️') {
                    showRow = false;
                }
            }
            if (showRow && hideShort) {
                const pageCountCell = row.cells[5]; // Assuming page_count is the 6th column (index 5)
                if (pageCountCell) {
                    const pageCountText = pageCountCell.textContent.trim();
                    const pageCount = pageCountText ? parseInt(pageCountText, 10) : NaN;
                    if (!isNaN(pageCount) && pageCount < minPageCountValue) {
                        showRow = false;
                    }
                    // Optional: Hide if page count is empty/unknown when filtering by page count?
                    // else if (pageCountText === '') {
                    //     showRow = false;
                    // }
                }
            }

            // --- Show/Hide Row and Detail Row ---
            // Use classList.toggle for cleaner, more readable code
            if (row) {
                row.classList.toggle('filter-hidden', !showRow);
            }
            if (detailRow) {
                // Detail row visibility should ideally follow the main row,
                // but only if it's explicitly hidden by filters.
                // If the main row is shown, the detail row's visibility should depend on its own 'expanded' state.
                // However, for simplicity and to ensure it's hidden when the main row is filtered out,
                // we can hide it here. The toggleDetails function handles the 'expanded' class.
                // Let's keep it simple: if main row is hidden by filter, detail row is hidden by filter.
                // If main row is shown by filter, detail row is shown by filter (but might be collapsed).
                detailRow.classList.toggle('filter-hidden', !showRow);
                // Important: Ensure the 'expanded' state is respected if the row becomes visible again.
                // The 'expanded' class controls display:block for detail rows.
                // If the row is shown by filter, we don't force 'expanded' off here.
                // toggleDetails will manage the 'expanded' class.
            }
        });
        // --- End of existing filtering loop ---

        // --- Apply Journal Shading based on visible rows ---
        const currentVisibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
        const currentJournalCounts = calculateJournalFrequencies(currentVisibleRows);
        applyJournalShading(currentJournalCounts, currentVisibleRows);
        // --- End of Journal Shading ---

        updateCounts(); 
        applyAlternatingShading();
    }

    if (searchInput) {           searchInput.addEventListener('input', applyFilters);    }
    if (hideOfftopicCheckbox) {  hideOfftopicCheckbox.addEventListener('change', applyFilters);    }
    if (hideShortCheckbox) {     hideShortCheckbox.addEventListener('change', applyFilters);    }
    if (minPageCountInput) {
        // Use 'input' for immediate response as the user types the number
        minPageCountInput.addEventListener('input', applyFilters);
        // Also listen for 'change' in case the user uses arrow keys or spinner (if supported)
        minPageCountInput.addEventListener('change', applyFilters);
    }
    // --- Call applyFilters initially to ensure state is consistent (e.g., if inputs had values from cache) ---
    // Although defaults are off, good practice.
    applyFilters();
    

    // --- Single Event Listener for Headers (Handles Client-Side Sorting) ---
    headers.forEach(header => {
        header.addEventListener('click', function () {
            const sortBy = this.getAttribute('data-sort');
            if (!sortBy) return;

            let newDirection = 'ASC';
            if (currentClientSort.column === sortBy) { // If clicking the same column, toggle direction
                newDirection = currentClientSort.direction === 'ASC' ? 'DESC' : 'ASC';
            }
            const tbody = document.querySelector('#papersTable tbody');
            if (!tbody) {
                console.error("Table body not found!");
                return;
            }
            const rows = Array.from(tbody.querySelectorAll('tr[data-paper-id]'));

            const getSortValue = (row) => {
                let cellValue = null;
                if (['title', 'year', 'journal', 'authors', 'changed', 'changed_by', 'verified_by', 'research_area', 'type', 'page_count', 'estimated_score'].includes(sortBy)) {
                    let cell = null;
                    const headerIndex = Array.from(header.parentNode.children).indexOf(header);
                    if (headerIndex !== -1) {
                        cell = row.cells[headerIndex];
                    }
                    cellValue = cell ? cell.textContent.trim() : '';
                    
                    if (sortBy === 'year' || sortBy === 'estimated_score' || sortBy === 'page_count' ) {
                        cellValue = parseInt(cellValue, 10) || 0; // Default to 0 if not a number
                    }
                }

                // Handle boolean/status columns (is_survey, is_offtopic, etc.)
                else if (['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray'].includes(sortBy) || sortBy.startsWith('features_') || sortBy.startsWith('technique_')) {
                    const cell = row.querySelector(`.editable-status[data-field="${sortBy}"]`);
                    cellValue = cell ? cell.textContent.trim() : '';
                    // Convert symbols to a sortable value (e.g., ✔️ -> 2, ❌ -> 1, ❔ -> 0)
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
                return newDirection === 'DESC' ? -comparison : comparison;
            });
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
                tbody.appendChild(mainRow);
                if (detailRow) {
                    tbody.appendChild(detailRow);
                }
            });
            updateCounts(); // This updates counts after sorting
            // Re-calculate and re-apply shading based on the CURRENT state of the table.
            // We need to consider ALL main rows to determine visibility and counts correctly.
            const allMainRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
            const currentJournalCountsAfterSort = calculateJournalFrequencies(allMainRows); // Count based on *all* rows' current visibility (filter-hidden class)
            applyJournalShading(currentJournalCountsAfterSort, allMainRows); // Apply shading to *all* main rows based on the new counts and current visibility
            // --- End of Journal Shading after sorting ---
            applyAlternatingShading();
            currentClientSort = { column: sortBy, direction: newDirection };
            document.querySelectorAll('th .sort-indicator').forEach(ind => {
                if (ind) ind.textContent = '';
            });
            const indicator = this.querySelector('.sort-indicator'); // 'this' is the clicked header
            if (indicator) {
                indicator.textContent = newDirection === 'ASC' ? '↑' : '↓';
            }
        });
    });

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
    const data = {
        id: paperId,
        research_area: researchAreaValue,
        page_count: pageCountValue // <-- Add this line
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
                    row.querySelector('.changed-by-cell').innerHTML = renderChangedBy(data.changed_by);
                }
                const pageCountCell = row.cells[5];
                if (pageCountCell) {                     // Handle displaying null/undefined as empty string
                     pageCountCell.textContent = data.page_count !== null && data.page_count !== undefined ? data.page_count : '';
                }
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