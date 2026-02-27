// static/filtering.js
/** This file contains client-side filtering code, shared between server-based full page and client-only HTML export.
 */

// Hardocoded cells - used for multiple scripts:
const pdfCellIndex = 0;
const titleCellIndex = 1;
const yearCellIndex = 2;
const pageCountCellIndex = 3;
const journalCellIndex = 4;
const typeCellIndex = 5;
const relevanceCellIndex = 7;
const estScoreCellIndex = 38;
const userOverrideCountCellIndex = 39; // Adjust based on final column position

const searchInput = document.getElementById('search-input');
const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
const hideXrayCheckbox = document.getElementById('hide-xray-checkbox');
const hideApprovedCheckbox = document.getElementById('hide-approved-checkbox');
const onlySurveyCheckbox = document.getElementById('only-survey-checkbox');
const showPCBcheckbox = document.getElementById('show-pcb-checkbox');
const showSolderCheckbox = document.getElementById('show-solder-checkbox');
const showPCBAcheckbox = document.getElementById('show-pcba-checkbox');
const noFeaturesCheckbox = document.getElementById('no-features-checkbox');
const showOtherCheckbox = document.getElementById('show-other-checkbox');

let filterTimeoutId = null;
const FILTER_DEBOUNCE_DELAY = 250;
const MAX_STORED_OPEN_DETAILS = 10;

const headers = document.querySelectorAll('th[data-sort]');
let currentClientSort = { column: null, direction: 'ASC' };

// Pre-compiled regular expressions for search (if needed)
let searchRegex = null;
let searchTerms = [];

const SYMBOL_SORT_WEIGHTS = {
    '✔️': 2,
    '❌': 1,
    '❔': 0
};

const SYMBOL_PDF_WEIGHTS = {
    '📗': 3, // Annotated
    '📕': 2, // PDF
    '❔': 1,  // None
    '💰': 0 // Paywalled
};

// Define weights for 'verified_by' symbols specifically
// Using the values from comms.js VERIFIED_BY_CYCLE logic or a direct mapping
// Assuming 👤 (User) > ❔ (Unverified) > 🖥️ (Model) based on typical verification status priority
// Adjust the numbers if a different priority is desired.
const VERIFIED_BY_SORT_WEIGHTS = {
    '👤': 2, // User
    '❔': 1, // Unverified (or Unknown)
    '🖥️': 0  // Model (Computer)
};

// Cache frequently accessed elements
const tbody = document.querySelector('#papersTable tbody');
const duplicateCountElement = document.getElementById('duplicate-papers-count');

// Add the WeakMap for caching row data
const rowCache = new WeakMap();
/**
 * Applies alternating row shading to visible main rows.
 * Ensures detail rows AND history rows follow their main row's shading.
 * Each "paper group" (main row + detail row + history row) gets a single alternating color.
 * Should be pure client-side to be reused for HTML export
 */
function applyAlternatingShading() {
    // Use CSS classes to avoid inline style recalculation where possible
    const rows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
    let idx = 0;
    for (const main of rows) {
        const shade = (idx & 1) ? 'alt-shade-2' : 'alt-shade-1';
        main.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
        main.classList.toggle('alt-shade-2', shade === 'alt-shade-2');

        // Apply same shading to detail row if it exists
        const detail = main.nextElementSibling;
        if (detail && detail.classList.contains('detail-row')) {
            detail.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
            detail.classList.toggle('alt-shade-2', shade === 'alt-shade-2');
        }
        
        // Apply same shading to history row if it exists (second sibling after main)
        const history = detail && detail.nextElementSibling;
        if (history && history.classList.contains('history-row')) {
            history.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
            history.classList.toggle('alt-shade-2', shade === 'alt-shade-2');
        }
        idx++;
    }
}
/**
 * Optimized duplicate shading using cached data and batch operations
 */
// Corrected version assuming 'rows' passed are the visible ones:
/**
 * Optimized duplicate shading using cached data and batch operations
 * @param {NodeList} visibleRows - The list of rows currently visible after filtering.
 */
function applyDuplicateShading(visibleRows) {
    // Use the rows parameter passed from applyLocalFilters
    const journalCounts = new Map();
    const titleCounts = new Map();

    // Count occurrences for both journal names and titles from visible rows
    for (let i = 0; i < visibleRows.length; i++) {
        const row = visibleRows[i];
        // Use rowCache.get(row) instead of row._cachedData
        const cachedData = rowCache.get(row);
        if (cachedData) { // Ensure cache exists for this row
            const journalName = cachedData.journalText;
            const title = cachedData.titleText;

            if (journalName) {
                journalCounts.set(journalName, (journalCounts.get(journalName) || 0) + 1);
            }
            if (title) {
                titleCounts.set(title, (titleCounts.get(title) || 0) + 1);
            }
        }
    }

    // Count duplicate titles (only titles with 2 or more occurrences)
    let duplicateTitleCount = 0;
    for (const [title, count] of titleCounts) {
        if (title && count >= 2) {
            duplicateTitleCount++;
        }
    }

    // Update the duplicate papers count in HTML
    if (duplicateCountElement) {
        duplicateCountElement.textContent = duplicateTitleCount;
    }

    // Determine the maximum count for scaling (for journals only)
    let maxCount = 0;
    for (const count of journalCounts.values()) {
        if (count > maxCount) maxCount = count;
    }

    // Pre-calculate HSL strings to avoid repeated string operations
    const baseJournalHue = 210;
    const baseSaturation = 66;
    const minLightness = 96;
    const maxLightness = 84;

    const baseTitleHue = 0;
    const titleSaturation = 66;
    const titleLightness = 94;

    // Pre-calculate HSL strings for journals
    const journalHslStrings = new Map();
    for (const [journalName, count] of journalCounts) {
        if (count >= 2) {
            let lightness;
            if (maxCount <= 1) {
                lightness = minLightness;
            } else {
                lightness = maxLightness + (minLightness - maxLightness) * (1 - (count - 1) / (maxCount - 1));
                lightness = Math.max(maxLightness, Math.min(minLightness, lightness));
            }
            journalHslStrings.set(journalName, `hsl(${baseJournalHue}, ${baseSaturation}%, ${lightness}%)`);
        }
    }

    // Pre-calculate HSL string for titles
    const duplicateTitleHslString = `hsl(${baseTitleHue}, ${titleSaturation}%, ${titleLightness}%)`;

    // Apply shading in a single pass
    for (let i = 0; i < visibleRows.length; i++) {
        const row = visibleRows[i];
        const journalCell = row.cells[journalCellIndex];
        const titleCell = row.cells[titleCellIndex];

        // Reset background colors
        journalCell.style.backgroundColor = '';
        titleCell.style.backgroundColor = '';

        // Use rowCache.get(row) to get cached data
        const cachedData = rowCache.get(row);
        if (cachedData) { // Ensure cache exists
            const journalName = cachedData.journalText;
            const title = cachedData.titleText;

            // Apply journal shading (progressive)
            if (journalName && journalCounts.get(journalName) >= 2) {
                journalCell.style.backgroundColor = journalHslStrings.get(journalName);
            }

            // Apply title shading (consistent red for duplicates)
            if (title && titleCounts.get(title) >= 2) {
                titleCell.style.backgroundColor = duplicateTitleHslString;
            }
        }
    }
}
// --- Tri-State Survey Filter Logic (Add to globals.js) ---
// Define the states for the survey filter
const SURVEY_FILTER_STATES = {
    ALL: 'all',           // Default: Show all papers
    ONLY_SURVEYS: 'surveys', // Show only papers marked as surveys (✔️)
    ONLY_NON_SURVEYS: 'non_surveys' // Show only papers NOT marked as surveys (❌ or ❔)
};

