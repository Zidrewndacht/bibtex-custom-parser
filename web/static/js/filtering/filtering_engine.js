// static/js/filtering_engine.js
/** Core filtering, sorting, shading, and row-expansion pipeline.
 *  Shared between server-based full page and client-only HTML export. */

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
    const isChangedBySort = sortBy === 'changed_by';          // ← ADD
    const isTypeSort = sortBy === 'type';
    const isUserCommentSort = sortBy === 'user_comment_state';
    const isEditableStatusSort = !isNumericSort && !isPDFSort && !isVerifiedBySort
        && !isChangedBySort && !isTypeSort && !isUserCommentSort   // ← ADD isChangedBySort
        && !['title', 'journal', 'changed'].includes(sortBy);

    const sortData = mainRowsToSort.map(mainRow => {
        let cellValue;
        if (isDateSort) {
            const cell = mainRow.querySelector('.changed-cell');
            const cellText = cell ? cell.textContent.trim() : '';
            const dateMatch = cellText.match(/(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
            cellValue = dateMatch ? new Date(2000 + parseInt(dateMatch[3]), parseInt(dateMatch[2]) - 1, parseInt(dateMatch[1]), parseInt(dateMatch[4]), parseInt(dateMatch[5]), parseInt(dateMatch[6])) : new Date(NaN);
        } else if (isNumericSort) {
            const cell = mainRow.querySelector(`[data-field="${sortBy}"]`) || mainRow.cells[yearCellIndex];
            cellValue = cell ? parseFloat(cell.textContent.trim()) || 0 : 0;
        } else if (isPDFSort) {
            const cell = mainRow.cells[pdfCellIndex];
            cellValue = SYMBOL_PDF_WEIGHTS[cell?.textContent.trim()] ?? 0;
        } else if (isVerifiedBySort) {
            const cell = mainRow.querySelector(`.editable-verify[data-field="${sortBy}"]`);
            const symbolText = cell?.querySelector('span')?.textContent?.trim() || '';
            cellValue = VERIFIED_BY_SORT_WEIGHTS[symbolText] ?? 0;
        } else if (isChangedBySort) {                          // ← ADD THIS BLOCK
            const cell = mainRow.querySelector('[data-field="changed_by"]');
            const symbolText = cell?.querySelector('span')?.textContent?.trim() || '';
            cellValue = VERIFIED_BY_SORT_WEIGHTS[symbolText] ?? 0;
        } else if (isTypeSort) {
            // FIX: read from the actual type column, using the title attr (raw type name)
            const cell = mainRow.cells[typeCellIndex];
            cellValue = cell ? (cell.getAttribute('title') || cell.textContent.trim()) : '';
        } else if (isUserCommentSort) {
            // FIX: read from the actual commented cell, not the title column
            const cell = mainRow.querySelector('[data-field="user_comment_state"]');
            cellValue = SYMBOL_SORT_WEIGHTS[cell?.textContent.trim()] ?? 0;
        } else if (isEditableStatusSort) {
            // FIX: certainty-aware sort — conflicts grouped, partial agreement differentiated
            const cell = mainRow.querySelector(`[data-field="${sortBy}"]`);
            if (cell) {
                const hasConflict = cell.querySelector('.conflict-warning') !== null;
                if (hasConflict) {
                    cellValue = 3.25; // all conflicts grouped together between weak-yes and strong-no
                } else {
                    const emojiSpan = cell.querySelector('.emoji-content');
                    const emoji = emojiSpan ? emojiSpan.textContent.trim() : '';
                    const baseWeight = SYMBOL_SORT_WEIGHTS[emoji] ?? 0; // ✔️=2, ❌=1, ❔=0
                    const certBonus = cell.classList.contains('certainty-solid') ? 0 :
                                    cell.classList.contains('certainty-80')   ? -0.25 :
                                    cell.classList.contains('certainty-60')   ? -0.5 : -0.75;
                    cellValue = baseWeight * 2 + certBonus;
                }
            } else {
                cellValue = 0;
            }
        } else {
            const cell = mainRow.cells[titleCellIndex];
            cellValue = cell ? cell.textContent.trim() : '';
        }
        // ... rest of sortData (detailRow, historyRow, rowGroup) unchanged ...

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
    // Double requestAnimationFrame ensures the browser paints the loading overlay
    // before we start the blocking sort operation
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
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
        });
    });
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