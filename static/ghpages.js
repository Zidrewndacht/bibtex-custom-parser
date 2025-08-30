const searchInput = document.getElementById('search-input');
const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
const minPageCountInput = document.getElementById('min-page-count');

const yearFromInput = document.getElementById('year-from');
const yearToInput = document.getElementById('year-to');

const fullscreenBtn = document.getElementById('fullscreen-btn');

const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
const totalPaperCount = allRows.length;

let filterTimeoutId = null;
const FILTER_DEBOUNCE_DELAY = 200;

let latestCounts = {};
const SYMBOL_SORT_WEIGHTS = {
    '✔️': 2,
    '❌': 1,
    '❔': 0
};

function scheduleFilterUpdate() {
    clearTimeout(filterTimeoutId);
    document.documentElement.classList.add('busyCursor');
    filterTimeoutId = setTimeout(() => {
        setTimeout(() => {
            applyFilters();
        }, 0);
    }, FILTER_DEBOUNCE_DELAY);
}

function toggleDetails(element) {
    const row = element.closest('tr');
    const detailRow = row.nextElementSibling;
    const isExpanded = detailRow && detailRow.classList.contains('expanded');
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
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', // Classification (Top-level)
    'features_tracks', 'features_holes', 'features_solder_insufficient', 'features_solder_excess',
    'features_solder_void', 'features_solder_crack', 'features_orientation', 'features_wrong_component',
    'features_missing_component', 'features_cosmetic', 'features_other', // Features (Nested under 'features')
    'technique_classic_cv_based', 'technique_ml_traditional',
    'technique_dl_cnn_classifier', 'technique_dl_cnn_detector', 'technique_dl_rcnn_detector',
    'technique_dl_transformer', 'technique_dl_other', 'technique_hybrid', 'technique_available_dataset', // Techniques (Nested under 'technique')
    'changed_by', 'verified', 'verified_by' // Add these for user counting (Top-level)
];
function updateCounts() { 
    const counts = {};
    COUNT_FIELDS.forEach(field => counts[field] = 0);
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const visiblePaperCount = visibleRows.length;

    visibleRows.forEach(row => {
        COUNT_FIELDS.forEach(field => {
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
    const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
    const totalPaperCount = allRows.length;
    latestCounts = counts; // Make counts available outside this function
    document.getElementById('visible-count-cell').textContent = `${visiblePaperCount} paper${visiblePaperCount !== 1 ? 's' : ''} of ${totalPaperCount}`;
    COUNT_FIELDS.forEach(field => {
        const countCell = document.getElementById(`count-${field}`);
        if (countCell) {
            countCell.textContent = counts[field];
        }
    });
}

function applyAlternatingShading() {
    const visibleMainRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    visibleMainRows.forEach((mainRow, groupIndex) => {
        const shadeClass = (groupIndex % 2 === 0) ? 'alt-shade-1' : 'alt-shade-2';
        mainRow.classList.remove('alt-shade-1', 'alt-shade-2');
        mainRow.classList.add(shadeClass);
        mainRow.nextElementSibling.classList.remove('alt-shade-1', 'alt-shade-2');
        mainRow.nextElementSibling.classList.add(shadeClass);
    });
}

function applyJournalShading(rows) {
    //Disabled, redundant after stats.
    // const journalCounts = new Map();
    // rows.forEach(row => {
    //     if (!row.classList.contains('filter-hidden')) {
    //         const journalCell = row.cells[3];
    //         if (journalCell) {
    //             const journalName = journalCell.textContent.trim();
    //             if (journalName) {
    //                 journalCounts.set(journalName, (journalCounts.get(journalName) || 0) + 1);
    //             }
    //         }
    //     }
    // });

    // let maxCount = 0;
    // for (const count of journalCounts.values()) {
    //     if (count > maxCount) maxCount = count;
    // }

    // const baseHue = 210;
    // const baseSaturation = 70;
    // const minLightness = 97;
    // const maxLightness = 80;

    // rows.forEach(row => {
    //     const journalCell = row.cells[3];
    //     if (journalCell) {
    //         journalCell.style.backgroundColor = '';
    //         if (!row.classList.contains('filter-hidden')) {
    //             const journalName = journalCell.textContent.trim();
    //             if (journalName) {
    //                 const count = journalCounts.get(journalName) || 0;
    //                 if (count > 1) {
    //                     let lightness;
    //                     if (maxCount <= 1) {
    //                         lightness = minLightness;
    //                     } else {
    //                         lightness = maxLightness + (minLightness - maxLightness) * (1 - (count - 1) / (maxCount - 1));
    //                         lightness = Math.max(maxLightness, Math.min(minLightness, lightness));
    //                     }
    //                     journalCell.style.backgroundColor = `hsl(${baseHue}, ${baseSaturation}%, ${lightness}%)`;
    //                 }
    //             }
    //         }
    //     }
    // });
}

function applyFilters() {
    const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';
    const tbody = document.querySelector('#papersTable tbody');
    if (!tbody) return;

    // --- Get filter values ---
    const hideOfftopicChecked = hideOfftopicCheckbox.checked;
    const minPageCountValue = minPageCountInput ? parseInt(minPageCountInput.value, 10) || 0 : 0;
    // Get year range values
    const yearFromValue = yearFromInput ? parseInt(yearFromInput.value, 10) || 0 : 0;
    const yearToValue = yearToInput ? parseInt(yearToInput.value, 10) || Infinity : Infinity;

    const rows = tbody.querySelectorAll('tr[data-paper-id]');
    rows.forEach(row => {
        let showRow = true;
        const paperId = row.getAttribute('data-paper-id');
        let detailRow = null;
        if (paperId) {
            let nextSibling = row.nextElementSibling;
            while (nextSibling && !nextSibling.classList.contains('detail-row')) {
                if (nextSibling.hasAttribute('data-paper-id')) break;
                nextSibling = nextSibling.nextElementSibling;
            }
            if (nextSibling && nextSibling.classList.contains('detail-row')) {
                detailRow = nextSibling;
            }
        }

        // --- Apply Filters ---

        // 1. Hide Off-topic
        if (showRow && hideOfftopicChecked) {
            const offtopicCell = row.querySelector('.editable-status[data-field="is_offtopic"]');
            if (offtopicCell && offtopicCell.textContent.trim() === '✔️') { 
                showRow = false;
            }
        }

        // 2. Minimum Page Count
        // Only hide if page count is a known number and it's less than the minimum
        if (showRow && minPageCountValue > 0) { // Only check if min value is set
            const pageCountCell = row.cells[4]; // Index 4 for 'Pages' column
            if (pageCountCell) {
                const pageCountText = pageCountCell.textContent.trim();
                // Only filter if there's actual text to parse
                if (pageCountText !== '') {
                    const pageCount = parseInt(pageCountText, 10);
                    // If parsing was successful and the number is less than the minimum, hide
                    if (!isNaN(pageCount) && pageCount < minPageCountValue) {
                        showRow = false;
                    }
                }
                // If pageCountText is '', pageCount is NaN, or pageCount >= min, row stays visible
            }
        }

        // 3. Year Range
        if (showRow) {
            const yearCell = row.cells[2]; // Index 2 for 'Year' column
            if (yearCell) {
                const yearText = yearCell.textContent.trim();
                const year = yearText ? parseInt(yearText, 10) : NaN;
                // If year is not a number or outside the range, hide the row
                 // Ensure year is valid before comparison
                if (isNaN(year) || year < yearFromValue || year > yearToValue) {
                    showRow = false;
                }
            }
        }

        // 4. Search Term
        if (showRow && searchTerm) {
            let rowText = (row.textContent || '').toLowerCase();
            let detailText = '';
            if (detailRow) {
                const detailClone = detailRow.cloneNode(true);
                // Exclude traces from search if desired (as in original)
                detailClone.querySelector('.detail-evaluator-trace .trace-content')?.remove();
                detailClone.querySelector('.detail-verifier-trace .trace-content')?.remove();
                detailText = (detailClone.textContent || '').toLowerCase();
            }
            if (!rowText.includes(searchTerm) && !detailText.includes(searchTerm)) {
                showRow = false;
            }
        }

        // Apply the visibility state
        row.classList.toggle('filter-hidden', !showRow);
        if (detailRow) { // Ensure detailRow exists before toggling
            detailRow.classList.toggle('filter-hidden', !showRow);
        }
    });

    // Update UI elements that depend on visible rows
    const currentVisibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
    applyJournalShading(currentVisibleRows);
    updateCounts();
    applyAlternatingShading();

    document.documentElement.classList.remove('busyCursor');
}


document.addEventListener('DOMContentLoaded', function () {
    const headers = document.querySelectorAll('th[data-sort]');
    let currentClientSort = { column: null, direction: 'ASC' };

    searchInput.addEventListener('input', scheduleFilterUpdate);
    hideOfftopicCheckbox.addEventListener('change', scheduleFilterUpdate);
    minPageCountInput.addEventListener('input', scheduleFilterUpdate);
    minPageCountInput.addEventListener('change', scheduleFilterUpdate);
    yearFromInput.addEventListener('input', scheduleFilterUpdate);
    yearFromInput.addEventListener('change', scheduleFilterUpdate); 
    yearToInput.addEventListener('input', scheduleFilterUpdate);
    yearToInput.addEventListener('change', scheduleFilterUpdate); 

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

                    if (['title', 'year', 'journal', /*'authors',*/ 'page_count', 'estimated_score', 'relevance'].includes(sortBy)) { // <-- Added 'relevance'
                        cell = mainRow.cells[headerIndex];
                        cellValue = cell ? cell.textContent.trim() : ''; // <-- ADDED NULL CHECK
                        if (sortBy === 'year' || sortBy === 'estimated_score' || sortBy === 'page_count' || sortBy === 'relevance') { // <-- Added 'relevance'
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


    const statsBtn = document.getElementById('stats-btn');
    const modal = document.getElementById('statsModal');
    const spanClose = document.querySelector('#statsModal .close');

    function calculateStats() {
        const stats = {
            journals: {},
            keywords: {},
            authors: {},
            researchAreas: {}
        };

        const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
        visibleRows.forEach(row => {
            const journalCell = row.cells[3];
            if (journalCell) {
                const journal = journalCell.textContent.trim();
                if (journal) {
                    stats.journals[journal] = (stats.journals[journal] || 0) + 1;
                }
            }
            const detailRow = row.nextElementSibling;
            if (detailRow && detailRow.classList.contains('detail-row')) {
                const keywordsPara = detailRow.querySelector('.detail-metadata p strong');
                if (keywordsPara && keywordsPara.textContent.trim() === 'Keywords:') {
                    const keywordsParent = keywordsPara.parentElement;
                    if (keywordsParent) {
                        let keywordsText = keywordsParent.textContent.trim();
                        const prefix = "Keywords:";
                        if (keywordsText.startsWith(prefix)) {
                            keywordsText = keywordsText.substring(prefix.length).trim();
                        }
                        const keywordsList = keywordsText.split(';')
                            .map(kw => kw.trim())
                            .filter(kw => kw.length > 0);
                        keywordsList.forEach(keyword => {
                            stats.keywords[keyword] = (stats.keywords[keyword] || 0) + 1;
                        });
                    }
                }
            }
            let authorsList = [];
            const detailRowForAuthors = row.nextElementSibling;
            if (detailRowForAuthors && detailRowForAuthors.classList.contains('detail-row')) {
                const authorsPara = Array.from(detailRowForAuthors.querySelectorAll('.detail-metadata p')).find(p => {
                    const strongTag = p.querySelector('strong');
                    return strongTag && strongTag.textContent.trim() === 'Full Authors:';
                });
                if (authorsPara) {
                    let authorsText = authorsPara.textContent.trim();
                    const prefix = "Full Authors:";
                    if (authorsText.startsWith(prefix)) {
                        authorsText = authorsText.substring(prefix.length).trim();
                    }
                    if (authorsText) {
                        authorsList = authorsText.split(';')
                            .map(author => author.trim())
                            .filter(author => author.length > 0);
                    } else {
                        console.warn("Found 'Full Authors:' paragraph but no author text following it.", row);
                    }
                }
            }
            authorsList.forEach(author => {
                stats.authors = stats.authors || {};
                stats.authors[author] = (stats.authors[author] || 0) + 1;
            });

            const detailRowForResearchArea = row.nextElementSibling;
            if (detailRowForResearchArea && detailRowForResearchArea.classList.contains('detail-row')) {
                const researchAreaInput = detailRowForResearchArea.querySelector('.detail-edit input[name="research_area"]');
                if (researchAreaInput) {
                    const researchArea = researchAreaInput.value.trim();
                    if (researchArea) {
                        stats.researchAreas[researchArea] = (stats.researchAreas[researchArea] || 0) + 1;
                    }
                }
            }
        });
        return stats;
    }

    function displayStats() {
        const FEATURE_FIELDS = [
            'features_tracks', 'features_holes', 'features_solder_insufficient',
            'features_solder_excess', 'features_solder_void', 'features_solder_crack',
            'features_orientation', 'features_missing_component', 'features_wrong_component',
            'features_cosmetic'
        ];
        // Include Datasets here temporarily to get the label mapping easily,
        // then filter it out for data/labels for the Techniques chart
        const TECHNIQUE_FIELDS_ALL = [
            'technique_classic_cv_based', 'technique_ml_traditional',
            'technique_dl_cnn_classifier', 'technique_dl_cnn_detector', 'technique_dl_rcnn_detector',
            'technique_dl_transformer', 'technique_dl_other', 'technique_hybrid',
            'technique_available_dataset' // Included to get label easily
        ];
        // Map NEW field names (data-field values / structure keys) to user-friendly labels (based on your table headers)
        const FIELD_LABELS = {
            // Features
            'features_tracks': 'Tracks',
            'features_holes': 'Holes',
            'features_solder_insufficient': 'Insufficient Solder',
            'features_solder_excess': 'Excess Solder',
            'features_solder_void': 'Solder Voids',
            'features_solder_crack': 'Solder Cracks',
            'features_orientation': 'Orientation/Polarity', // Combined as per previous logic
            'features_wrong_component': 'Wrong Component',
            'features_missing_component': 'Missing Component',
            'features_cosmetic': 'Cosmetic',
            // 'features_other': 'Other Features', // Label for 'other'

            // Techniques
            'technique_classic_cv_based': 'Classic CV',
            'technique_ml_traditional': 'Traditional ML',
            'technique_dl_cnn_classifier': 'CNN Classifier',
            'technique_dl_cnn_detector': 'CNN Detector (e.g., YOLO)',
            'technique_dl_rcnn_detector': 'R-CNN Detector',
            'technique_dl_transformer': 'Transformer',
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



        // --- Prepare Features Chart Data (in original order) ---
        // Read data in the order defined by FEATURE_FIELDS, without sorting
        const featuresLabels = FEATURE_FIELDS.map(field => FIELD_LABELS[field] || field);
        const featuresValues = FEATURE_FIELDS.map(field => getCountFromFooter(field));
        
        // // --- Prepare Features Chart Data ---
        // // Read and sort the data
        // const featuresData = FEATURE_FIELDS.map(field => ({
        //     label: FIELD_LABELS[field] || field,
        //     value: getCountFromFooter(field)
        // }));

        // // Sort by value descending (largest first)
        // featuresData.sort((a, b) => b.value - a.value);

        // // Extract sorted labels and values
        // const sortedFeaturesLabels = featuresData.map(item => item.label);
        // const sortedFeaturesValues = featuresData.map(item => item.value);

        // Define colors (same order as original)
        const featuresColors = [
            'hsla(180, 48%, 32%, 0.66)',    // PCB
            'hsla(180, 48%, 32%, 0.66)',  
            'hsla(0, 0%, 48%, 0.66)',       // solder
            'hsla(0, 0%, 48%, 0.66)', 
            'hsla(0, 0%, 48%, 0.66)',
            'hsla(0, 0%, 48%, 0.66)',
            'hsla(347, 70%, 49%, 0.66)', // PCBA
            'hsla(347, 70%, 49%, 0.66)', // 
            'hsla(347, 70%, 49%, 0.66)', // 
            'hsla(204, 82%, 37%, 0.66)',  // Blue
            'hsla(42, 100%, 37%, 0.66)',  // Yellow
            'hsla(260, 80%, 50%, 0.66)', // Purple
            'hsla(30, 100%, 43%, 0.66)',  // Orange
        ];

        const featuresBorderColors = [
            'hsla(204, 82%, 18%, 1.00)',
            'hsla(204, 82%, 18%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)',
            'hsla(347, 70%, 29%, 1.00)',
            'hsla(347, 70%, 29%, 1.00)',
            'hsla(347, 70%, 29%, 1.00)',
            'hsla(219, 100%, 30%, 1.00)',
            'hsla(42, 100%, 18%, 1.00)',
            'hsla(180, 48%, 18%, 1.00)',
            'hsla(30, 100%, 23%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)'
        ];

        const featuresChartData = {
            // labels: sortedFeaturesLabels,
            labels: featuresLabels, // <<< CHANGED
            datasets: [{
                label: 'Features Count',
                // data: sortedFeaturesValues,
                data: featuresValues, // <<< CHANGED
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
            'hsla(0, 0%, 48%, 0.66)',  // Grey
            'hsla(96, 100%, 29%, 0.66)',  
        ];

        const techniquesBorderColors = [
            'hsla(347, 70%, 29%, 1.00)',
            'hsla(204, 82%, 18%, 1.00)',
            'hsla(42, 100%, 18%, 1.00)',
            'hsla(180, 48%, 18%, 1.00)',
            'hsla(260, 100%, 30%, 1.00)',
            'hsla(30, 100%, 23%, 1.00)',
            'hsla(0, 0%, 28%, 1.00)',
            'hsla(147, 48%, 18%, 1.00)',
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
        function populateList(listElementId, dataObj) {
            const listElement = document.getElementById(listElementId);
            listElement.innerHTML = '';
            const sortedEntries = Object.entries(dataObj)
                .filter(([name, count]) => count > 1)
                .sort((a, b) => {
                    if (b[1] !== a[1]) {
                        return b[1] - a[1];
                    }
                    return a[0].localeCompare(b[0]);
                });
            if (sortedEntries.length === 0) {
                listElement.innerHTML = '<li>No items with count > 1.</li>';
                return;
            }
            sortedEntries.forEach(([name, count]) => {
                const listItem = document.createElement('li');
                const escapedName = name.replace(/&/g, "&amp;").replace(/</g, "<").replace(/>/g, ">");
                listItem.innerHTML = `<span class="count">${count}</span> <span class="name">${escapedName}</span>`;
                listElement.appendChild(listItem);
            });
        }
        populateList('journalStatsList', stats.journals);
        populateList('keywordStatsList', stats.keywords);
        populateList('authorStatsList', stats.authors);
        populateList('researchAreaStatsList', stats.researchAreas);

        modal.offsetHeight;
        modal.classList.add('modal-active');
    }
    function closeModal() {  modal.classList.remove('modal-active');   }
    if (spanClose) { spanClose.addEventListener('click', closeModal);  }
    window.addEventListener('click', function (event) {
        if (event.target === modal) {  closeModal();  }
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal.classList.contains('modal-active')) {  closeModal();   }
    });
    if (statsBtn) {
        statsBtn.addEventListener('click', function () {
            document.documentElement.classList.add('busyCursor');
            setTimeout(() => {
                displayStats();
                document.documentElement.classList.remove('busyCursor');
            }, 10);
        });
    }

    applyFilters();

});