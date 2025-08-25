// static/filtering.js
/** For filtering, stats counters and other purely-local functionality that doesn't do any communication with the server: */
// --- Filtering Logic ---
const searchInput = document.getElementById('search-input');
const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
const hideShortCheckbox = document.getElementById('hide-short-checkbox');
const minPageCountInput = document.getElementById('min-page-count');

const hideOlderCheckbox = document.getElementById('hide-older-checkbox');
const maxAgeInput = document.getElementById('max-age');

const fullscreenBtn = document.getElementById('fullscreen-btn');

// Get all main rows (both visible and hidden by filters) only once:
const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
const totalPaperCount = allRows.length;

let filterTimeoutId = null;
const FILTER_DEBOUNCE_DELAY = 200; 

// --- Add a variable to hold the latest counts ---
let latestCounts = {}; // This will store the counts calculated by updateCounts

// --- Optimized Client-Side Sorting ---
// Pre-calculate symbol weights OUTSIDE the sort loop for efficiency
const SYMBOL_SORT_WEIGHTS = {
    '✔️': 2, // Yes
    '❌': 1, // No
    '❔': 0  // Unknown
};

function scheduleFilterUpdate() {
    clearTimeout(filterTimeoutId);
    // Set the cursor immediately on user interaction
    document.documentElement.classList.add('busyCursor');
    // Debounce the actual filtering
    filterTimeoutId = setTimeout(() => {
        // Use setTimeout(0) to defer the heavy work to the next event loop tick.
        // This allows the browser to process the 'progress' cursor change.
        setTimeout(() => {
            applyFilters(); // Run the expensive filtering
            // Apply rAF here if needed for post-filter updates, 
            // though applyFilters already calls them.
        }, 0);
    }, FILTER_DEBOUNCE_DELAY);
}

function toggleDetails(element) {   //OK
    const row = element.closest('tr');
    const detailRow = row.nextElementSibling; // Assume detail row is the next sibling
    const isExpanded = detailRow && detailRow.classList.contains('expanded'); // Check if detailRow exists
    if (isExpanded) {
        if (detailRow) detailRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span>';
    } else {
        if (detailRow) detailRow.classList.add('expanded');
        element.innerHTML = '<span>Hide</span>';
    }
}

// --- Count Logic ---
// Define the fields for which we want to count '✔️'
const COUNT_FIELDS = [
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', // Classification
    'features_solder', 'features_polarity', 'features_wrong_component',
    'features_missing_component', 'features_tracks', 'features_holes', 'features_cosmetic', // Features
    'technique_classic_computer_vision_based', 'technique_machine_learning_based',
    'technique_dl_cnn_based', 'technique_dl_rcnn_based', 'technique_dl_transformer_based','technique_dl_other', 
    'technique_hybrid', 'technique_available_dataset', // Techniques
    'changed_by', 'verified_by' // Add these for user counting
];
// --- Modify updateCounts() ---
function updateCounts() {
    const counts = {};
    // Initialize counts for ALL status fields (including changed_by, verified_by)
    COUNT_FIELDS.forEach(field => counts[field] = 0);
    // --- Paper Count Logic ---
    // Select only VISIBLE main rows for counting '✔️' and calculating visible count
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const visiblePaperCount = visibleRows.length;
    // --- End Paper Count Logic ---

    // Count symbols in visible rows
    visibleRows.forEach(row => {
        COUNT_FIELDS.forEach(field => {
            // --- CORRECTED SELECTOR: Use general selector [data-field="${field}"] ---
            // This works for both .editable-status/data-field and .status-cell/data-field cells
            const cell = row.querySelector(`[data-field="${field}"]`);
            if (cell) {
                const cellText = cell.textContent.trim();
                if (field === 'changed_by' || field === 'verified_by') {
                    // Count '👤' for these specific fields
                    if (cellText === '👤') {
                        counts[field]++;
                    }
                } else {
                    // Count '✔️' for the original fields
                    if (cellText === '✔️') {
                        counts[field]++;
                    }
                }
            }
        });
    });
    // --- NEW: Store the counts globally ---
    latestCounts = counts; // Make counts available outside this function
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
            // This will be the count of '✔️' or '👤' in visible rows, depending on the field
            countCell.textContent = counts[field];
        }
    });
}
// --- End Modify updateCounts() ---

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

        // Remove any existing alternating shade classes from the main row
        mainRow.classList.remove('alt-shade-1', 'alt-shade-2');
        mainRow.classList.add(shadeClass);

        // --- Handle Detail Row Shading ---
        mainRow.nextElementSibling.classList.remove('alt-shade-1', 'alt-shade-2');
        mainRow.nextElementSibling.classList.add(shadeClass);
        // Note: Ensure CSS .detail-row has background-color: inherit; or no background-color set
        // so it uses the one from the .alt-shade-* class.
    });
}


