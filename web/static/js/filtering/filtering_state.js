// static/js/filtering_state.js
/** Filter definitions, runtime state, checkbox handlers, and URL ↔ state serialization.
 *  Shared between server-based full page and client-only HTML export. */

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