// Store the current state of the survey filter
let currentSurveyFilterState = SURVEY_FILTER_STATES.ONLY_NON_SURVEYS; 

// Function to cycle the checkbox's visual state and update the title
function updateSurveyCheckboxUI() {
    const checkbox = onlySurveyCheckbox; // Reference from your globals
    const state = currentSurveyFilterState;

    // Remove any previous tri-state classes (if you add custom styling)
    checkbox.classList.remove('tri-state-indeterminate'); // Example class

    switch (state) {
        case SURVEY_FILTER_STATES.ALL:
            checkbox.checked = false;
            checkbox.indeterminate = false; // Ensure indeterminate is off
            checkbox.title = 'Currently showing all papers. Click to show only Survey papers';
            break;
        case SURVEY_FILTER_STATES.ONLY_SURVEYS:
            checkbox.checked = true; // Visually checked
            checkbox.indeterminate = false;
            checkbox.title = 'Currently showing only Surveys. Click to show only primary (non-survey) papers';
            break;
        case SURVEY_FILTER_STATES.ONLY_NON_SURVEYS:
            checkbox.checked = false; // Visually unchecked
            checkbox.indeterminate = true; // Use indeterminate to show the third state
            checkbox.title = 'Currently showing only primary (non-survey) papers. Click to show All papers';
            break;
    }
}

// Function to cycle the filter state on click
function cycleSurveyFilterState() {
    switch (currentSurveyFilterState) {
        case SURVEY_FILTER_STATES.ALL:
            currentSurveyFilterState = SURVEY_FILTER_STATES.ONLY_SURVEYS;
            break;
        case SURVEY_FILTER_STATES.ONLY_SURVEYS:
            currentSurveyFilterState = SURVEY_FILTER_STATES.ONLY_NON_SURVEYS;
            break;
        case SURVEY_FILTER_STATES.ONLY_NON_SURVEYS:
            currentSurveyFilterState = SURVEY_FILTER_STATES.ALL;
            break;
    }
    updateSurveyCheckboxUI();
    applyLocalFilters(); // Re-apply filters after state change
}

// Pre-calculate feature groups for faster lookups
const FEATURE_GROUPS = {
    pcb: ['features_tracks', 'features_holes', 'features_bare_pcb_other'],
    solder: [
        'features_solder_insufficient',
        'features_solder_excess',
        'features_solder_void',
        'features_solder_crack',
        'features_solder_other'
    ],
    pcba: [
        'features_orientation',
        'features_missing_component',
        'features_wrong_component',
        'features_component_other',
        'features_cosmetic',
    ],
    other: ['features_other_state']
};

// Combine all feature fields into a single array for efficient iteration
const ALL_FEATURE_FIELDS = [
    ...FEATURE_GROUPS.pcb,
    ...FEATURE_GROUPS.solder,
    ...FEATURE_GROUPS.pcba,
    ...FEATURE_GROUPS.other
];