// --- Journal Shading Logic ---
function applyJournalShading(rows) {
    const journalCounts = new Map();

    rows.forEach(row => {
        // Only count visible rows (not hidden by filters)
        if (!row.classList.contains('filter-hidden')) {
            // Assuming Journal/Conf is the 5th column (index 4)
            const journalCell = row.cells[3]; //moved afer hiding authors column
            if (journalCell) {
                const journalName = journalCell.textContent.trim();
                // Only count non-empty journal names
                if (journalName) {
                    journalCounts.set(journalName, (journalCounts.get(journalName) || 0) + 1);
                }
            }
        }
    });
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
        const journalCell = row.cells[3]; //moved afer hiding authors column
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


function applyFilters() {
    const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';
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
        if (showRow && hideOfftopicCheckbox.checked) {
            const offtopicCell = row.querySelector('.editable-status[data-field="is_offtopic"]');
            if (offtopicCell && offtopicCell.textContent.trim() === '✔️') {
                showRow = false;
            }
        }
        if (showRow && hideShortCheckbox.checked) {
            const pageCountCell = row.cells[4]; //moved afer hiding authors column
            if (pageCountCell) {
                const minPageCountValue = minPageCountInput ? parseInt(minPageCountInput.value, 10) || 0 : 0;
                const pageCountText = pageCountCell.textContent.trim();
                const pageCount = pageCountText ? parseInt(pageCountText, 10) : NaN;
                if (!isNaN(pageCount) && pageCount < minPageCountValue) {
                    showRow = false;
                }
            }
        }
        if (showRow && hideOlderCheckbox && hideOlderCheckbox.checked) {
            const maxAgeValue = parseInt(maxAgeInput.value, 10);
            // Only apply if the max age is a valid number greater than 0
            if (!isNaN(maxAgeValue) && maxAgeValue > 0) {
                const yearCell = row.cells[2]; //moved afer hiding authors column
                if (yearCell) {
                    const yearText = yearCell.textContent.trim();
                    const paperYear = yearText ? parseInt(yearText, 10) : NaN;
                    // Check if the paper year is a valid number and older than the cutoff
                    if (!isNaN(paperYear)) {
                         const currentYear = new Date().getFullYear();
                         const cutoffYear = currentYear - maxAgeValue;
                         if (paperYear < cutoffYear) {
                              showRow = false;
                         }
                    }
                }
            }
        }
        if (showRow && searchTerm) {
            let rowText = (row.textContent || '').toLowerCase();

            let detailText = '';
            if (detailRow) {
                // Create a clone to avoid modifying the original DOM temporarily
                const detailClone = detailRow.cloneNode(true);
                detailClone.querySelector('.detail-evaluator-trace .trace-content').remove(); // Remove the evaluator trace content
                detailClone.querySelector('.detail-verifier-trace .trace-content').remove();  // Remove the verifier trace content

                // Now get the text content of the modified clone (excluding traces)
                detailText = (detailClone.textContent || '').toLowerCase();
            }
            // Check if the search term is present in either the main row or the filtered detail row text
            if (!rowText.includes(searchTerm) && !detailText.includes(searchTerm)) {
                showRow = false;
            }
        }
        // --- Show/Hide Row and Detail Row ---
        // Use classList.toggle for cleaner, more readable code
        row.classList.toggle('filter-hidden', !showRow);
        // if main row is hidden by filter, detail row is hidden by filter.
        // If main row is shown by filter, detail row is shown by filter (but might be collapsed).
        detailRow.classList.toggle('filter-hidden', !showRow);
    });

    // --- Reapply Journal Shading based on visible rows ---
    const currentVisibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
    applyJournalShading(currentVisibleRows);
    updateCounts();
    applyAlternatingShading();
    
    // Reset cursor after filtering is complete
    document.documentElement.classList.remove('busyCursor');
}

