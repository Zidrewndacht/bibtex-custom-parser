// static/filtering.js
/** This file contains client-side filtering code, shared between server-based full page and client-only HTML export. */

const APP_CONFIG = window.APP_CONFIG || { groups: [], editable_fields: [] };

// Hardcoded baseline cell indices (Leading 6 columns are fixed)
const pdfCellIndex = 0;
const titleCellIndex = 1;
const yearCellIndex = 2;
const pageCountCellIndex = 3;
const journalCellIndex = 4;
const typeCellIndex = 5;
const relevanceCellIndex = 7; // Leading 6 + Off-topic (6) = Relevance (7)

const searchInput = document.getElementById('search-input');
const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
const hideApprovedCheckbox = document.getElementById('hide-approved-checkbox');

let filterTimeoutId = null;
const FILTER_DEBOUNCE_DELAY = 250;
const MAX_STORED_OPEN_DETAILS = 10;
const headers = document.querySelectorAll('th[data-sort]');
let currentClientSort = { column: null, direction: 'ASC' };

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
const rowCache = new WeakMap();

// Helper to safely traverse nested JSON paths
function getJsonPath(obj, path) {
    if (!obj || !path) return null;
    return path.split('.').reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : null), obj);
}

// ============================================================================
// DYNAMIC FILTER CONFIGURATION (Built from YAML via APP_CONFIG)
// ============================================================================
const TRI_STATE_FILTERS = {};
const INCLUSION_FILTERS = {};
const ALL_INCLUSION_FIELDS = [];

APP_CONFIG.groups.forEach(group => {
    if (group.filter_type === 'tri_state') {
        TRI_STATE_FILTERS[group.name] = {
            field: group.json_path,
            cacheKey: `${group.name}Status`,
            label: group.label || group.friendly_name || group.name
        };
    } else if (group.filter_type === 'inclusion') {
        const fields = group.fields.map(f => `${group.json_path}.${f.key}`);
        INCLUSION_FILTERS[group.name] = fields;
        ALL_INCLUSION_FIELDS.push(...fields);
    }
});

const triStateFilterStates = {};
Object.keys(TRI_STATE_FILTERS).forEach(k => triStateFilterStates[k] = 'all');

const inclusionFilterStates = {};
Object.keys(INCLUSION_FILTERS).forEach(k => inclusionFilterStates[k] = false);

function updateTriStateUI(filterKey) {
    const checkbox = document.querySelector(`.tri-state-checkbox[data-filter-group="${filterKey}"]`);
    if (!checkbox) return;
    const state = triStateFilterStates[filterKey];
    const label = TRI_STATE_FILTERS[filterKey].label;
    checkbox.classList.remove('tri-state-indeterminate');
    switch(state) {
        case 'all':
            checkbox.checked = false;
            checkbox.indeterminate = false;
            checkbox.title = `Currently showing all papers. Click to show only ${label}.`;
            break;
        case 'only_true':
            checkbox.checked = true;
            checkbox.indeterminate = false;
            checkbox.title = `Currently showing only ${label} papers. Click to show only non-${label}.`;
            break;
        case 'only_false':
            checkbox.checked = false;
            checkbox.indeterminate = true;
            checkbox.title = `Currently showing only non-${label} papers. Click to show all papers.`;
            break;
    }
}

function cycleTriStateFilter(filterKey) {
    const states = ['all', 'only_true', 'only_false'];
    const current = triStateFilterStates[filterKey];
    triStateFilterStates[filterKey] = states[(states.indexOf(current) + 1) % 3];
    updateTriStateUI(filterKey);
    applyLocalFilters();
}

function updateInclusionUI(filterKey) {
    const checkbox = document.querySelector(`.inclusion-checkbox[data-filter-group="${filterKey}"]`);
    if (!checkbox) return;
    checkbox.checked = inclusionFilterStates[filterKey];
}

function toggleInclusionFilter(filterKey) {
    inclusionFilterStates[filterKey] = !inclusionFilterStates[filterKey];
    updateInclusionUI(filterKey);
    applyLocalFilters();
}