// Pre-compiled regex for search terms (if using regex search)
function compileSearchRegex(searchTerm) {
    if (!searchTerm) return null;
    const terms = searchTerm.split(/\s+/).filter(t => t.length > 0);
    searchTerms = terms.map(t => t.toLowerCase());
    return new RegExp(searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
}

// Update getClientFilterState to include sort parameters
function getClientFilterState() {
    return {
        hide_xray: hideXrayCheckbox.checked ? 1 : 0,
        hide_approved: hideApprovedCheckbox.checked ? 1 : 0,
        hide_offtopic: hideOfftopicCheckbox.checked ? 1 : 0,
        survey_filter: currentSurveyFilterState,
        show_pcb: showPCBcheckbox.checked ? 1 : 0,
        show_solder: showSolderCheckbox.checked ? 1 : 0,
        show_pcba: showPCBAcheckbox.checked ? 1 : 0,
        show_other: showOtherCheckbox.checked ? 1 : 0,
        no_features: noFeaturesCheckbox.checked ? 1 : 0,
        search: searchInput.value.trim(),
        sort_by: currentClientSort.column || '',
        sort_dir: currentClientSort.direction || 'ASC'
    };
}


let urlUpdateTimeout;
function updateUrlWithClientFilters() {
    clearTimeout(urlUpdateTimeout);
    urlUpdateTimeout = setTimeout(() => {
        const url = new URL(window.location);
        const clientFilters = getClientFilterState();

        for (const [key, value] of Object.entries(clientFilters)) {
            // Always include everything: '1', '0', 'all', search string, etc.
            // This is important because some checkboxes are default on, other default off, etc.
            url.searchParams.set(key, String(value));
        }

        window.history.replaceState({}, '', url);
    }, 100);
}



let rafId = 0;
let currentFilterAbortController = null;

function applyLocalFilters() {
    // Cancel any ongoing filter operation
    if (currentFilterAbortController) {
        currentFilterAbortController.abort();
    }
    
    // Create a new abort controller for this operation
    currentFilterAbortController = new AbortController();
    const signal = currentFilterAbortController.signal;

    clearTimeout(filterTimeoutId);
    document.documentElement.classList.add('busyCursor');
    cancelAnimationFrame(rafId);
    filterTimeoutId = setTimeout(() => {
        // Check if operation was cancelled
        if (signal.aborted) return;

        // --- Pre-cache data for all rows to avoid repeated DOM queries ---
        const rows = tbody.querySelectorAll('tr[data-paper-id]');
        
        // Pre-calculate filter values outside the loop
        const hideXrayChecked = hideXrayCheckbox.checked;
        const hideApprovedChecked = hideApprovedCheckbox.checked;
        const showPCBChecked = showPCBcheckbox.checked;
        const showSolderChecked = showSolderCheckbox.checked;
        const showPCBAChecked = showPCBAcheckbox.checked;
        const showOtherChecked = showOtherCheckbox.checked;
        const showNoFeaturesChecked = noFeaturesCheckbox.checked;
        const hideOfftopicChecked = document.body.id === 'html-export' ? hideOfftopicCheckbox.checked : false;
        const minPageCountValue = document.body.id === 'html-export' ? (document.getElementById('min-page-count').value.trim() || 0) : 0;
        const yearFromValue = document.body.id === 'html-export' ? (document.getElementById('year-from').value.trim() || 0) : 0;
        const yearToValue = document.body.id === 'html-export' ? (document.getElementById('year-to').value.trim() || 0) : 0;
        const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const compiledSearchRegex = compileSearchRegex(searchTerm);

        // --- Cache data for all rows in a single pass ---
        for (let i = 0; i < rows.length; i++) {
            // Check if operation was cancelled during the loop
            if (signal.aborted) return;
            
            const row = rows[i];
            // Cache status cells
            const surveyCell = row.querySelector('.editable-status[data-field="is_survey"]');
            const xrayCell = row.querySelector('.editable-status[data-field="is_x_ray"]');
            const verifiedCell = row.querySelector('.editable-status[data-field="verified"]');
            const offtopicCell = row.querySelector('.editable-status[data-field="is_offtopic"]');

            // Cache feature cell values
            const featureValues = {};
            for (let j = 0; j < ALL_FEATURE_FIELDS.length; j++) {
                // Check if operation was cancelled during the loop
                if (signal.aborted) return;
                
                const fieldName = ALL_FEATURE_FIELDS[j];
                const cell = row.querySelector(`[data-field="${fieldName}"]`);
                featureValues[fieldName] = cell ? cell.textContent.trim() : '';
            }

            // Determine group membership based on cached feature values
            let hasPCBFeature = false;
            for (let j = 0; j < FEATURE_GROUPS.pcb.length; j++) {
                // Check if operation was cancelled during the loop
                if (signal.aborted) return;
                
                if (featureValues[FEATURE_GROUPS.pcb[j]] === '✔️') {
                    hasPCBFeature = true;
                    break;
                }
            }

            let hasSolderFeature = false;
            for (let j = 0; j < FEATURE_GROUPS.solder.length; j++) {
                // Check if operation was cancelled during the loop
                if (signal.aborted) return;
                
                if (featureValues[FEATURE_GROUPS.solder[j]] === '✔️') {
                    hasSolderFeature = true;
                    break;
                }
            }

            let hasPCBAFeature = false;
            for (let j = 0; j < FEATURE_GROUPS.pcba.length; j++) {
                // Check if operation was cancelled during the loop
                if (signal.aborted) return;
                
                if (featureValues[FEATURE_GROUPS.pcba[j]] === '✔️') {
                    hasPCBAFeature = true;
                    break;
                }
            }

            let hasOtherFeature = false;
            for (let j = 0; j < FEATURE_GROUPS.other.length; j++) {
                // Check if operation was cancelled during the loop
                if (signal.aborted) return;
                
                if (featureValues[FEATURE_GROUPS.other[j]] === '✔️') {
                    hasOtherFeature = true;
                    break;
                }
            }

            // Cache hidden data text
            let hiddenDataText = '';
            const hiddenDataCells = row.querySelectorAll('td.hidden-data-cell');
            for (let j = 0; j < hiddenDataCells.length; j++) {
                // Check if operation was cancelled during the loop
                if (signal.aborted) return;
                
                hiddenDataText += ' ' + (hiddenDataCells[j].textContent || '').toLowerCase();
            }

            // Cache main row text content (excluding hidden data cells) and the paper ID
            let visibleRowText = '';
            // Include the paper ID in the searchable text
            const paperId = row.getAttribute('data-paper-id'); // Get the paper ID
            if (paperId) {
                visibleRowText += ' ' + paperId.toLowerCase(); // Add it to the searchable text
            }
            for (let j = 0; j < row.cells.length; j++) {
                // Check if operation was cancelled during the loop
                if (signal.aborted) return;
                if (!row.cells[j].classList.contains('hidden-data-cell')) {
                    visibleRowText += ' ' + row.cells[j].textContent.toLowerCase();
                }
            }


            // Cache frequently accessed text values
            const journalText = row.cells[journalCellIndex]?.textContent?.trim().toLowerCase() || '';
            const titleText = row.cells[titleCellIndex]?.textContent?.trim().toLowerCase() || '';

            // Store all cached data in the WeakMap using the row element as the key
            rowCache.set(row, {
                surveyStatus: surveyCell ? surveyCell.textContent.trim() : '❔',
                xrayStatus: xrayCell ? xrayCell.textContent.trim() : 'N/A',
                verifiedStatus: verifiedCell ? verifiedCell.textContent.trim() : 'N/A',
                offtopicStatus: offtopicCell ? offtopicCell.textContent.trim() : 'N/A',
                featureValues: featureValues,
                hasPCBFeature,
                hasSolderFeature,
                hasPCBAFeature,
                hasOtherFeature,
                hiddenDataText,
                visibleRowText,
                journalText,
                titleText,
                pageCount: row.cells[pageCountCellIndex]?.textContent?.trim() || '',
                year: row.cells[yearCellIndex]?.textContent?.trim() || ''
            });
        }

        /* ---------- 1.  shared batch containers ---------- */
        const toHide = [];
        const toShow = [];

        /* ---------- 2.  single walk over every <tr> using cached data ---------- */
        for (let i = 0; i < rows.length; i++) {
            // Check if operation was cancelled during the loop
            if (signal.aborted) return;
            
            const row = rows[i];
            // Get cached data from the WeakMap
            const cachedData = rowCache.get(row);

            let showRow = true;

            /* ----------------------------------------------------
                2a.  HTML-export-only filters
            ---------------------------------------------------- */
            if (document.body.id === 'html-export') {
                if (showRow && hideOfftopicChecked) {
                    if (cachedData.offtopicStatus === '✔️') {
                        showRow = false;
                    }
                }

                if (showRow && minPageCountValue > 0) {
                    const pageCount = parseInt(cachedData.pageCount, 10);
                    if (!isNaN(pageCount) && pageCount < minPageCountValue) {
                        showRow = false;
                    }
                }

                if (showRow && (yearFromValue || yearToValue)) {
                    const year = cachedData.year ? parseInt(cachedData.year, 10) : NaN;
                    if (isNaN(year) || (yearFromValue && year < yearFromValue) || (yearToValue && year > yearToValue)) {
                        showRow = false;
                    }
                }
            }

            /* ----------------------------------------------------
                2b.  universal filters (search, survey, X-ray, …)
            ---------------------------------------------------- */
            // Search Term
            if (showRow && searchTerm) {
                // Fast string inclusion check first
                if (!cachedData.visibleRowText.includes(searchTerm) && !cachedData.hiddenDataText.includes(searchTerm)) {
                    showRow = false;
                }

                // If still showing, do more complex search if needed
                if (showRow && compiledSearchRegex) {
                    // Additional regex or multi-term checks if needed
                }
            }

            // Apply the tri-state survey filter logic
            if (showRow) {
                const surveyStatus = cachedData.surveyStatus;

                switch (currentSurveyFilterState) {
                    case SURVEY_FILTER_STATES.ONLY_SURVEYS:
                        if (surveyStatus !== '✔️') {
                            showRow = false;
                        }
                        break;
                    case SURVEY_FILTER_STATES.ONLY_NON_SURVEYS:
                        if (surveyStatus === '✔️') {
                            showRow = false;
                        }
                        break;
                    // For SURVEY_FILTER_STATES.ALL, showRow remains unchanged (default)
                }
            }

            // Existing filters (X-Ray, Survey, Approved)
            if (showRow && hideXrayChecked) {
                if (cachedData.xrayStatus === '✔️') {
                    showRow = false;
                }
            }
            if (showRow && hideApprovedChecked) {
                if (cachedData.verifiedStatus === '✔️') {
                    showRow = false;
                }
            }

            // --- Feature Group Filters ---
            if (showRow && (showPCBChecked || showSolderChecked || showPCBAChecked || showOtherChecked)) {
                if (!( (showPCBChecked && cachedData.hasPCBFeature) ||
                        (showSolderChecked && cachedData.hasSolderFeature) ||
                        (showPCBAChecked && cachedData.hasPCBAFeature) ||
                        (showOtherChecked && cachedData.hasOtherFeature) )) {
                    showRow = false;
                }
            }

            // --- "No Features" Filter ---
            if (showRow && showNoFeaturesChecked) {
                let hasAnyFeatureFilled = false;
                for (let j = 0; j < ALL_FEATURE_FIELDS.length; j++) {
                    const cellText = cachedData.featureValues[ALL_FEATURE_FIELDS[j]];
                    if (cellText !== '' && cellText !== '❌' && cellText !== '❔') {
                        hasAnyFeatureFilled = true;
                        break;
                    }
                }

                if (hasAnyFeatureFilled) {
                    showRow = false;
                }
            }

            /* ----------------------------------------------------
                2c.  queue the visibility change (no DOM touch yet)
            ---------------------------------------------------- */
            const detailRow = row.nextElementSibling;
            const hide = !showRow;

            if (row.classList.contains('filter-hidden') !== hide) {
                (hide ? toHide : toShow).push(row);
            }
            if (detailRow && detailRow.classList.contains('filter-hidden') !== hide) {
                (hide ? toHide : toShow).push(detailRow);
            }
        }

        /* ---------- 3.  one RAF to flush all changes ---------- */
        // Batch DOM operations
        for (let i = 0; i < toHide.length; i++) {
            // Check if operation was cancelled during the loop
            if (signal.aborted) return;
            
            toHide[i].classList.add('filter-hidden');
        }
        for (let i = 0; i < toShow.length; i++) {
            // Check if operation was cancelled during the loop
            if (signal.aborted) return;
            
            toShow[i].classList.remove('filter-hidden');
        }

        rafId = requestAnimationFrame(() => {
            if (signal.aborted) return;
            

            if (document.body.id !== 'html-export') {
                const visibleRows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
                applyDuplicateShading(visibleRows);
                const applyButton = document.getElementById('apply-serverside-filters');
                applyButton.style.opacity = '0';
                applyButton.style.pointerEvents = 'none';
            }
            // Apply the current sort after filtering
            if (currentClientSort.column) {
                performSort(currentClientSort.column, currentClientSort.direction);
            }
            updateUrlWithClientFilters();
            applyAlternatingShading();
            updateCounts();
            restoreDetailState(); // Call the new function to open rows based on the set and current DOM state

            document.documentElement.classList.remove('busyCursor');

            // Clean up the abort controller when operation completes successfully
            if (currentFilterAbortController?.signal === signal) {
                currentFilterAbortController = null;
            }
        });
    }, FILTER_DEBOUNCE_DELAY);
}

// Pre-calculate sort column indices for faster lookups
const SORT_COLUMN_INDICES = {
    'title': titleCellIndex,
    'year': yearCellIndex,
    'journal': journalCellIndex,
    'page_count': pageCountCellIndex,
    'estimated_score': estScoreCellIndex,
    'relevance': relevanceCellIndex,
    'pdf-link': pdfCellIndex,
    'user_override_count': userOverrideCountCellIndex,
};

// Define fields that do NOT use the .editable-status selector for sorting
// These will be sorted using their direct cell text content, but still potentially using SYMBOL_SORT_WEIGHTS if they contain symbols.
const NON_EDITABLE_STATUS_FIELDS = new Set([
    'user_comment_state', // Commented
    'features_other_state', // Other (Features)
    'type'                // Type
    // Add other non-editable status fields here if any are discovered later
    // e.g., 'some_other_field_name'
]);

// ... (Keep all other functions and variables the same until performSort)

function performSort(sortBy, direction, visibleMainRows = null) { // Changed parameter name for clarity
    if (!sortBy) return;

    // Use provided visible main rows or get them from DOM
    // This function now expects an array of MAIN rows only.
    const mainRowsToSort = visibleMainRows || Array.from(tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)'));

    if (mainRowsToSort.length === 0) return;

    // Calculate the header index based on the sort column
    const sortHeader = document.querySelector(`th[data-sort="${sortBy}"]`);
    if (!sortHeader) return;
    const headerIndex = Array.prototype.indexOf.call(sortHeader.parentNode.children, sortHeader);

    // Pre-calculate sort type to avoid repeated checks inside the loop
    const isDateSort = sortBy === 'changed';
    const isNumericSort = ['year', 'estimated_score', 'page_count', 'relevance', 'user_override_count'].includes(sortBy);    
    const isPDFSort = sortBy === 'pdf-link';
    const isVerifiedBySort = sortBy === 'verified_by';
    const isEditableStatusSort = !isNumericSort && !isPDFSort && !isVerifiedBySort && !NON_EDITABLE_STATUS_FIELDS.has(sortBy) && !['title', 'journal', 'changed_by', 'changed'].includes(sortBy);

    // Prepare an array of objects containing sort value and the group of rows (main, detail, history)
    const sortData = mainRowsToSort.map(mainRow => {
        let cellValue;

        if (isDateSort) {
            const cell = mainRow.cells[headerIndex];
            const cellText = cell ? cell.textContent.trim() : '';
            const dateMatch = cellText.match(/(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
            if (dateMatch) {
                const [, day, month, year, hour, minute, second] = dateMatch;
                cellValue = new Date(2000 + parseInt(year), parseInt(month) - 1, parseInt(day), parseInt(hour), parseInt(minute), parseInt(second));
            } else {
                console.warn(`Invalid date format for sorting: ${cellText}`);
                cellValue = new Date(NaN);
            }
        } else if (isNumericSort) {
            const cell = mainRow.cells[headerIndex];
            cellValue = cell ? parseFloat(cell.textContent.trim()) || 0 : 0;
        } else if (isPDFSort) {
            const cell = mainRow.cells[headerIndex];
            cellValue = SYMBOL_PDF_WEIGHTS[cell?.textContent.trim()] ?? 0;
        } else if (isVerifiedBySort) {
            const cell = mainRow.querySelector(`.editable-verify[data-field="${sortBy}"]`);
            const symbolText = cell?.querySelector('span')?.textContent?.trim() || '';
            cellValue = VERIFIED_BY_SORT_WEIGHTS[symbolText] ?? 0;
        } else if (isEditableStatusSort) {
            const cell = mainRow.querySelector(`.editable-status[data-field="${sortBy}"]`);
            cellValue = SYMBOL_SORT_WEIGHTS[cell?.textContent.trim()] ?? 0;
        } else {
            const cell = mainRow.cells[headerIndex];
            const cellText = cell ? cell.textContent.trim() : '';
            if (sortBy === 'type') {
                cellValue = cellText;
            } else if (NON_EDITABLE_STATUS_FIELDS.has(sortBy)) {
                cellValue = SYMBOL_SORT_WEIGHTS[cellText] ?? 0;
            } else {
                cellValue = cellText;
            }
        }

        // Identify associated detail and history rows
        const detailRow = mainRow.nextElementSibling && mainRow.nextElementSibling.classList.contains('detail-row') ? mainRow.nextElementSibling : null;
        const historyRow = detailRow && detailRow.nextElementSibling && detailRow.nextElementSibling.classList.contains('history-row') ? detailRow.nextElementSibling : null;

        // Collect the group of rows belonging to this main row
        const rowGroup = [mainRow];
        if (detailRow) rowGroup.push(detailRow);
        if (historyRow) rowGroup.push(historyRow);

        const paperId = mainRow.getAttribute('data-paper-id');

        return { value: cellValue, rowGroup, paperId };
    });

    // Sort the data array based on the calculated sort value
    sortData.sort((a, b) => {
        let comparison = 0;
        const aValue = a.value;
        const bValue = b.value;

        if (aValue instanceof Date && bValue instanceof Date) {
            if (isNaN(aValue)) {
                if (isNaN(bValue)) {
                    comparison = 0;
                } else {
                    comparison = 1;
                }
            } else if (isNaN(bValue)) {
                comparison = -1;
            } else {
                comparison = aValue - bValue;
            }
        } else if (typeof aValue === 'string' && typeof bValue === 'string') {
            comparison = aValue.localeCompare(bValue, undefined, { sensitivity: 'base' });
        } else {
            if (aValue > bValue) comparison = 1;
            else if (aValue < bValue) comparison = -1;
        }

        // Secondary sort by paperId for stability
        if (comparison === 0) {
            if (a.paperId > b.paperId) comparison = 1;
            else if (a.paperId < b.paperId) comparison = -1;
        }

        return direction === 'DESC' ? -comparison : comparison;
    });

    // Batch update the DOM by appending the sorted groups
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < sortData.length; i++) {
        const group = sortData[i].rowGroup;
        for (let j = 0; j < group.length; j++) {
            fragment.appendChild(group[j]); // Append main, then detail, then history if they exist
        }
    }
    tbody.appendChild(fragment); // Single DOM append operation for the entire sorted structure

    // Update the sort indicator
    document.querySelectorAll('th .sort-indicator').forEach(ind => ind.textContent = '');
    const indicator = sortHeader.querySelector('.sort-indicator');
    if (indicator) {
        indicator.textContent = direction === 'ASC' ? '▲' : '▼';
    }
}

function sortTable() {
    //console.log("sortTable called for column:", this.getAttribute('data-sort'));
    document.documentElement.classList.add('busyCursor');
    
    setTimeout(() => {
        const sortBy = this.getAttribute('data-sort');
        if (!sortBy) return;

        let newDirection = 'DESC';
        if (currentClientSort.column === sortBy) {
            newDirection = currentClientSort.direction === 'DESC' ? 'ASC' : 'DESC';
        }
        currentClientSort = { column: sortBy, direction: newDirection };

        // Perform the sort immediately on current visible rows
        performSort(sortBy, currentClientSort.direction);
        
        // Then apply the same UI updates that happen in the filtering flow
        requestAnimationFrame(() => {
            if (document.body.id !== 'html-export') {
                const visibleRows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
                applyDuplicateShading(visibleRows);
            }
            updateUrlWithClientFilters();
            applyAlternatingShading();
            document.documentElement.classList.remove('busyCursor');
        });
    }, 50);
}


// --- Add F3 Shortcut ---
document.addEventListener('keydown', function(event) {
    if (event.key === 'F3') {
        event.preventDefault();
        searchInput.focus();
    }
});

function initializeClientFilters() {
    const urlParams = new URLSearchParams(window.location.search);
    
    // For each checkbox, if there's a URL parameter, use it to set the state
    // Otherwise, keep the existing DOM state
    const checkboxParams = {
        'hide_xray': hideXrayCheckbox,
        'hide_approved': hideApprovedCheckbox,
        'hide_offtopic': hideOfftopicCheckbox,
        'show_pcb': showPCBcheckbox,
        'show_solder': showSolderCheckbox,
        'show_pcba': showPCBAcheckbox,
        'show_other': showOtherCheckbox,
        'no_features': noFeaturesCheckbox
    };

    for (const [param, checkbox] of Object.entries(checkboxParams)) {
        const paramValue = urlParams.get(param);
        if (paramValue !== null) {
            checkbox.checked = paramValue === '1';
        }
    }
    
    // Handle search input
    const searchValueFromUrl = urlParams.get('search');
    if (searchValueFromUrl !== null) {
        searchInput.value = searchValueFromUrl;
    }


    // Handle open detail IDs from URL
    const openDetailsParam = urlParams.get('open_details');
    if (openDetailsParam) {
        const initialOpenIds = openDetailsParam.split(',').map(id => id.trim()).filter(id => id !== '');
        // Limit and populate the set
        openDetailIds = new Set(initialOpenIds.slice(0, MAX_STORED_OPEN_DETAILS));
        //console.log("Initialized openDetailIds from URL:", [...openDetailIds]); // Debug log
    } else {
        // Ensure the set is initialized as empty if no param
        openDetailIds = new Set();
    }

    const openHistoryParam = urlParams.get('open_history');
    if (openHistoryParam) {
        const initialOpenHistoryIds = openHistoryParam.split(',').map(id => id.trim()).filter(id => id !== '');
        openHistoryIds = new Set(initialOpenHistoryIds.slice(0, MAX_STORED_OPEN_DETAILS)); // Reuse MAX_STORED_OPEN_DETAILS or define a specific one for history if needed
        //console.log("Initialized openHistoryIds from URL:", [...openHistoryIds]); // Debug log
    } else {
        openHistoryIds = new Set();
    }

    // Handle survey filter state
    const surveyFilterValue = urlParams.get('survey_filter');
    if (surveyFilterValue) {
        currentSurveyFilterState = surveyFilterValue;
    }
    
    // Handle sort parameters - only set if they exist in URL
    const sortColumnFromUrl = urlParams.get('sort_by');
    const sortDirectionFromUrl = urlParams.get('sort_dir');
    
    if (sortColumnFromUrl) {
        currentClientSort = {
            column: sortColumnFromUrl,
            direction: sortDirectionFromUrl === 'DESC' ? 'DESC' : 'ASC'
        };
        
        // Update the sort indicator in the UI
        const sortHeader = document.querySelector(`th[data-sort="${currentClientSort.column}"]`);
        if (sortHeader) {
            const indicator = sortHeader.querySelector('.sort-indicator');
            if (indicator) {
                indicator.textContent = currentClientSort.direction === 'ASC' ? '▲' : '▼';
            }
        }
    } else {
        // If no sort parameters in URL, reset to null state (no sort applied)
        currentClientSort = { column: null, direction: 'ASC' };
    }
    
    
    updateSurveyCheckboxUI();
    
    // Update URL to reflect initial state (this ensures the URL is clean and consistent)
    updateUrlWithClientFilters();
}

let openDetailIds = new Set();
let openHistoryIds = new Set();
const openRowTypes = new Map(); // Tracks 'details' or 'history' for each paperId

let detailStateUpdateTimeout = null;
function updateUrlWithDetailState() {
    clearTimeout(detailStateUpdateTimeout);
    detailStateUpdateTimeout = setTimeout(() => {
        const url = new URL(window.location);

        // --- Handle open detail IDs ---
        const sortedDetailIds = [...openDetailIds].sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).slice(0, MAX_STORED_OPEN_DETAILS); // Sort numerically if IDs are numbers, otherwise use string sort
        if (sortedDetailIds.length > 0) {
            url.searchParams.set('open_details', sortedDetailIds.join(','));
        } else {
            url.searchParams.delete('open_details');
        }

        // --- Handle open history IDs ---
        const sortedHistoryIds = [...openHistoryIds].sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).slice(0, MAX_STORED_OPEN_DETAILS); // Sort numerically if IDs are numbers, otherwise use string sort
        if (sortedHistoryIds.length > 0) {
            url.searchParams.set('open_history', sortedHistoryIds.join(','));
        } else {
            url.searchParams.delete('open_history');
        }

        // Use replaceState to avoid adding history entries
        window.history.replaceState({}, '', url);
        //console.log("URL updated with open detail IDs:", sortedDetailIds, "and history IDs:", sortedHistoryIds); // Debug log
    }, 100); // Debounce delay
}