document.addEventListener('DOMContentLoaded', function () {
    const headers = document.querySelectorAll('th[data-sort]');
    let currentClientSort = { column: null, direction: 'ASC' }; 
    //Start with both filters enabled:
    hideOfftopicCheckbox.checked = true;
    hideShortCheckbox.checked = true;
    hideOlderCheckbox.checked = true;

    searchInput.addEventListener('input', scheduleFilterUpdate);
    hideOfftopicCheckbox.addEventListener('change', scheduleFilterUpdate);
    hideShortCheckbox.addEventListener('change', scheduleFilterUpdate);
    minPageCountInput.addEventListener('input', scheduleFilterUpdate);
    minPageCountInput.addEventListener('change', scheduleFilterUpdate);
    hideOlderCheckbox.addEventListener('change', scheduleFilterUpdate);
    maxAgeInput.addEventListener('input', scheduleFilterUpdate);
    maxAgeInput.addEventListener('change', scheduleFilterUpdate);

    // --- Close Modal with Escape Key ---
    document.addEventListener('keydown', function(event) {
        // Check if the pressed key is 'Escape' and if the modal is currently active
        if (event.key === 'Escape' && modal.classList.contains('modal-active')) {
            closeModal(); // Call your existing closeModal function
        }
    });
    applyFilters(); //apply initial filtering
    
    // --- Single Event Listener for Headers (Handles Optimized Client-Side Sorting) ---
    headers.forEach(header => {
        header.addEventListener('click', function () {
            document.documentElement.classList.add('busyCursor');
            setTimeout(() => {
                const sortBy = this.getAttribute('data-sort');
                if (!sortBy) return;

                // --- Determine Sort Direction ---
                let newDirection = 'DESC';
                if (currentClientSort.column === sortBy) {
                    newDirection = currentClientSort.direction === 'DESC' ? 'ASC' : 'DESC';
                }

                const tbody = document.querySelector('#papersTable tbody');
                if (!tbody) return;

                // --- PRE-PROCESS: Extract Sort Values and Row References ---
                const visibleMainRows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
                const headerIndex = Array.prototype.indexOf.call(this.parentNode.children, this);
                const sortData = [];
                let mainRow, paperId, cellValue, detailRow, cell;

                for (let i = 0; i < visibleMainRows.length; i++) {
                    mainRow = visibleMainRows[i];
                    paperId = mainRow.getAttribute('data-paper-id');

                    // --- Determine Sort Value (Ultra-Direct) ---
                    if (['title', 'year', 'journal', /*'authors',*/ 'page_count', 'estimated_score'].includes(sortBy)) {
                        cell = mainRow.cells[headerIndex];
                        cellValue = cell.textContent.trim();
                        if (sortBy === 'year' || sortBy === 'estimated_score' || sortBy === 'page_count') {
                            cellValue = parseFloat(cellValue) || 0;
                        }
                    } else if (['type', 'changed', 'changed_by', 'verified', 'verified_by', 'research_area'].includes(sortBy)) {
                        cell = mainRow.cells[headerIndex];
                        cellValue = cell ? cell.textContent.trim() : '';
                    } else { // Status/Feature/Technique columns
                        cell = mainRow.querySelector(`.editable-status[data-field="${sortBy}"]`);
                        cellValue = SYMBOL_SORT_WEIGHTS[cell.textContent.trim()] ?? 0;
                    }

                    detailRow = mainRow.nextElementSibling;
                    sortData.push({ value: cellValue, mainRow, detailRow, paperId });
                }

                // --- SORT the Array of Objects ---
                sortData.sort((a, b) => {
                    let comparison = 0;
                    if (a.value > b.value) comparison = 1;
                    else if (a.value < b.value) comparison = -1;
                    else {
                        if (a.paperId > b.paperId) comparison = 1;
                        else if (a.paperId < b.paperId) comparison = -1;
                    }
                    return newDirection === 'DESC' ? -comparison : comparison;
                });

                // --- BATCH UPDATE the DOM ---
                const fragment = document.createDocumentFragment();
                for (let i = 0; i < sortData.length; i++) {
                    fragment.appendChild(sortData[i].mainRow);
                    fragment.appendChild(sortData[i].detailRow);
                }
                tbody.appendChild(fragment);

                // --- Schedule UI Updates ---
                requestAnimationFrame(() => { applyAlternatingShading(); });
                requestAnimationFrame(() => {
                    const currentVisibleRowsForJournal = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
                    applyJournalShading(currentVisibleRowsForJournal);
                });
                requestAnimationFrame(() => { updateCounts(); });

                currentClientSort = { column: sortBy, direction: newDirection };

                document.documentElement.classList.remove('busyCursor');
                // Update sort indicators
                document.querySelectorAll('th .sort-indicator').forEach(ind => ind.textContent = '');
                this.querySelector('.sort-indicator').textContent = newDirection === 'ASC' ? '▲' : '▼'; // Assuming correct symbols

            }, 0); // Defer execution
        });
    });

    // --- Stats Modal Functionality ---
    const statsBtn = document.getElementById('stats-btn');
    const modal = document.getElementById('statsModal');
    const spanClose = document.querySelector('#statsModal .close'); // Specific close button

    // Function to calculate statistics from visible rows
    function calculateStats() {
        const stats = {
            journals: {},
            keywords: {},
            authors: {}, // NEW: Initialize authors object
            researchAreas: {}
        };

        const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');

        visibleRows.forEach(row => {
            // --- Journal/Conf ---
            const journalCell = row.cells[3]; // Index 3 for Journal/Conf
            if (journalCell) {
                const journal = journalCell.textContent.trim();
                if (journal) {
                    stats.journals[journal] = (stats.journals[journal] || 0) + 1;
                }
            }

            // --- Keywords ---
            // Keywords are in the detail row. Find it.
            const detailRow = row.nextElementSibling;
            if (detailRow && detailRow.classList.contains('detail-row')) {
                // Find the Keywords paragraph within the detail metadata div
                const keywordsPara = detailRow.querySelector('.detail-metadata p strong');
                if (keywordsPara && keywordsPara.textContent.trim() === 'Keywords:') {
                    // Get the text content *after* the <strong>Keywords:</strong>
                    // A simple way is to get the parent's text and remove the strong part
                    const keywordsParent = keywordsPara.parentElement;
                    if (keywordsParent) {
                        // Extract text content and remove the "Keywords:" part
                        let keywordsText = keywordsParent.textContent.trim();
                        const prefix = "Keywords:";
                        if (keywordsText.startsWith(prefix)) {
                            keywordsText = keywordsText.substring(prefix.length).trim();
                        }
                        // Split by ';', trim whitespace, filter out empty strings
                        const keywordsList = keywordsText.split(';')
                            .map(kw => kw.trim())
                            .filter(kw => kw.length > 0);

                        keywordsList.forEach(keyword => {
                            stats.keywords[keyword] = (stats.keywords[keyword] || 0) + 1;
                        });
                    }
                }
            }

            // --- Authors (REPLACEMENT/NEW CODE) ---
            // Authors are also in the detail row metadata, like keywords.
            let authorsList = []; // Initialize an empty list for authors for this row
            const detailRowForAuthors = row.nextElementSibling;
            if (detailRowForAuthors && detailRowForAuthors.classList.contains('detail-row')) {
                // Find the paragraph containing 'Full Authors:'
                // Query for the <p> tag that contains a <strong> tag with the text 'Full Authors:'
                // This is more robust than assuming the *first* <p> or relying solely on the <strong> tag's text.
                const authorsPara = Array.from(detailRowForAuthors.querySelectorAll('.detail-metadata p')).find(p => {
                    const strongTag = p.querySelector('strong');
                    return strongTag && strongTag.textContent.trim() === 'Full Authors:';
                });

                if (authorsPara) {
                    // Get the full text content of the paragraph
                    let authorsText = authorsPara.textContent.trim();
                    const prefix = "Full Authors:";
                    // Check if it starts with the prefix and remove it
                    if (authorsText.startsWith(prefix)) {
                        authorsText = authorsText.substring(prefix.length).trim();
                    }
                    // Safety check: ensure we have text left after removing the prefix
                    if (authorsText) {
                        // Split by ';', trim whitespace, filter out empty strings
                        authorsList = authorsText.split(';')
                            .map(author => author.trim())
                            .filter(author => author.length > 0);
                    } else {
                        console.warn("Found 'Full Authors:' paragraph but no author text following it.", row);
                    }
                } else {
                    // It's possible the paper has no authors listed, or the format is unexpected.
                    // This might be common enough not to warn, but uncomment if debugging:
                    // console.warn("Could not find 'Full Authors:' paragraph in detail row.", row);
                }
            }

            // Now, increment counts for the authors found for this row
            authorsList.forEach(author => {
                // Ensure stats.authors object exists
                stats.authors = stats.authors || {};
                // Increment count for the author
                stats.authors[author] = (stats.authors[author] || 0) + 1;
            });
            // --- End Authors (REPLACEMENT/NEW CODE) ---


            // --- Research Area ---
            const detailRowForResearchArea = row.nextElementSibling;
            if (detailRowForResearchArea && detailRowForResearchArea.classList.contains('detail-row')) {
                const researchAreaInput = detailRowForResearchArea.querySelector('.detail-edit input[name="research_area"]');
                if (researchAreaInput) {
                    const researchArea = researchAreaInput.value.trim();
                    if (researchArea) {
                        // If research areas are also multi-valued like keywords, adapt parsing here.
                        // For now, treat the whole input value as a single research area.
                        stats.researchAreas[researchArea] = (stats.researchAreas[researchArea] || 0) + 1;
                    }
                }
            }
        });

        return stats;
    }

    function displayStats() {
        // --- NEW: Chart Creation Logic (Read counts from footer) ---

        // Define the fields for Features and Techniques explicitly for charting
        const FEATURE_FIELDS = [
            'features_tracks', 'features_holes', 'features_solder',
            'features_missing_component', 'features_wrong_component',
            'features_polarity', 'features_cosmetic'
        ];

        // Include Datasets here temporarily to get the label mapping easily,
        // then filter it out for data/labels for the Techniques chart
        const TECHNIQUE_FIELDS_ALL = [
            'technique_classic_computer_vision_based', 'technique_machine_learning_based',
            'technique_dl_cnn_based', 'technique_dl_rcnn_based',
            'technique_dl_transformer_based', 'technique_dl_other', 'technique_hybrid',
            'technique_available_dataset' // Included to get label easily
        ];

        // Map field names to user-friendly labels (based on your table headers)
        const FIELD_LABELS = {
            'features_tracks': 'Tracks',
            'features_holes': 'Holes',
            'features_solder': 'Solder',
            'features_missing_component': 'Missing Component',
            'features_wrong_component': 'Wrong Component',
            'features_polarity': 'Polarity',
            'features_cosmetic': 'Cosmetic',
            'technique_classic_computer_vision_based': 'Classic CV',
            'technique_machine_learning_based': 'ML',
            'technique_dl_cnn_based': 'CNN',
            'technique_dl_rcnn_based': 'R-CNN',
            'technique_dl_transformer_based': 'Transformer',
            'technique_dl_other': 'Other DL',
            'technique_hybrid': 'Hybrid',
            'technique_available_dataset': 'Datasets' // Label for Datasets
        };

        // --- Read Counts from Footer Cells ---
        // We read the counts directly from the cells updated by updateCounts()
        function getCountFromFooter(fieldId) {
            const cell = document.getElementById(`count-${fieldId}`);
            if (cell) {
                const text = cell.textContent.trim();
                const number = parseInt(text, 10);
                return isNaN(number) ? 0 : number;
            }
            return 0;
        }




        
        // --- Prepare Features Chart Data ---
        // Read and sort the data
        const featuresData = FEATURE_FIELDS.map(field => ({
            label: FIELD_LABELS[field] || field,
            value: getCountFromFooter(field)
        }));

        // Sort by value descending (largest first)
        featuresData.sort((a, b) => b.value - a.value);

        // Extract sorted labels and values
        const sortedFeaturesLabels = featuresData.map(item => item.label);
        const sortedFeaturesValues = featuresData.map(item => item.value);

        // Define colors (same order as original)
        const featuresColors = [
            'hsla(347, 70%, 49%, 0.66)', // Red
            'hsla(204, 82%, 37%, 0.66)',  // Blue
            'hsla(42, 100%, 37%, 0.66)',  // Yellow
            'hsla(180, 48%, 32%, 0.66)',  // Teal
            'hsla(260, 80%, 50%, 0.66)', // Purple
            'hsla(30, 100%, 43%, 0.66)',  // Orange
            'hsla(0, 0%, 48%, 0.66)'  // Grey
        ];

        const featuresBorderColors = [
            'hsla(347, 70%, 29%, 1.00)',
            'hsla(204, 82%, 18%, 1.00)',
            'hsla(42, 100%, 18%, 1.00)',
            'hsla(180, 48%, 18%, 1.00)',
            'hsla(260, 100%, 30%, 1.00)',
            'hsla(30, 100%, 23%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)'
        ];

        const featuresChartData = {
            labels: sortedFeaturesLabels,
            datasets: [{
                label: 'Features Count',
                data: sortedFeaturesValues,
                backgroundColor: featuresColors,
                borderColor: featuresBorderColors,
                borderWidth: 2,
                hoverOffset: 4
            }]
        };

        // --- Prepare Techniques Chart Data (Excluding Datasets count) ---
        const TECHNIQUE_FIELDS_NO_DATASET = TECHNIQUE_FIELDS_ALL.filter(field => field !== 'technique_available_dataset');

        // Read and sort the data
        const techniquesData = TECHNIQUE_FIELDS_NO_DATASET.map(field => ({
            label: FIELD_LABELS[field] || field,
            value: getCountFromFooter(field)
        }));

        // Sort by value descending (largest first)
        techniquesData.sort((a, b) => b.value - a.value);

        // Extract sorted labels and values
        const sortedTechniquesLabels = techniquesData.map(item => item.label);
        const sortedTechniquesValues = techniquesData.map(item => item.value);

        // Define colors (same order as original)
        const techniquesColors = [
            'hsla(347, 70%, 49%, 0.66)', // Red
            'hsla(204, 82%, 37%, 0.66)',  // Blue
            'hsla(42, 100%, 37%, 0.66)',  // Yellow
            'hsla(180, 48%, 32%, 0.66)',  // Teal
            'hsla(260, 80%, 50%, 0.66)', // Purple
            'hsla(30, 100%, 43%, 0.66)',  // Orange
            'hsla(0, 0%, 48%, 0.66)'  // Grey
        ];

        const techniquesBorderColors = [
            'hsla(347, 70%, 29%, 1.00)',
            'hsla(204, 82%, 18%, 1.00)',
            'hsla(42, 100%, 18%, 1.00)',
            'hsla(180, 48%, 18%, 1.00)',
            'hsla(260, 100%, 30%, 1.00)',
            'hsla(30, 100%, 23%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)'
        ];

        const techniquesChartData = {
            labels: sortedTechniquesLabels,
            datasets: [{
                label: 'Techniques Count',
                data: sortedTechniquesValues,
                backgroundColor: techniquesColors,
                borderColor: techniquesBorderColors,
                borderWidth: 2,
                hoverOffset: 4
            }]
        };

        // --- Destroy existing charts if they exist (important for re-renders) ---
        if (window.featuresPieChartInstance) {
            window.featuresPieChartInstance.destroy();
            delete window.featuresPieChartInstance; // Optional: clean up reference
        }
        if (window.techniquesPieChartInstance) {
            window.techniquesPieChartInstance.destroy();
            delete window.techniquesPieChartInstance; // Optional: clean up reference
        }

        // --- Get Canvas Contexts ---
        const featuresCtx = document.getElementById('featuresPieChart')?.getContext('2d');
        const techniquesCtx = document.getElementById('techniquesPieChart')?.getContext('2d');

        // // Pizza chart version:
        // if (featuresCtx) {
        //     window.featuresPieChartInstance = new Chart(featuresCtx, {
        //         type: 'pie',
        //         data: featuresChartData,
        //         options: {
        //             responsive: true,
        //             maintainAspectRatio: false, // Important with fixed container height
        //             plugins: {
        //                 legend: {
        //                     position: 'top',
        //                 },
        //                 title: {
        //                     display: false, // Title is in the H3
        //                 },
        //                 tooltip: {
        //                     callbacks: {
        //                         // Optional: Customize tooltip label
        //                         label: function(context) {
        //                             return `${context.label}: ${context.raw}`;
        //                         }
        //                     }
        //                 }
        //                 // Optional: Add data labels inside slices (requires chartjs-plugin-datalabels)
        //                 // datalabels: { anchor: 'center', align: 'center', formatter: (value) => value > 0 ? value : '' }
        //             }
        //         }
        //     });
        // } else {
        //     console.warn("Canvas context for featuresPieChart not found.");
        // }
                // if (techniquesCtx) {
        //     window.techniquesPieChartInstance = new Chart(techniquesCtx, {
        //         type: 'bar', // Changed from 'pie' to 'bar'
        //         data: techniquesChartData,
        //         options: {
        //             indexAxis: 'y', // This makes it horizontal
        //             responsive: true,
        //             maintainAspectRatio: false,
        //             plugins: {
        //                 legend: {
        //                     display: false // Hide legend for cleaner look
        //                 },
        //                 title: {
        //                     display: false
        //                 },
        //                 tooltip: {
        //                     callbacks: {
        //                         label: function(context) {
        //                             return `${context.label}: ${context.raw}`;
        //                         }
        //                     }
        //                 }
        //             },
        //             scales: {
        //                 x: {
        //                     beginAtZero: true,
        //                     ticks: {
        //                         precision: 0 // Only show whole numbers
        //                     }
        //                 }
        //             }
        //         }
        //     });
        // } else {
        //     console.warn("Canvas context for techniquesPieChart not found.");
        // }
        // if (techniquesCtx) {
        //     window.techniquesPieChartInstance = new Chart(techniquesCtx, {
        //         type: 'pie',
        //         data: techniquesChartData,
        //         options: {
        //             responsive: true,
        //             maintainAspectRatio: false, // Important with fixed container height
        //             plugins: {
        //                 legend: {
        //                     position: 'top',
        //                 },
        //                 title: {
        //                     display: false, // Title is in the H3
        //                 },
        //                 tooltip: {
        //                     callbacks: {
        //                         // Optional: Customize tooltip label
        //                         label: function(context) {
        //                             return `${context.label}: ${context.raw}`;
        //                         }
        //                     }
        //                 }
        //                 // Optional: Add data labels inside slices
        //                 // datalabels: { anchor: 'center', align: 'center', formatter: (value) => value > 0 ? value : '' }
        //             }
        //         }
        //     });
        // } else {
        //     console.warn("Canvas context for techniquesPieChart not found.");
        // }
        // --- Render Charts if contexts exist ---
        if (featuresCtx) {
            window.featuresPieChartInstance = new Chart(featuresCtx, {
                type: 'bar', // Changed from 'pie' to 'bar'
                data: featuresChartData,
                options: {
                    indexAxis: 'y', // This makes it horizontal
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false // Hide legend for cleaner look
                        },
                        title: {
                            display: false
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return `${context.label}: ${context.raw}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: {
                                precision: 0 // Only show whole numbers
                            }
                        }
                    }
                }
            });
        } else {
            console.warn("Canvas context for featuresPieChart not found.");
        }


        if (techniquesCtx) {
            window.techniquesPieChartInstance = new Chart(techniquesCtx, {
                type: 'bar', // Changed from 'pie' to 'bar'
                data: techniquesChartData,
                options: {
                    indexAxis: 'y', // This makes it horizontal
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false // Hide legend for cleaner look
                        },
                        title: {
                            display: false
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return `${context.label}: ${context.raw}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: {
                                precision: 0 // Only show whole numbers
                            }
                        }
                    }
                }
            });
        } else {
            console.warn("Canvas context for techniquesPieChart not found.");
        }

        const stats = calculateStats(); 
        
        // Helper function to populate a list element
        function populateList(listElementId, dataObj) {
            // ... (existing populateList code remains exactly the same) ...
            const listElement = document.getElementById(listElementId);
            listElement.innerHTML = ''; // Clear previous content
            // Convert object to array, filter for count > 1, then sort
            // 1. Convert to array of [name, count] pairs
            // 2. Filter: keep only entries where count > 1
            // 3. Sort: by count (desc) then name (asc)
            const sortedEntries = Object.entries(dataObj)
                .filter(([name, count]) => count > 1) // Only include counts > 1
                .sort((a, b) => {
                    // Sort by count descending
                    if (b[1] !== a[1]) {
                        return b[1] - a[1];
                    }
                    // If counts are equal, sort by name ascending
                    return a[0].localeCompare(b[0]);
                });
            if (sortedEntries.length === 0) {
                listElement.innerHTML = '<li>No items with count > 1.</li>';
                return;
            }
            sortedEntries.forEach(([name, count]) => {
                const listItem = document.createElement('li');
                // Escape potential HTML in names (basic)
                const escapedName = name.replace(/&/g, "&amp;").replace(/</g, "<").replace(/>/g, ">");
                // Swap the order: count first, then name
                listItem.innerHTML = `<span class="count">${count}</span> <span class="name">${escapedName}</span>`;
                listElement.appendChild(listItem);
            });
        }

        // --- Animate In ---
        // Populate content first (existing calls - these also remain unchanged)
        populateList('journalStatsList', stats.journals);
        populateList('keywordStatsList', stats.keywords);
        populateList('authorStatsList', stats.authors);
        populateList('researchAreaStatsList', stats.researchAreas);

        // Trigger reflow to ensure styles are applied before adding the active class
        // This helps ensure the transition plays correctly on the first open
        modal.offsetHeight;
        // Add the active class to trigger the animation
        modal.classList.add('modal-active');
        // --- End Animate In ---
    }

    // Function to close the modal
    function closeModal() {
        // modal.style.display = 'none';
        modal.classList.remove('modal-active');
    }

    // Event Listeners for Stats Modal
    if (statsBtn) {
        statsBtn.addEventListener('click', function() {
            // Add busy cursor while calculating
            document.documentElement.classList.add('busyCursor');
            // Use setTimeout to allow cursor change to render
            setTimeout(() => {
                displayStats();
                document.documentElement.classList.remove('busyCursor');
            }, 10);
        });
    }

    if (spanClose) {
        spanClose.addEventListener('click', closeModal);
    }

    // Close modal if user clicks outside the modal content
    window.addEventListener('click', function(event) {
        if (event.target === modal) {
            closeModal();
        }
    });
    // --- End Stats Modal Functionality ---

        // Helper function to check if fullscreen is active
    function isFullscreen() {
        return !!(document.fullscreenElement /* Standard syntax */
            || document.webkitFullscreenElement /* WebKit */
            || document.mozFullScreenElement /* Mozilla */
            || document.msFullscreenElement /* IE11 */);
    }

    // Helper function to request fullscreen
    function requestFullscreen(element) {
        if (element.requestFullscreen) {
            element.requestFullscreen();
        } else if (element.webkitRequestFullscreen) { /* Safari */
            element.webkitRequestFullscreen();
        } else if (element.mozRequestFullScreen) { /* Mozilla */
            element.mozRequestFullScreen();
        } else if (element.msRequestFullscreen) { /* IE11 */
            element.msRequestFullscreen();
        }
    }

    // Helper function to exit fullscreen
    function exitFullscreen() {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        } else if (document.webkitExitFullscreen) { /* Safari */
            document.webkitExitFullscreen();
        } else if (document.mozCancelFullScreen) { /* Mozilla */
            document.mozCancelFullScreen();
        } else if (document.msExitFullscreen) { /* IE11 */
            document.msExitFullscreen();
        }
    }

    // Update button text based on state
    function updateFullscreenButton() {
        const span = fullscreenBtn.querySelector('span');
        if (span) {
            span.textContent = isFullscreen() ? '⇱' : '⇲'; // Toggle arrow characters
        }
    }

    // Listen for fullscreen change events to update the button
    document.addEventListener('fullscreenchange', updateFullscreenButton);
    document.addEventListener('webkitfullscreenchange', updateFullscreenButton); // Safari
    document.addEventListener('mozfullscreenchange', updateFullscreenButton);    // Mozilla
    document.addEventListener('MSFullscreenChange', updateFullscreenButton);     // IE11

    // Add click event listener to the button
    fullscreenBtn.addEventListener('click', function () {
        if (isFullscreen()) {
            exitFullscreen();
        } else {
            // Request fullscreen for the entire document element
            requestFullscreen(document.documentElement);
        }
        // Update button immediately after click, before the async fullscreen change event
        updateFullscreenButton();
    });

    // Initialize button text on page load
    updateFullscreenButton();
});