/**
 * Applies alternating row shading to visible main rows.
 * Ensures detail rows AND history rows follow their main row's shading.
 * Each "paper group" (main row + detail row + history row) gets a single alternating color.
 * Should be pure client-side to be reused for HTML export
 */
function applyAlternatingShading() {
    const rows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
    let idx = 0;
    for (const main of rows) {
        const shade = (idx & 1) ? 'alt-shade-2' : 'alt-shade-1';
        main.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
        main.classList.toggle('alt-shade-2', shade === 'alt-shade-2');
        const detail = main.nextElementSibling;
        if (detail && detail.classList.contains('detail-row')) {
            detail.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
            detail.classList.toggle('alt-shade-2', shade === 'alt-shade-2');
        }
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
        if (cachedData) {
            if (cachedData.journalText) journalCounts.set(cachedData.journalText, (journalCounts.get(cachedData.journalText) || 0) + 1);
            if (cachedData.titleText) titleCounts.set(cachedData.titleText, (titleCounts.get(cachedData.titleText) || 0) + 1);
        }
    }
    // Count duplicate titles (only titles with 2 or more occurrences)
    let duplicateTitleCount = 0;
    for (const [title, count] of titleCounts) { if (title && count >= 2) duplicateTitleCount++; }
    if (duplicateCountElement) duplicateCountElement.textContent = duplicateTitleCount;

    let maxCount = 0;
    for (const count of journalCounts.values()) { if (count > maxCount) maxCount = count; }

    const baseJournalHue = 210, baseSaturation = 66, minLightness = 96, maxLightness = 84;
    const baseTitleHue = 0, titleSaturation = 66, titleLightness = 94;
    const journalHslStrings = new Map();
    for (const [journalName, count] of journalCounts) {
        if (count >= 2) {
            let lightness = maxCount <= 1 ? minLightness : maxLightness + (minLightness - maxLightness) * (1 - (count - 1) / (maxCount - 1));
            lightness = Math.max(maxLightness, Math.min(minLightness, lightness));
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
        const cachedData = rowCache.get(row);
        if (cachedData) {
            if (cachedData.journalText && journalCounts.get(cachedData.journalText) >= 2) journalCell.style.backgroundColor = journalHslStrings.get(cachedData.journalText);
            if (cachedData.titleText && titleCounts.get(cachedData.titleText) >= 2) titleCell.style.backgroundColor = duplicateTitleHslString;
        }
    }
}

function compileSearchRegex(searchTerm) {
    if (!searchTerm) return null;
    searchTerms = searchTerm.split(/\s+/).filter(t => t.length > 0).map(t => t.toLowerCase());
    return new RegExp(searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
}

function getClientFilterState() {
    const state = {
        hide_approved: hideApprovedCheckbox.checked ? 1 : 0,
        hide_offtopic: hideOfftopicCheckbox.checked ? 1 : 0,
        search: searchInput.value.trim(),
        sort_by: currentClientSort.column || '',
        sort_dir: currentClientSort.direction || 'ASC'
    };
    Object.keys(triStateFilterStates).forEach(k => state[`${k}_filter`] = triStateFilterStates[k]);
    Object.keys(inclusionFilterStates).forEach(k => state[`show_${k}`] = inclusionFilterStates[k] ? 1 : 0);
    return state;
}

let urlUpdateTimeout;
function updateUrlWithClientFilters() {
    clearTimeout(urlUpdateTimeout);
    urlUpdateTimeout = setTimeout(() => {
        const url = new URL(window.location);
        const clientFilters = getClientFilterState();
        // Always include everything: '1', '0', 'all', search string, etc.
        // This is important because some checkboxes are default on, other default off, etc.
        for (const [key, value] of Object.entries(clientFilters)) url.searchParams.set(key, String(value));
        window.history.replaceState({}, '', url);
    }, 100);
}

let rafId = 0;
let currentFilterAbortController = null;

function applyLocalFilters() {
    // Cancel any ongoing filter operation
    if (currentFilterAbortController) currentFilterAbortController.abort();
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
        const hideApprovedChecked = hideApprovedCheckbox.checked;
        const hideOfftopicChecked = document.body.id === 'html-export' ? hideOfftopicCheckbox.checked : false;
        const minPageCountValue = document.body.id === 'html-export' ? (document.getElementById('min-page-count').value.trim() || 0) : 0;
        const yearFromValue = document.body.id === 'html-export' ? (document.getElementById('year-from').value.trim() || 0) : 0;
        const yearToValue = document.body.id === 'html-export' ? (document.getElementById('year-to').value.trim() || 0) : 0;
        const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const compiledSearchRegex = compileSearchRegex(searchTerm);

        const activeInclusionGroups = Object.keys(inclusionFilterStates).filter(k => inclusionFilterStates[k]);

        // --- Cache data for all rows in a single pass ---
        for (let i = 0; i < rows.length; i++) {
            if (signal.aborted) return;
            const row = rows[i];
            const cachedData = {
                journalText: row.cells[journalCellIndex]?.textContent?.trim().toLowerCase() || '',
                titleText: row.cells[titleCellIndex]?.textContent?.trim().toLowerCase() || '',
                pageCount: row.cells[pageCountCellIndex]?.textContent?.trim() || '',
                year: row.cells[yearCellIndex]?.textContent?.trim() || '',
                hiddenDataText: '',
                visibleRowText: ''
            };

            for (const [key, config] of Object.entries(TRI_STATE_FILTERS)) {
                const cell = row.querySelector(`[data-field="${config.field}"]`);
                cachedData[config.cacheKey] = cell ? cell.textContent.trim() : '❔';
            }

            const inclusionValues = {};
            const inclusionGroupMatches = {};
            Object.keys(INCLUSION_FILTERS).forEach(g => inclusionGroupMatches[g] = false);

            for (const fieldName of ALL_INCLUSION_FIELDS) {
                const cell = row.querySelector(`[data-field="${fieldName}"]`);
                const val = cell ? cell.textContent.trim() : '';
                inclusionValues[fieldName] = val;
                for (const [groupName, fields] of Object.entries(INCLUSION_FILTERS)) {
                    if (fields.includes(fieldName) && val === '✔️') inclusionGroupMatches[groupName] = true;
                }
            }
            cachedData.inclusionValues = inclusionValues;
            cachedData.inclusionGroupMatches = inclusionGroupMatches;

            const offtopicCell = row.querySelector('[data-field="is_offtopic"]');
            cachedData.offtopicStatus = offtopicCell ? offtopicCell.textContent.trim() : 'N/A';
            const verifiedCell = row.querySelector('[data-field="verified"]');
            cachedData.verifiedStatus = verifiedCell ? verifiedCell.textContent.trim() : 'N/A';

            let hiddenDataText = '';
            row.querySelectorAll('td.hidden-data-cell').forEach(c => hiddenDataText += ' ' + (c.textContent || '').toLowerCase());
            cachedData.hiddenDataText = hiddenDataText;

            let visibleRowText = ' ' + (row.getAttribute('data-paper-id') || '').toLowerCase();
            for (let j = 0; j < row.cells.length; j++) {
                if (!row.cells[j].classList.contains('hidden-data-cell')) visibleRowText += ' ' + row.cells[j].textContent.toLowerCase();
            }
            cachedData.visibleRowText = visibleRowText;
            rowCache.set(row, cachedData);
        }

        const toHide = [];
        const toShow = [];

        for (let i = 0; i < rows.length; i++) {
            if (signal.aborted) return;
            const row = rows[i];
            const cachedData = rowCache.get(row);
            let showRow = true;

            if (document.body.id === 'html-export') {
                if (showRow && hideOfftopicChecked && cachedData.offtopicStatus === '✔️') showRow = false;
                if (showRow && minPageCountValue > 0) {
                    const pageCount = parseInt(cachedData.pageCount, 10);
                    if (!isNaN(pageCount) && pageCount < minPageCountValue) showRow = false;
                }
                if (showRow && (yearFromValue || yearToValue)) {
                    const year = cachedData.year ? parseInt(cachedData.year, 10) : NaN;
                    if (isNaN(year) || (yearFromValue && year < yearFromValue) || (yearToValue && year > yearToValue)) showRow = false;
                }
            }

            if (showRow && searchTerm) {
                if (!cachedData.visibleRowText.includes(searchTerm) && !cachedData.hiddenDataText.includes(searchTerm)) showRow = false;
                if (showRow && compiledSearchRegex && !compiledSearchRegex.test(cachedData.visibleRowText + cachedData.hiddenDataText)) showRow = false;
            }

            if (showRow) {
                for (const [key, config] of Object.entries(TRI_STATE_FILTERS)) {
                    if (triStateFilterStates[key] !== 'all') {
                        const status = cachedData[config.cacheKey];
                        if (triStateFilterStates[key] === 'only_true' && status !== '✔️') showRow = false;
                        else if (triStateFilterStates[key] === 'only_false' && status === '✔️') showRow = false;
                    }
                }
            }

            if (showRow && hideApprovedChecked && cachedData.verifiedStatus === '✔️') showRow = false;

            if (showRow && activeInclusionGroups.length > 0) {
                let matchesAnyGroup = false;
                for (const g of activeInclusionGroups) {
                    if (cachedData.inclusionGroupMatches[g]) { matchesAnyGroup = true; break; }
                }
                if (!matchesAnyGroup) showRow = false;
            }

            const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ? row.nextElementSibling : null;
            const historyRow = detailRow && detailRow.nextElementSibling && detailRow.nextElementSibling.classList.contains('history-row') ? detailRow.nextElementSibling : null;
            
            const hide = !showRow;
            if (row.classList.contains('filter-hidden') !== hide) (hide ? toHide : toShow).push(row);
            if (detailRow && detailRow.classList.contains('filter-hidden') !== hide) (hide ? toHide : toShow).push(detailRow);
            if (historyRow && historyRow.classList.contains('filter-hidden') !== hide) (hide ? toHide : toShow).push(historyRow);
        }

        toHide.forEach(r => r.classList.add('filter-hidden'));
        toShow.forEach(r => r.classList.remove('filter-hidden'));

        rafId = requestAnimationFrame(() => {
            if (signal.aborted) return;
            if (document.body.id !== 'html-export') {
                const visibleRows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
                applyDuplicateShading(visibleRows);
                const applyButton = document.getElementById('apply-serverside-filters');
                if(applyButton) { applyButton.style.opacity = '0'; applyButton.style.pointerEvents = 'none'; }
            }
            if (currentClientSort.column) performSort(currentClientSort.column, currentClientSort.direction);
            updateUrlWithClientFilters();
            applyAlternatingShading();
            updateCounts();
            restoreDetailState();
            document.documentElement.classList.remove('busyCursor');
            if (currentFilterAbortController?.signal === signal) currentFilterAbortController = null;
        });
    }, FILTER_DEBOUNCE_DELAY);
}