function restoreDetailState() {
    //console.log("Starting restoreDetailState. Intended open detail IDs:", [...openDetailIds], "Intended open history IDs:", [...openHistoryIds]); // Debug log

    // --- PHASE 1: Restore Detail Rows ---
    const idsToOpenDetails = [...openDetailIds];
    idsToOpenDetails.forEach(paperId => {
        const mainRow = document.querySelector(`tr[data-paper-id="${paperId}"]:not(.filter-hidden)`);
        if (mainRow) {
            const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleDetails"]'); // Target the specific detail toggle button
            if (toggleButton) {
                const detailRow = mainRow.nextElementSibling; // detail-row is the immediate next sibling
                const isCurrentlyExpanded = detailRow && detailRow.classList.contains('expanded');
                if (!isCurrentlyExpanded) {
                    //console.log(`Restoring (opening) detail row for paper ID ${paperId}`);
                    toggleDetails(toggleButton);
                } else {
                    //console.log(`Detail row for paper ID ${paperId} is already expanded.`);
                }
            } else {
                console.warn(`Detail toggle button not found for paper ID ${paperId} during restore.`);
            }
        } else {
            // Paper might be filtered out. ID remains in set for potential future restoration.
            //console.log(`Main row for detail paper ID ${paperId} not found or hidden, keeping ID.`);
        }
    });

    // --- PHASE 2: Restore History Rows ---
    const idsToOpenHistory = [...openHistoryIds];
    idsToOpenHistory.forEach(paperId => {
        const mainRow = document.querySelector(`tr[data-paper-id="${paperId}"]:not(.filter-hidden)`);
        if (mainRow) {
            const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleHistory"]'); // Target the specific history toggle button
            if (toggleButton) {
                // Remember: history-row is the *second* next sibling after the main row
                const historyRow = mainRow.nextElementSibling && mainRow.nextElementSibling.nextElementSibling &&
                                   mainRow.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
                                   mainRow.nextElementSibling.nextElementSibling : null;

                const isCurrentlyExpanded = historyRow && historyRow.classList.contains('expanded');
                if (!isCurrentlyExpanded) {
                    //console.log(`Restoring (opening) history row for paper ID ${paperId}`);
                    toggleHistory(toggleButton);
                } else {
                    //console.log(`History row for paper ID ${paperId} is already expanded.`);
                }
            } else {
                console.warn(`History toggle button not found for paper ID ${paperId} during restore.`);
            }
        } else {
            // Paper might be filtered out. ID remains in set for potential future restoration.
            //console.log(`Main row for history paper ID ${paperId} not found or hidden, keeping ID.`);
        }
    });

    // --- PHASE 3: Clean up rows that should be closed (e.g., due to filtering) ---
    // This phase ensures that if a row is expanded but its ID is not in the respective set,
    // it gets closed. This handles cases where a filter is applied after rows were opened.

    // Close detail rows that should not be open
    const allExpandedVisibleDetailRows = document.querySelectorAll('tr.detail-row.expanded:not(.filter-hidden)');
    allExpandedVisibleDetailRows.forEach(detailRow => {
        const mainRow = detailRow.previousElementSibling; // Should be the main paper row
        if (mainRow && mainRow.hasAttribute('data-paper-id')) {
            const paperId = mainRow.getAttribute('data-paper-id');
            if (!openDetailIds.has(paperId)) {
                // This detail row is open but shouldn't be according to the set.
                // Find its toggle button in the main row and call toggleDetails to close it.
                const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleDetails"]');
                if (toggleButton) {
                     //console.log(`Closing unintended detail row for paper ID ${paperId}`);
                     toggleDetails(toggleButton); // This should correctly update the set and URL
                } else {
                     console.warn(`Toggle button not found for paper ID ${paperId} when trying to close unintended detail row.`);
                }
            }
        } else {
             console.warn("Could not find main row for an expanded detail row during cleanup.");
        }
    });

    // Close history rows that should not be open
    const allExpandedVisibleHistoryRows = document.querySelectorAll('tr.history-row.expanded:not(.filter-hidden)');
    allExpandedVisibleHistoryRows.forEach(historyRow => {
        // Remember: history-row's previous sibling is detail-row, so main row is previousElementSibling of *that*
        const detailRow = historyRow.previousElementSibling; // Should be the detail row
        if (detailRow && detailRow.classList.contains('detail-row')) {
            const mainRow = detailRow.previousElementSibling; // Should be the main paper row
            if (mainRow && mainRow.hasAttribute('data-paper-id')) {
                const paperId = mainRow.getAttribute('data-paper-id');
                if (!openHistoryIds.has(paperId)) {
                    // This history row is open but shouldn't be according to the set.
                    // Find its toggle button in the main row and call toggleHistory to close it.
                    const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleHistory"]');
                    if (toggleButton) {
                         //console.log(`Closing unintended history row for paper ID ${paperId}`);
                         toggleHistory(toggleButton); // This should correctly update the set and URL
                    } else {
                         console.warn(`Toggle button not found for paper ID ${paperId} when trying to close unintended history row.`);
                    }
                }
            } else {
                 console.warn("Could not find main row for an expanded history row during cleanup.");
            }
        } else {
             console.warn("Previous sibling of an expanded history row is not a detail-row during cleanup.");
        }
    });

    //console.log("Finished restoreDetailState. Final open detail IDs:", [...openDetailIds], "Final open history IDs:", [...openHistoryIds]); // Debug log
}




/**
 * Copies the provided paper ID to the clipboard in the specified format.
 * Provides user feedback by changing the button text to 'Copied!' temporarily.
 * @param {string} paperId - The ID of the paper to copy.
 * @param {HTMLElement} buttonElement - The button that was clicked.
 * @param {string} format - The format to use ('raw', 'cite', or 'citen').
 */
function copyPaperId(paperId, buttonElement, format = 'raw') {
    if (!paperId) {
        console.warn('Paper ID is empty or undefined.');
        alert('Paper ID is empty and cannot be copied.');
        return;
    }

    const originalText = buttonElement.innerHTML;
    buttonElement.innerHTML = 'Copied!';
    
    let textToCopy = paperId;
    if (format === 'cite') {
        textToCopy = `\\cite{${paperId}}`;
    } else if (format === 'citen') {
        textToCopy = `\\citen{${paperId}}`;
    }
    
    navigator.clipboard.writeText(textToCopy)
        .then(() => {
            setTimeout(() => {
                buttonElement.innerHTML = originalText;
            }, 2000);
        })
        .catch(err => {
            console.error(`Failed to copy ${format === 'raw' ? 'ID' : 'citation'}: `, err);
            alert(`Failed to copy ${format === 'raw' ? 'ID' : 'citation'} to clipboard.`);
            buttonElement.innerHTML = originalText;
        });
}