function performSort(sortBy, direction, visibleMainRows = null) {
    if (!sortBy) return;
    const mainRowsToSort = visibleMainRows || Array.from(tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)'));
    if (mainRowsToSort.length === 0) return;

    const sortHeader = document.querySelector(`th[data-sort="${sortBy}"]`);
    if (!sortHeader) return;

    const isDateSort = sortBy === 'changed';
    const isNumericSort = ['year', 'estimated_score', 'page_count', 'relevance', 'user_override_count'].includes(sortBy);
    const isPDFSort = sortBy === 'pdf-link';
    const isVerifiedBySort = sortBy === 'verified_by';
    const isEditableStatusSort = !isNumericSort && !isPDFSort && !isVerifiedBySort && !['title', 'journal', 'changed_by', 'changed', 'type', 'user_comment_state'].includes(sortBy);

    const sortData = mainRowsToSort.map(mainRow => {
        let cellValue;
        if (isDateSort) {
            const cell = mainRow.querySelector('.changed-cell');
            const cellText = cell ? cell.textContent.trim() : '';
            const dateMatch = cellText.match(/(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
            cellValue = dateMatch ? new Date(2000 + parseInt(dateMatch[3]), parseInt(dateMatch[2]) - 1, parseInt(dateMatch[1]), parseInt(dateMatch[4]), parseInt(dateMatch[5]), parseInt(dateMatch[6])) : new Date(NaN);
        } else if (isNumericSort) {
            const cell = mainRow.querySelector(`[data-field="${sortBy}"]`) || mainRow.cells[yearCellIndex]; // fallback
            cellValue = cell ? parseFloat(cell.textContent.trim()) || 0 : 0;
        } else if (isPDFSort) {
            const cell = mainRow.cells[pdfCellIndex];
            cellValue = SYMBOL_PDF_WEIGHTS[cell?.textContent.trim()] ?? 0;
        } else if (isVerifiedBySort) {
            const cell = mainRow.querySelector(`.editable-verify[data-field="${sortBy}"]`);
            const symbolText = cell?.querySelector('span')?.textContent?.trim() || '';
            cellValue = VERIFIED_BY_SORT_WEIGHTS[symbolText] ?? 0;
        } else if (isEditableStatusSort) {
            const cell = mainRow.querySelector(`[data-field="${sortBy}"]`);
            cellValue = SYMBOL_SORT_WEIGHTS[cell?.textContent.trim()] ?? 0;
        } else {
            const cell = mainRow.cells[titleCellIndex]; // fallback for text
            cellValue = cell ? cell.textContent.trim() : '';
        }

        const detailRow = mainRow.nextElementSibling && mainRow.nextElementSibling.classList.contains('detail-row') ? mainRow.nextElementSibling : null;
        const historyRow = detailRow && detailRow.nextElementSibling && detailRow.nextElementSibling.classList.contains('history-row') ? detailRow.nextElementSibling : null;
        const rowGroup = [mainRow];
        if (detailRow) rowGroup.push(detailRow);
        if (historyRow) rowGroup.push(historyRow);
        return { value: cellValue, rowGroup, paperId: mainRow.getAttribute('data-paper-id') };
    });

    sortData.sort((a, b) => {
        let comparison = 0;
        if (a.value instanceof Date && b.value instanceof Date) {
            if (isNaN(a.value)) comparison = isNaN(b.value) ? 0 : 1;
            else if (isNaN(b.value)) comparison = -1;
            else comparison = a.value - b.value;
        } else if (typeof a.value === 'string' && typeof b.value === 'string') {
            comparison = a.value.localeCompare(b.value, undefined, { sensitivity: 'base' });
        } else {
            if (a.value > b.value) comparison = 1;
            else if (a.value < b.value) comparison = -1;
        }
        if (comparison === 0) {
            if (a.paperId > b.paperId) comparison = 1;
            else if (a.paperId < b.paperId) comparison = -1;
        }
        return direction === 'DESC' ? -comparison : comparison;
    });

    const fragment = document.createDocumentFragment();
    sortData.forEach(group => group.rowGroup.forEach(r => fragment.appendChild(r)));
    tbody.appendChild(fragment);

    document.querySelectorAll('th .sort-indicator').forEach(ind => ind.textContent = '');
    const indicator = sortHeader.querySelector('.sort-indicator');
    if (indicator) indicator.textContent = direction === 'ASC' ? '▲' : '▼';
}

function sortTable() {
    document.documentElement.classList.add('busyCursor');
    setTimeout(() => {
        const sortBy = this.getAttribute('data-sort');
        if (!sortBy) return;
        let newDirection = 'DESC';
        if (currentClientSort.column === sortBy) newDirection = currentClientSort.direction === 'DESC' ? 'ASC' : 'DESC';
        currentClientSort = { column: sortBy, direction: newDirection };
        performSort(sortBy, currentClientSort.direction);
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

function updateCounts() {
    const visibleRows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
    const visibleCount = visibleRows.length;
    const loadedCount = tbody.querySelectorAll('tr[data-paper-id]').length;
    
    const visibleCountEl = document.getElementById('visible-papers-count');
    if (visibleCountEl) visibleCountEl.textContent = visibleCount;
    
    const loadedCountEl = document.getElementById('loaded-papers-count');
    if (loadedCountEl) loadedCountEl.textContent = loadedCount;

    // Dynamic counts for inferred fields
    for (const group of APP_CONFIG.groups) {
        if (group.filter_type === 'tri_state') {
            const cell = document.getElementById(`count-${group.json_path}`) || document.querySelector(`[data-count-field="${group.json_path}"]`);
            if (cell) {
                let count = 0;
                visibleRows.forEach(row => {
                    const td = row.querySelector(`[data-field="${group.json_path}"]`);
                    if (td && td.textContent.trim() === '✔️') count++;
                });
                cell.textContent = count;
            }
        } else if (group.filter_type === 'inclusion' || group.filter_type === 'none') {
            for (const field_def of group.fields) {
                const path = `${group.json_path}.${field_def.key}`;
                const cell = document.getElementById(`count-${path.replace(/\./g, '_')}`) || document.getElementById(`count-${path}`) || document.querySelector(`[data-count-field="${path}"]`);
                if (cell) {
                    let count = 0;
                    visibleRows.forEach(row => {
                        const td = row.querySelector(`[data-field="${path}"]`);
                        if (td && td.textContent.trim() === '✔️') count++;
                    });
                    cell.textContent = count;
                }
            }
        }
    }
    
    // Baseline Counts
    const countVerified = document.getElementById('count-verified');
    if (countVerified) {
        let c = 0;
        visibleRows.forEach(row => {
            const td = row.querySelector('[data-field="verified"]');
            if (td && td.textContent.trim() === '✔️') c++;
        });
        countVerified.textContent = c;
    }
}

function initializeClientFilters() {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('hide_approved') === '1') hideApprovedCheckbox.checked = true;
    if (urlParams.get('hide_offtopic') === '1') hideOfftopicCheckbox.checked = true;
    const searchValueFromUrl = urlParams.get('search');
    if (searchValueFromUrl !== null) searchInput.value = searchValueFromUrl;
    const openDetailsParam = urlParams.get('open_details');
    openDetailIds = new Set(openDetailsParam ? openDetailsParam.split(',').map(id => id.trim()).filter(id => id !== '').slice(0, MAX_STORED_OPEN_DETAILS) : []);
    const openHistoryParam = urlParams.get('open_history');
    openHistoryIds = new Set(openHistoryParam ? openHistoryParam.split(',').map(id => id.trim()).filter(id => id !== '').slice(0, MAX_STORED_OPEN_DETAILS) : []);
    for (const key of Object.keys(TRI_STATE_FILTERS)) {
        const paramVal = urlParams.get(`${key}_filter`);
        if (['all', 'only_true', 'only_false'].includes(paramVal)) triStateFilterStates[key] = paramVal;
        updateTriStateUI(key);
    }
    for (const key of Object.keys(INCLUSION_FILTERS)) {
        const paramVal = urlParams.get(`show_${key}`);
        if (paramVal === '1') inclusionFilterStates[key] = true;
        updateInclusionUI(key);
    }
    const sortColumnFromUrl = urlParams.get('sort_by');
    const sortDirectionFromUrl = urlParams.get('sort_dir');
    if (sortColumnFromUrl) {
        currentClientSort = { column: sortColumnFromUrl, direction: sortDirectionFromUrl === 'DESC' ? 'DESC' : 'ASC' };
        const sortHeader = document.querySelector(`th[data-sort="${currentClientSort.column}"]`);
        if (sortHeader) {
            const indicator = sortHeader.querySelector('.sort-indicator');
            if (indicator) indicator.textContent = currentClientSort.direction === 'ASC' ? '▲' : '▼';
        }
    } else {
        currentClientSort = { column: null, direction: 'ASC' };
    }
    updateUrlWithClientFilters();
}

let openDetailIds = new Set();
let openHistoryIds = new Set();
let detailStateUpdateTimeout = null;

function updateUrlWithDetailState() {
    clearTimeout(detailStateUpdateTimeout);
    detailStateUpdateTimeout = setTimeout(() => {
        const url = new URL(window.location);
        const sortedDetailIds = [...openDetailIds].sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).slice(0, MAX_STORED_OPEN_DETAILS);
        if (sortedDetailIds.length > 0) url.searchParams.set('open_details', sortedDetailIds.join(','));
        else url.searchParams.delete('open_details');
        
        const sortedHistoryIds = [...openHistoryIds].sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).slice(0, MAX_STORED_OPEN_DETAILS);
        if (sortedHistoryIds.length > 0) url.searchParams.set('open_history', sortedHistoryIds.join(','));
        else url.searchParams.delete('open_history');
        
        window.history.replaceState({}, '', url);
    }, 100);
}

function restoreDetailState() {
    [...openDetailIds].forEach(paperId => {
        const mainRow = document.querySelector(`tr[data-paper-id="${paperId}"]:not(.filter-hidden)`);
        if (mainRow) {
            const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            if (toggleButton && !(mainRow.nextElementSibling && mainRow.nextElementSibling.classList.contains('expanded'))) toggleDetails(toggleButton);
        }
    });
    [...openHistoryIds].forEach(paperId => {
        const mainRow = document.querySelector(`tr[data-paper-id="${paperId}"]:not(.filter-hidden)`);
        if (mainRow) {
            const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            const historyRow = mainRow.nextElementSibling && mainRow.nextElementSibling.nextElementSibling && mainRow.nextElementSibling.nextElementSibling.classList.contains('history-row') ? mainRow.nextElementSibling.nextElementSibling : null;
            if (toggleButton && !(historyRow && historyRow.classList.contains('expanded'))) toggleHistory(toggleButton);
        }
    });
}


/**
 * Switches between history tabs (Main, Set 1, Set 2, Set 3)
 * Pure client-side - no server communication needed
 * @param {HTMLElement} tabButton - The clicked tab button element
 */
function switchHistoryTab(tabButton) {
    const paperId = tabButton.getAttribute('data-paper-id');
    const selectedTab = tabButton.getAttribute('data-tab');
    const historyRow = tabButton.closest('.history-flex-container');
    if (!historyRow) {
        console.error(`History container not found for paper ${paperId}`);
        return;
    }

    // Remove active class from all tabs
    historyRow.querySelectorAll('.history-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    // Remove active class from all tab panels
    historyRow.querySelectorAll('.history-tab-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    // Add active class to selected tab
    tabButton.classList.add('active');

    // Add active class to selected tab panel using data attributes
    const selectedPanel = historyRow.querySelector(`.history-tab-panel[data-tab-panel="${selectedTab}"][data-paper-id="${paperId}"]`);
    if (selectedPanel) {
        selectedPanel.classList.add('active');
    }
}

/**
 * Copies the provided paper ID to the clipboard in the specified format.
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
            setTimeout(() => { buttonElement.innerHTML = originalText; }, 2000);
        })
        .catch(err => {
            console.error(`Failed to copy: `, err);
            alert(`Failed to copy to clipboard.`);
            buttonElement.innerHTML = originalText;
        });
}

/**
 * Copies the provided BibTeX string to the clipboard.
 */
function copyBibtex(bibtexString, buttonElement) {
    if (bibtexString) {
        const originalText = buttonElement.textContent;
        buttonElement.textContent = 'Copied!';
        navigator.clipboard.writeText(bibtexString)
            .then(() => {
                setTimeout(() => { buttonElement.textContent = originalText; }, 2000);
            })
            .catch(err => {
                console.error('Failed to copy BibTeX: ', err);
                alert('Failed to copy BibTeX to clipboard.');
                buttonElement.textContent = originalText;
            });
    } else {
        console.warn('BibTeX content is empty.');
        alert('BibTeX content is empty and cannot be copied.');
    }
}

/**
 * Generates a LaTeX longtable based on the currently visible (filtered) rows.
 */
function copyLatexLongtable() {
    const buttonElement = document.getElementById('longtable-btn');
    if (!buttonElement) {
        console.error("Button #longtable-btn not found.");
        alert('Error: Could not find the LaTeX copy button.');
        return;
    }
    const originalText = buttonElement.innerHTML; 
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
`; 
    rows.forEach((row, index) => { 
        const typeCell = row.cells[typeCellIndex]; 
        const typeTitle = typeCell ? typeCell.getAttribute('title') || typeCell.textContent.trim() : '';
        const titleCell = row.cells[titleCellIndex];
        const titleText = titleCell ? titleCell.textContent.trim() : ''; 
        const authorsCell = row.querySelector('td.hidden-data-cell[data-field="authors"]');
        const authorsText = authorsCell ? authorsCell.textContent.trim() : '';
        const yearCell = row.cells[yearCellIndex];
        const yearText = yearCell ? yearCell.textContent.trim() : '';
        const pageCountCell = row.cells[pageCountCellIndex];
        const pageCountText = pageCountCell ? pageCountCell.textContent.trim() : '';
        const venueCell = row.cells[journalCellIndex];
        const venueText = venueCell ? venueCell.textContent.trim() : '';
        
        const sanitizeForLatex = (str) => typeof str !== 'string' ? String(str) : str;
        
        const type = sanitizeForLatex(typeTitle);
        const title = sanitizeForLatex(titleText);
        const authors = sanitizeForLatex(authorsText);
        const year = sanitizeForLatex(yearText);
        const pages = sanitizeForLatex(pageCountText);
        const venue = sanitizeForLatex(venueText);
        
        const rowColor = (index % 2 === 0) ? '' : '\\rowcolor{tableshade} '; 
        latexContent += `${rowColor}${type} & ${title} & ${authors} & ${year} & ${pages} & ${venue} \\\\ \n`; 
    });
    latexContent += `\\hline \n`;
    latexContent += `\\end{longtable}\n\\end{landscape} \n`;
    
    navigator.clipboard.writeText(latexContent)
        .then(() => {
            buttonElement.innerHTML = 'Copied!';
            setTimeout(() => { buttonElement.innerHTML = originalText; }, 2000);
        })
        .catch(err => {
            console.error('Failed to copy LaTeX table: ', err);
            alert('Failed to copy LaTeX table to clipboard.');
            buttonElement.innerHTML = originalText;
        });
}

document.addEventListener('DOMContentLoaded', function () {
    initializeClientFilters();
    
    hideApprovedCheckbox.addEventListener('change', applyLocalFilters);
    
    document.querySelectorAll('.tri-state-checkbox').forEach(cb => {
        const group = cb.getAttribute('data-filter-group');
        cb.addEventListener('click', () => cycleTriStateFilter(group));
    });
    
    document.querySelectorAll('.inclusion-checkbox').forEach(cb => {
        const group = cb.getAttribute('data-filter-group');
        cb.addEventListener('change', () => toggleInclusionFilter(group));
    });

    searchInput.addEventListener('input', () => {
        clearTimeout(filterTimeoutId);
        document.documentElement.classList.add('busyCursor');
        if (currentFilterAbortController) currentFilterAbortController.abort();
        currentFilterAbortController = new AbortController();
        filterTimeoutId = setTimeout(() => {
            if (currentFilterAbortController.signal.aborted) return;
            applyLocalFilters();
        }, 150);
    });
    
    document.getElementById('clear-search-btn').addEventListener('click', function() {
        searchInput.value = '';
        searchInput.dispatchEvent(new Event('input'));
    });
    
    headers.forEach(header => header.addEventListener('click', sortTable));
    
    // RESTORED: Event delegation for history tab switching
    document.addEventListener('click', function(event) {
        const tabButton = event.target.closest('.history-tab-btn');
        if (tabButton) {
            switchHistoryTab(tabButton);
        }
    });

    // RESTORED: Event listener for LaTeX longtable button
    document.getElementById('longtable-btn')?.addEventListener('click', copyLatexLongtable);

    applyLocalFilters();
});