/**
 * Copies the provided BibTeX string to the clipboard.
 * Provides user feedback by changing the button text to 'Copied!' temporarily.
 * @param {string} bibtexString - The BibTeX citation string to copy.
 * @param {HTMLElement} buttonElement - The button that was clicked.
 */
function copyBibtex(bibtexString, buttonElement) {
    if (bibtexString) {
        // Store original text
        const originalText = buttonElement.textContent;

        // Change button text immediately to provide feedback
        buttonElement.textContent = 'Copied!';

        navigator.clipboard.writeText(bibtexString)
            .then(() => {
                //console.log('BibTeX copied to clipboard.');
                // The text is already 'Copied!', now reset it after a delay
                setTimeout(() => {
                    buttonElement.textContent = originalText;
                }, 2000); // Reset text after 2 seconds
            })
            .catch(err => {
                console.error('Failed to copy BibTeX: ', err);
                alert('Failed to copy BibTeX to clipboard.');
                 // Reset text if copy failed
                 buttonElement.textContent = originalText;
            });
    } else {
        console.warn('BibTeX content is empty.');
        alert('BibTeX content is empty and cannot be copied.');
    }
}


/**
 * Generates a LaTeX longtable based on the currently visible (filtered) rows in the papers table.
 * Uses alternating row shading to separate rows instead of lines.
 * Sets smaller margins and font size to maximize data density.
 * Copies the generated LaTeX code to the clipboard and provides user feedback on the button.
 */
function copyLatexLongtable() {
    const buttonElement = document.getElementById('longtable-btn');
    if (!buttonElement) {
        console.error("Button #longtable-btn not found.");
        alert('Error: Could not find the LaTeX copy button.');
        return;
    }

    const originalText = buttonElement.innerHTML; // Use innerHTML to preserve formatting like <em>

    const rows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');

    if (rows.length === 0) {
        alert('No visible rows found to generate LaTeX table.');
        buttonElement.innerHTML = originalText;
        return;
    }

    let latexContent = `
% Ensure packages are loaded in your preamble:
% \\usepackage{longtable}
% \\usepackage{xcolor}
% \\usepackage{pdflscape} % For landscape pages
% \\usepackage[margin=1.5cm]{geometry} % Set smaller margins for the table area

\\begin{landscape} % Start landscape environment

% ----------------------------------------------------------
\\chapter{Lista completa de artigos julgados como relevantes através do ResearchParça}
% ----------------------------------------------------------

\\definecolor{tableshade}{HTML}{EEEEEE} 
\\scriptsize % Use smaller font to fit more data
\\begin{longtable}{p{2cm}p{8cm}p{5cm}c c p{6cm}} 
\\textbf{Tipo} & \\textbf{Título} & \\textbf{Autores} & \\textbf{Ano} & \\textbf{Páginas} & \\textbf{Periódico/Conferência} \\\\
\\hline % Line only under the header row
\\endfirsthead

\\multicolumn{6}{c}{{\\bfseries \\tablename\\ \\thetable{} -- continuação dá página anterior}} \\\\
\\rowcolor{tableshade}
\\textbf{Tipo} & \\textbf{Título} & \\textbf{Autores} & \\textbf{Ano} & \\textbf{Páginas} & \\textbf{Periódico/Conferência} \\\\
\\hline % Line only under the header row on subsequent pages
\\endhead

\\hline % Line before the footer
\\multicolumn{6}{|r|}{{Continua na próxima página}} \\\\
\\hline % Line after the footer text
\\endfoot

\\hline % Line before the last footer
\\endlastfoot

`; // End of preamble lines

    // Loop through rows and add data with alternating shading
    rows.forEach((row, index) => { // Add index to determine shading
        // Extract data using cached data if available, otherwise query DOM
        let cachedData = rowCache.get(row);

        // --- Retrieve Original Data ---
        // Type: Get the title attribute from the specific type emoji cell (6th status cell)
        const typeCell = row.cells[typeCellIndex]; // Use the hardcoded index for type cell (5th index -> 6th cell)
        const typeTitle = typeCell ? typeCell.getAttribute('title') || typeCell.textContent.trim() : '';

        // Title: Get directly from the title cell (1st index -> 2nd cell), preserving original case
        const titleCell = row.cells[titleCellIndex];
        const titleText = titleCell ? titleCell.textContent.trim() : ''; // Don't use lowercased cached version

        // Authors: Get from the hidden data cell
        const authorsCell = row.querySelector('td.hidden-data-cell[data-field="authors"]');
        const authorsText = authorsCell ? authorsCell.textContent.trim() : '';

        // Year: Get directly from the year cell (2nd index -> 3rd cell)
        const yearCell = row.cells[yearCellIndex];
        const yearText = yearCell ? yearCell.textContent.trim() : '';

        // Page Count: Get directly from the page count cell (3rd index -> 4th cell)
        const pageCountCell = row.cells[pageCountCellIndex];
        const pageCountText = pageCountCell ? pageCountCell.textContent.trim() : '';

        // Venue: Get directly from the journal/conference cell (4th index -> 5th cell)
        const venueCell = row.cells[journalCellIndex];
        const venueText = venueCell ? venueCell.textContent.trim() : '';


        // --- Sanitize data for LaTeX (basic escaping, handling newlines) ---
        const sanitizeForLatex = (str) => {
            if (typeof str !== 'string') str = String(str);
            // Basic replacements for common LaTeX special characters
            // Be careful with ampersands in particular for table alignment
            return str
        };

        const type = sanitizeForLatex(typeTitle);
        const title = sanitizeForLatex(titleText);
        const authors = sanitizeForLatex(authorsText);
        const year = sanitizeForLatex(yearText);
        const pages = sanitizeForLatex(pageCountText);
        const venue = sanitizeForLatex(venueText);

        // Determine if the row should be shaded based on its index
        const rowColor = (index % 2 === 0) ? '' : '\\rowcolor{tableshade} '; // Shade odd-numbered rows (0-indexed: 1st data row is 0, 2nd is 1, etc.)

        // Add the row content to the LaTeX string with potential shading
        // No \\hline after each data row
        latexContent += `${rowColor}${type} & ${title} & ${authors} & ${year} & ${pages} & ${venue} \\\\\n`; // Removed \\hline
    });

    // Add the final hline before \end{longtable} if you want a bottom border
    latexContent += `\\hline % Optional: Add a final line under the last data row if desired\n`;
    latexContent += `\\end{longtable}\n\n\\end{landscape} % End landscape environment\n`;

    navigator.clipboard.writeText(latexContent)
        .then(() => {
            //console.log('LaTeX table copied to clipboard.');
            buttonElement.innerHTML = 'Copied!';
            setTimeout(() => {
                buttonElement.innerHTML = originalText;
            }, 2000); // Reset text after 2 seconds
        })
        .catch(err => {
            console.error('Failed to copy LaTeX table: ', err);
            alert('Failed to copy LaTeX table to clipboard. Please check the console for details.');
            buttonElement.innerHTML = originalText;
        });
}


// Existing DOMContentLoaded listener and other code follows...
document.addEventListener('DOMContentLoaded', function () {
    // Apply client filters from URL first
    initializeClientFilters();
    
    hideXrayCheckbox.addEventListener('change', applyLocalFilters);
    hideApprovedCheckbox.addEventListener('change', applyLocalFilters);
    onlySurveyCheckbox.addEventListener('click', cycleSurveyFilterState);
    showPCBcheckbox.addEventListener('change', applyLocalFilters);
    showSolderCheckbox.addEventListener('change', applyLocalFilters);
    showPCBAcheckbox.addEventListener('change', applyLocalFilters);
    noFeaturesCheckbox.addEventListener('change', applyLocalFilters);
    showOtherCheckbox.addEventListener('change', applyLocalFilters);

    searchInput.addEventListener('input', () => {
        // For search specifically, we might want a shorter debounce time
        clearTimeout(filterTimeoutId);
        document.documentElement.classList.add('busyCursor');
        
        // Cancel any ongoing filter operation
        if (currentFilterAbortController) {
            currentFilterAbortController.abort();
        }
        
        // Create a new abort controller for this operation
        currentFilterAbortController = new AbortController();
        const signal = currentFilterAbortController.signal;
        
        filterTimeoutId = setTimeout(() => {
            if (signal.aborted) return;
            applyLocalFilters();
        }, 150); // Shorter debounce for search
    });
    document.getElementById('clear-search-btn').addEventListener('click', function() {
        searchInput.value = '';
        searchInput.dispatchEvent(new Event('input'));
    });

    document.getElementById('longtable-btn')?.addEventListener('click', copyLatexLongtable); // Use optional chaining


    headers.forEach(header => {
        header.addEventListener('click', sortTable);
    });
    
    applyLocalFilters(); // Apply initial filtering
    updateSurveyCheckboxUI();
}); 

