// static/stats.js
/** This file contains client-side statistics code, shared between server-based full page and client-only HTML export.
 * Also includes all modal open/close logic for now.
 */
// stats.js
/** Stats-related Functionality **/

// --- State Variables ---
let latestCounts = {}; // This will store the counts calculated by updateCounts
let latestYearlyData = {};
let isStacked = false; // Default state
let isCumulative = false; // Default state
let showPieCharts = false; // Default to bar charts

// --- DOM Elements ---
const statsBtn = document.getElementById('stats-btn');
const aboutBtn = document.getElementById('about-btn');
const modal = document.getElementById('statsModal');
const modalSmall = document.getElementById('aboutModal');
const spanClose = document.querySelector('#statsModal .close'); // Specific close button
const smallClose = document.querySelector('#aboutModal .close'); // Specific close button

// --- Color Definitions ---
// Define the fixed color order used in the Techniques Distribution chart (sorted)
const techniquesColors = [
    'hsla(347, 60%, 69%, 0.95)', // Red - Classic CV
    'hsla(204, 62%, 57%, 0.95)',  // Blue - Traditional ML
    'hsla(52, 80%, 47%, 0.95)',  // Yellow - CNN Classifier
    'hsla(180, 32%, 52%, 0.95)',  // Teal - CNN Detector
    'hsla(260, 60%, 66%, 0.95)', // Purple - R-CNN Detector
    'hsla(25, 70%, 63%, 0.95)',  // Orange - Transformer
    'hsla(0, 0%, 68%, 0.95)',   // Grey - Other DL
    'hsla(96, 66%, 49%, 0.95)', // Green - Hybrid
];
const techniquesBorderColors = [
    'hsla(347, 70%, 39%, 0.75)',
    'hsla(204, 82%, 28%, 0.75)',
    'hsla(42, 100%, 28%, 0.75)',
    'hsla(180, 48%, 28%, 0.75)',
    'hsla(260, 100%, 40%, 0.75)',
    'hsla(30, 100%, 33%, 0.75)',
    'hsla(0, 0%, 38%, 0.75)',
    'hsla(147, 48%, 38%, 0.75)',
];

// Map technique fields to their *original* color index in the unsorted list
// IMPORTANT: This list must match the order of TECHNIQUE_FIELDS_FOR_YEARLY
const TECHNIQUE_FIELDS_FOR_YEARLY = [
    'technique_classic_cv_based', 'technique_ml_traditional',
    'technique_dl_cnn_classifier', 'technique_dl_cnn_detector', 'technique_dl_rcnn_detector',
    'technique_dl_transformer', 'technique_dl_other', 'technique_hybrid'
];
const TECHNIQUE_FIELD_COLOR_MAP = {};
// Include Datasets here temporarily to get the label mapping easily,
// then filter it out for data/labels for the Techniques chart
const TECHNIQUE_FIELDS_ALL = [
    ...TECHNIQUE_FIELDS_FOR_YEARLY,
    'technique_available_dataset' // Included to get label easily
];

// Define the original color order for Features Distribution chart
const featuresColorsOriginalOrder = [
    'hsla(130, 27%, 60%, 0.95)',    //  - PCB - Tracks (Teal)
    'hsla(130, 27%, 60%, 0.95)',    //  - PCB - Holes (Teal)
    'hsla(130, 27%, 60%, 0.95)',    //  - PCB - other (Teal)
    'hsla(0, 0%, 68%, 0.95)',       //  - solder - Insufficient (Grey)
    'hsla(0, 0%, 68%, 0.95)',       //  - solder - Excess (Grey)
    'hsla(0, 0%, 68%, 0.95)',       //  - solder - Void (Grey)
    'hsla(0, 0%, 68%, 0.95)',       //  - solder - Crack (Grey)
    'hsla(0, 0%, 68%, 0.95)',       //  - solder - other (Grey)
    'hsla(347, 70%, 72%, 0.95)',    //  - PCBA - Orientation (Red)
    'hsla(347, 70%, 72%, 0.95)',    //  - PCBA - Missing Comp (Red)
    'hsla(347, 70%, 72%, 0.95)',    //  - PCBA - Wrong Comp (Red)
    'hsla(347, 70%, 72%, 0.95)',    //  - PCBA - Other (Red)
    'hsla(204, 88%, 70%, 0.95)',    //  - Cosmetic (Blue)
    'hsla(284, 88%, 70%, 0.95)',    //  - Other
];
const featuresBorderColorsOriginalOrder = [
    'hsla(144, 83%, 28%, 0.75)',    // 0 - PCB - Tracks
    'hsla(144, 82%, 28%, 0.75)',    // 1 - PCB - Holes
    'hsla(144, 82%, 28%, 0.75)',    // 2 - PCB - other
    'hsla(0, 0%, 38%, 0.75)',       // 3 - solder - Insufficient
    'hsla(0, 0%, 38%, 0.75)',       // 4 - solder - Excess
    'hsla(0, 0%, 38%, 0.75)',       // 5 - solder - Void
    'hsla(0, 0%, 38%, 0.75)',       // 6 - solder - Crack
    'hsla(0, 0%, 38%, 0.75)',       // 7 - solder - other
    'hsla(347, 70%, 39%, 0.75)',    // 8 - PCBA - Orientation
    'hsla(347, 70%, 39%, 0.75)',    // 9 - PCBA - Missing Comp
    'hsla(347, 70%, 39%, 0.75)',    // 10 - PCBA - Wrong Comp
    'hsla(347, 70%, 39%, 0.75)',    // 11 - PCBA - Other
    'hsla(219, 100%, 40%, 0.75)',   // 12 - Cosmetic
    'hsla(284, 82%, 47%, 0.75)',    // 13 - Other
];

// Map feature fields to their *original* index in the unsorted list
// IMPORTANT: This list must match the order of FEATURE_FIELDS_FOR_YEARLY
const FEATURE_FIELDS_FOR_YEARLY = [
    'features_tracks', 'features_holes', 'features_bare_pcb_other',
    'features_solder_insufficient', 'features_solder_excess', 'features_solder_void', 'features_solder_crack', 'features_solder_other',
    'features_orientation', 'features_wrong_component', 'features_missing_component', 'features_component_other',
    'features_cosmetic',
    'features_other_state'
];
const FEATURE_FIELD_INDEX_MAP = {};
const FEATURE_FIELDS = [...FEATURE_FIELDS_FOR_YEARLY]; // Assuming FEATURE_FIELDS is the same as FOR_YEARLY

// --- Map Feature Fields to their Color Groups for Line Chart ---
// Define the distinct color groups for the line chart based on original colors
// The keys are the indices in the original color arrays that represent unique colors
const featureColorGroups = {
    0: { label: 'Bare PCB Defects', fields: [] },
    3: { label: 'Solder Defects', fields: [] },
    8: { label: 'PCB Assembly Defects', fields: [] },
    12: { label: 'Cosmetic', fields: [] },
    13: { label: 'Other', fields: [] }
};

// Map field names (data-field values / structure keys) to user-friendly labels (based on your table headers)
const FIELD_LABELS = {
    // Features
    'features_tracks': '(Bare PCB) Tracks',
    'features_holes': '(Bare PCB) Holes',
    'features_bare_pcb_other': '(Bare PCB) Other',
    'features_solder_insufficient': '(Solder) Insufficient',
    'features_solder_excess': '(Solder) Excess',
    'features_solder_void': '(Solder) Voids',
    'features_solder_crack': '(Solder) Cracks',
    'features_solder_other': '(Solder) Other',
    'features_orientation': '(PCBA) Orientation/Polarity', // Combined as per previous logic
    'features_wrong_component': '(PCBA) Wrong Component',
    'features_missing_component': '(PCBA) Missing Component',
    'features_component_other': '(PCBA) Other',
    'features_cosmetic': 'Cosmetic',
    'features_other_state': 'Other',
    // Techniques
    'technique_classic_cv_based': 'Classic CV',
    'technique_ml_traditional': 'Traditional ML',
    'technique_dl_cnn_classifier': 'CNN Classifier',
    'technique_dl_cnn_detector': 'CNN Detector',
    'technique_dl_rcnn_detector': 'R-CNN Detector',
    'technique_dl_transformer': 'Transformer',
    'technique_dl_other': 'Other DL',
    'technique_hybrid': 'Hybrid',
    'technique_available_dataset': 'Datasets' // Label for Datasets
};

// --- Define Mapping for Publication Types ---
const PUB_TYPE_MAP = {
    'article': 'Journal',
    'inproceedings': 'Conference',
    // 'proceedings': 'Conference', // Example: map proceedings to Conference as well
    // 'conference': 'Conference',    // Example: map conference to Conference as well
    // // Add other BibTeX types if needed, e.g.:
    // 'techreport': 'Report',
    // 'book': 'Book',
    // 'booklet': 'Booklet',
    // 'manual': 'Manual',
    // 'mastersthesis': 'Thesis (Masters)',
    // 'phdthesis': 'Thesis (PhD)',
    // 'unpublished': 'Unpublished'
};

function mapPubType(type) {
    return PUB_TYPE_MAP[type] || type; // Return mapped value or original if not found
}

function getChartDPR() {
    const nativeDPR = window.devicePixelRatio || 1; // Fallback to 1 if API isn't available
    if (nativeDPR > 1.0 && nativeDPR < 2.0) {
        return nativeDPR * 2; // Use 2x for slightly over 1x screens to improve clarity
    }
    // Use native DPR for <= 1x or >= 2x screens
    return nativeDPR;
}

// Define the fields for which we want to count '✔️':
const COUNT_FIELDS = [
    'pdf_present',
    'pdf_annotated',
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', // Classification (Top-level)
    'features_tracks', 'features_holes', 'features_bare_pcb_other',
    'features_solder_insufficient', 'features_solder_excess',
    'features_solder_void', 'features_solder_crack', 'features_solder_other',
    'features_orientation', 'features_wrong_component', 'features_missing_component', 'features_component_other',
    'features_cosmetic', 'features_other_state',
    'technique_classic_cv_based', 'technique_ml_traditional',
    'technique_dl_cnn_classifier', 'technique_dl_cnn_detector', 'technique_dl_rcnn_detector',
    'technique_dl_transformer', 'technique_dl_other', 'technique_hybrid', 'technique_available_dataset', // Techniques (Nested under 'technique')
    'changed_by', 'verified', 'verified_by', 'user_comment_state' // user counting (Top-level)
];

/** updateCounts() is used by filtering.js and comms.js! */
function updateCounts() { 
    const counts = {};
    const yearlySurveyImpl = {}; // { year: { surveys: count, impl: count } }
    const yearlyTechniques = {}; // { year: { technique_field: count, ... } }
    const yearlyFeatures = {}; // { year: { feature_field: count, ... } }
    const yearlyPubTypes = {}; // { year: { pubtype1: count, pubtype2: count, ... } }
    const yearlyModels = {}; // { year: { modelName: count, ... } }

    // Initialize counts for all defined fields
    COUNT_FIELDS.forEach(field => counts[field] = 0);

    // Select only VISIBLE main rows for counting '✔️' and calculating visible count
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const visiblePaperCount = visibleRows.length;

    //count on each update since server-side async can change this:
    const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
    const loadedPaperCount = allRows.length;

    // Count symbols in visible rows and collect yearly data
    visibleRows.forEach(row => {
        const pdfCell = row.cells[pdfCellIndex];
        if (pdfCell) {
            const pdfContent = pdfCell.textContent.trim();
            // Increment counts based on the emoji in the PDF cell
            if (pdfContent === '📕') { // PDF present
                counts['pdf_present'] = (counts['pdf_present'] || 0) + 1;
            } else if (pdfContent === '📗') { // Annotated PDF present
                counts['pdf_annotated'] = (counts['pdf_annotated'] || 0) + 1;
                counts['pdf_present'] = (counts['pdf_present'] || 0) + 1;       // Also count annotated as a PDF present
            } else if (pdfContent === '💰') {
                counts['pdf_paywalled'] = (counts['pdf_paywalled'] || 0) + 1;
            }
            // '❔' means no PDF, so no increment needed for this state
        }
        COUNT_FIELDS.forEach(field => {
            // Skip the PDF fields as they are handled separately above
            if (field === 'pdf_present' || field === 'pdf_annotated') {
                return; // Skip to the next field
            }
            const cell = row.querySelector(`[data-field="${field}"]`);
            const cellText = cell ? cell.textContent.trim() : '';
            if (field === 'model') {
                if (cellText && cellText !== '') { // Check if there's content
                    // Split the content by comma and trim whitespace
                    const modelNames = cellText.split(',').map(name => name.trim()).filter(name => name !== '');
                    // Add the number of distinct models found in this cell to the total count
                    counts[field] += modelNames.length;
                    // --- Update Yearly Model Counts ---
                    const yearCell = row.cells[yearCellIndex];
                    const yearText = yearCell ? yearCell.textContent.trim() : '';
                    const year = yearText ? parseInt(yearText, 10) : null;
                    if (year && !isNaN(year)) {
                        if (!yearlyModels[year]) {
                            yearlyModels[year] = {};
                        }
                        modelNames.forEach(modelName => {
                            // Increment count for this specific model name in this specific year
                            yearlyModels[year][modelName] = (yearlyModels[year][modelName] || 0) + 1;
                        });
                    }
                }
                // After processing the model field, return to avoid the default '✔️' check below
                return;
            }
            if (field === 'changed_by' || field === 'verified_by') {
                if (cellText === '👤') {
                    counts[field]++;
                }
            } else {
                if (cellText === '✔️') {
                    counts[field]++;
                }
            }
        });
        const yearCell = row.cells[yearCellIndex]; // Assuming Year is the 3rd column (index 2)
        const yearText = yearCell ? yearCell.textContent.trim() : '';
        const year = yearText ? parseInt(yearText, 10) : null;
        if (year && !isNaN(year)) {
            // Initialize yearly data objects for the year if they don't exist
            if (!yearlySurveyImpl[year]) {
                yearlySurveyImpl[year] = { surveys: 0, impl: 0 };
            }
            if (!yearlyTechniques[year]) {
                yearlyTechniques[year] = {};
                TECHNIQUE_FIELDS_FOR_YEARLY.forEach(f => yearlyTechniques[year][f] = 0);
            }
            if (!yearlyFeatures[year]) {
                yearlyFeatures[year] = {};
                FEATURE_FIELDS_FOR_YEARLY.forEach(f => yearlyFeatures[year][f] = 0);
            }
            // Update Publication Type counts ---
            const typeCell = row.cells[typeCellIndex]; // Assuming Type is the 1st column (index 0)
            const pubTypeText = typeCell ? typeCell.getAttribute('title') || typeCell.textContent.trim() : ''; // Use title for full type if available
            if (pubTypeText) {
                if (!yearlyPubTypes[year]) {
                    yearlyPubTypes[year] = {}; // Initialize object for this year's types
                }
                // Increment count for this type in this year
                yearlyPubTypes[year][pubTypeText] = (yearlyPubTypes[year][pubTypeText] || 0) + 1;
            }
            // Update Survey/Impl counts
            const isSurveyCell = row.querySelector('.editable-status[data-field="is_survey"]');
            const isSurvey = isSurveyCell && isSurveyCell.textContent.trim() === '✔️';
            if (isSurvey) {
                yearlySurveyImpl[year].surveys++;
            } else {
                yearlySurveyImpl[year].impl++;
            }
            // Update Technique counts
            TECHNIQUE_FIELDS_FOR_YEARLY.forEach(field => {
                const techCell = row.querySelector(`.editable-status[data-field="${field}"]`);
                if (techCell && techCell.textContent.trim() === '✔️') {
                    yearlyTechniques[year][field]++;
                }
            });
            // Update Feature counts
            FEATURE_FIELDS_FOR_YEARLY.forEach(field => {
                // const featCell = row.querySelector(`.editable-status[data-field="${field}"]`); //breaks "other" counts in chart, as it's a calculated, non-editable cell!
                const featCell = row.querySelector(`[data-field="${field}"]`);
                if (featCell && featCell.textContent.trim() === '✔️') {
                    yearlyFeatures[year][field]++;
                }
            });
            // Note: Yearly model counts are updated inside the 'model' field loop above
        }
    });

    // Make counts available outside this function
    latestCounts = counts;
    latestYearlyData = {
        surveyImpl: yearlySurveyImpl,
        techniques: yearlyTechniques,
        features: yearlyFeatures,
        pubTypes: yearlyPubTypes,
        models: yearlyModels
    };

    // ... (rest of the function remains the same: visible/loaded counts, footer updates)
    if (document.body.id === 'html-export') {
        // Alternative code for specific page
        document.getElementById('visible-count-cell').innerHTML = `<strong>${visiblePaperCount}</strong> paper${visiblePaperCount !== 1 ? 's' : ''} of <strong>${totalPaperCount}</strong>`;
    } else {
        // Original code for other pages
        const visiblePapersCountCell = document.getElementById('visible-papers-count');
        const loadedPapersCountCell = document.getElementById('loaded-papers-count');
        loadedPapersCountCell.textContent = loadedPaperCount;
        visiblePapersCountCell.textContent = visiblePaperCount;
    }

    // --- Update Footer Counts ---
    COUNT_FIELDS.forEach(field => {
        // Skip the 'pdf_annotated' field for direct footer update, as it's part of the combined PDF cell
        if (field === 'pdf_annotated') {
            return; // Skip updating the individual annotated count cell directly
        }
        const countCell = document.getElementById(`count-${field}`);
        if (countCell) {
            // For 'pdf_present', set the text content to the total count
            // and add a tooltip showing both counts
            if (field === 'pdf_present') {
                countCell.textContent = counts['pdf_present'];
                countCell.title = `Stored PDFs: ${counts['pdf_present']}, Annotated PDFs: ${counts['pdf_annotated']}, Paywalled: ${counts['pdf_paywalled']}. Data for the currently filtered set.`; // Set tooltip
            } else {
                // For all other fields, set the text content normally
                // Now, counts['model'] reflects the total number of model mentions
                countCell.textContent = counts[field];
            }
        }
    });
}

function calculateJournalConferenceStats() {
    const journalCounts = {};
    const conferenceCounts = {};
    // Select only VISIBLE main rows
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    visibleRows.forEach(row => {
        const journalCell = row.cells[journalCellIndex]; // Use the global defined in globals.js
        const typeCell = row.cells[typeCellIndex]; // Use the global defined in globals.js
        if (journalCell && typeCell) {
            const journalName = journalCell.textContent.trim();
            const type = typeCell.getAttribute('title') || typeCell.textContent.trim(); // Prefer title attribute for type
            // Only count if journal name is not empty
            if (journalName) {
                if (type && type.toLowerCase() === 'article') {
                    journalCounts[journalName] = (journalCounts[journalName] || 0) + 1;
                } else if (type && type.toLowerCase() === 'inproceedings') {
                    conferenceCounts[journalName] = (conferenceCounts[journalName] || 0) + 1; // Use journal cell content for conf name
                }
            }
        }
    });
    // Sort and filter results (count >= 1)
    const sortedJournals = Object.entries(journalCounts)
        .filter(([name, count]) => count >= 1) // Filter after counting
        .sort((a, b) => b[1] - a[1]); // Sort by count descending
    const sortedConferences = Object.entries(conferenceCounts)
        .filter(([name, count]) => count >= 1) // Filter after counting
        .sort((a, b) => b[1] - a[1]); // Sort by count descending
    return {
        journals: sortedJournals.map(([name, count]) => ({ name, count })),
        conferences: sortedConferences.map(([name, count]) => ({ name, count }))
    };
}

function calculateCumulativeData(originalDataArray) {
    if (!originalDataArray || originalDataArray.length === 0) return [];
    const cumulativeData = [];
    let sum = 0;
    for (let i = 0; i < originalDataArray.length; i++) {
        sum += originalDataArray[i];
        cumulativeData.push(sum);
    }
    return cumulativeData;
}

/* ----------  AUTO-ORDER DATASETS WHEN STACKED  ---------- */
function reorderDatasetsForStacking() {
    if (!isStacked) return;                // nothing to do when un-stacked
    const charts = [
        window.surveyVsImplLineChartInstance,
        window.techniquesPerYearLineChartInstance,
        window.featuresPerYearLineChartInstance,
        window.pubTypesPerYearLineChartInstance
    ].filter(Boolean);
    charts.forEach(chart => {
        const { datasets } = chart.data;
        /* Build an array of { datasetIndex, total } using the CURRENT data
           (already cumulative if cumulative is on) */
        const totals = datasets.map((ds, idx) => ({
            idx,
            total: ds.data.reduce((a, b) => a + b, 0)
        }));
        // totals.sort((A, B) => B.total - A.total);        /* Sort descending by total */
        totals.sort((A, B) => A.total - B.total);            /* Sort ascending by total (smallest first) to put smallest on bottom when stacked */
        /* Re-order only the datasets array (colours/labels stay intact) */
        chart.data.datasets = totals.map(t => datasets[t.idx]);
        chart.update();
    });
}

/* ----------  cumulative total in legend: Kimi K2 ---------- */
function cumulativeLegendLabels(chart) {
    const defaults = Chart.defaults.plugins.legend.labels.generateLabels;
    const labels = defaults.call(this, chart);   // keep default click behaviour
    if (!isCumulative) return labels;                // nothing to do
    labels.forEach(lbl => {
        const ds = chart.data.datasets[lbl.datasetIndex];
        const data = ds.data;
        const last = (Array.isArray(data) && data.length)
            ? data[data.length - 1]           // largest cumulative value
            : 0;
        lbl.text = `${lbl.text}  (${last})`;         // append total
    });
    return labels;
}

function buildStatsLists() {
    const stats = {
        journals: {},
        conferences: {},
        keywords: {},
        authors: {},
        researchAreas: {},
        otherDetectedFeatures: {},
        modelNames: {}
    };
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    visibleRows.forEach(row => {
        // --- Get Journal/Conference and Type (same as before) ---
        const journalCell = row.cells[journalCellIndex]; // Index 4 (Journal/Conf column)
        const typeCell = row.cells[typeCellIndex]; // Index 5 (Type column) - Assuming typeCellIndex is defined globally
        if (journalCell && typeCell) { // Ensure cells exist
            const journalConfName = journalCell.textContent.trim();
            const typeValue = (typeCell.getAttribute('title') || typeCell.textContent.trim()).toLowerCase(); // Use title if available, standardize case
            if (journalConfName) {
                // Determine if it's a journal or conference based on type
                // Common BibTeX types: 'article' -> journal, 'inproceedings', 'proceedings', 'conference' -> conference
                if (typeValue === 'article') {
                    stats.journals[journalConfName] = (stats.journals[journalConfName] || 0) + 1;
                } else if (typeValue === 'inproceedings' || typeValue === 'proceedings' || typeValue === 'conference') {
                    stats.conferences[journalConfName] = (stats.conferences[journalConfName] || 0) + 1;
                } else {
                    // Optional: Handle other types or log them if needed
                    // //console.log(`Unrecognized type for ${journalConfName}: ${typeValue}`);
                    // You could add them to a 'miscellaneous' category if desired
                }
            }
        }
        // --- Get data from hidden cells ---
        // Find the hidden cells by their data-field attribute within the current row
        const keywordsCell = row.querySelector('td[data-field="keywords"]');
        const authorsCell = row.querySelector('td[data-field="authors"]');
        const researchAreaCell = row.querySelector('td[data-field="research_area"]');
        const featuresOtherCell = row.querySelector('td[data-field="features_other"]');

        // --- Extract and Process Keywords ---
        if (keywordsCell) { // Check if the cell exists before accessing its content
            const keywordsText = keywordsCell.textContent.trim();
            if (keywordsText) {
                const keywordsList = keywordsText.split(';')
                    .map(kw => kw.trim())
                    .filter(kw => kw.length > 0);
                keywordsList.forEach(keyword => {
                    stats.keywords[keyword] = (stats.keywords[keyword] || 0) + 1;
                });
            }
        }

        // --- Extract and Process Authors ---
        if (authorsCell) { // Check if the cell exists before accessing its content
            const authorsText = authorsCell.textContent.trim();
            if (authorsText) {
                const authorsList = authorsText.split(';')
                    .map(author => author.trim())
                    .filter(author => author.length > 0);
                authorsList.forEach(author => {
                    stats.authors[author] = (stats.authors[author] || 0) + 1;
                });
            }
        }

        // --- Extract and Process Research Area ---
        if (researchAreaCell) { // Check if the cell exists before accessing its content
            const researchAreaText = researchAreaCell.textContent.trim();
            if (researchAreaText) {
                stats.researchAreas[researchAreaText] = (stats.researchAreas[researchAreaText] || 0) + 1;
            }
        }

        // --- Extract and Process Other Detected Features ---
        if (featuresOtherCell) { // Check if the cell exists before accessing its content
            const featuresOtherText = featuresOtherCell.textContent.trim();
            if (featuresOtherText) {
                const featuresList = featuresOtherText.split(';')
                    .map(f => f.trim())
                    .filter(f => f.length > 0);
                featuresList.forEach(feature => {
                    stats.otherDetectedFeatures[feature] = (stats.otherDetectedFeatures[feature] || 0) + 1;
                });
            }
        }

        // --- Extract and Process Model Names ---
        // IMPORTANT: Use the correct data-field attribute name for model names, likely 'model' based on updateCounts
        // The original code used 'model_name', but updateCounts looks for 'model'. Let's assume 'model' is correct here.
        // If your table uses 'model_name', change the selector accordingly.
        const modelNameCell = row.querySelector('td[data-field="model"]'); // Adjust selector if necessary
        if (modelNameCell) { // Check if the cell exists before accessing its content
             const modelNameText = modelNameCell.textContent.trim(); // Declare and assign modelNameText here
             if (modelNameText) { // Check if there's content
                 // Split the content by comma or semicolon
                 const modelNamesList = modelNameText.split(/[,;]/) // Split by comma or semicolon
                     .map(m => m.trim())
                     .filter(m => m.length > 0);
                 modelNamesList.forEach(modelName => {
                     stats.modelNames[modelName] = (stats.modelNames[modelName] || 0) + 1;
                 });
             }
        } else {
            // If 'model' field cell is not found, try 'model_name' as a fallback if needed
            const modelNameCellAlt = row.querySelector('td[data-field="model_name"]');
            if (modelNameCellAlt) {
                 const modelNameText = modelNameCellAlt.textContent.trim(); // Declare and assign modelNameText here
                 if (modelNameText) { // Check if there's content
                     // Split the content by comma or semicolon
                     const modelNamesList = modelNameText.split(/[,;]/) // Split by comma or semicolon
                         .map(m => m.trim())
                         .filter(m => m.length > 0);
                     modelNamesList.forEach(modelName => {
                         stats.modelNames[modelName] = (stats.modelNames[modelName] || 0) + 1;
                     });
                 }
            }
            // If neither 'model' nor 'model_name' is found, do nothing for this row regarding model names.
        }

    });

    function populateList(listElementId, dataObj) {
        const listElement = document.getElementById(listElementId);
        if (!listElement) {
            console.warn(`List element with ID ${listElementId} not found.`);
            return;
        }
        listElement.innerHTML = '';
        const sortedEntries = Object.entries(dataObj)
            .filter(([name, count]) => count >= 1) // Keep only entries with count >= 1 (changed from > 1 if desired)
            .sort((a, b) => {
                if (b[1] !== a[1]) {
                    return b[1] - a[1];
                }
                return a[0].localeCompare(b[0]);
            });
        if (sortedEntries.length === 0) {
            listElement.innerHTML = '<li>No items with count >= 1.</li>'; // Changed message
            return;
        }
        sortedEntries.forEach(([name, count]) => {
            const listItem = document.createElement('li');
            // Escape HTML to prevent XSS if data contains special characters
            const escapedName = name.replace(/&/g, "&amp;").replace(/</g, "<").replace(/>/g, ">");
            const escapedNameForTitle = escapedName.replace(/"/g, "&quot;"); // Escape quotes for title attribute
            // Create the list item content with count, search button, and name
            listItem.innerHTML = `<span class="count">${count}</span><button type="button" class="search-item-btn" title="Search for &quot;${escapedNameForTitle}&quot;">🔍</button><span class="name">${escapedName}</span>`;
            listElement.appendChild(listItem);
        });
        listElement.querySelectorAll('.search-item-btn').forEach(button => {
            button.addEventListener('click', function() {
                const listItem = this.closest('li');
                const nameSpan = listItem.querySelector('.name');
                if (nameSpan) {
                    const searchTerm = nameSpan.textContent.trim();
                    searchInput.value = searchTerm; // Set the search input value
                    closeModal(); // Close the stats modal
                    applyLocalFilters(); // Trigger the filter update
                }
            });
        });
    }

    // Function to populate lists where items *can* appear only once (no >= 1 filter)
    function populateSimpleList(listElementId, dataObj) {
        const listElement = document.getElementById(listElementId);
        if (!listElement) {
            console.warn(`List element with ID ${listElementId} not found.`);
            return;
        }
        listElement.innerHTML = '';
        // Sort entries: primarily by count (descending), then alphabetically (ascending) for ties
        const sortedEntries = Object.entries(dataObj)
            .sort((a, b) => {
                if (b[1] !== a[1]) {
                    return b[1] - a[1]; // Sort by count descending
                }
                return a[0].localeCompare(b[0]); // Sort alphabetically ascending if counts are equal
            });
        if (sortedEntries.length === 0) {
            listElement.innerHTML = '<li>No items found.</li>';
            return;
        }
        sortedEntries.forEach(([name, count]) => {
            const listItem = document.createElement('li');
            // Escape HTML to prevent XSS if data contains special characters
            const escapedName = name.replace(/&/g, "&amp;").replace(/</g, "<").replace(/>/g, ">");
            const escapedNameForTitle = escapedName.replace(/"/g, "&quot;"); // Escape quotes for title attribute
            // Create the list item content with count, search button, and name
            listItem.innerHTML = `<span class="count">${count}</span><button type="button" class="search-item-btn" title="Search for &quot;${escapedNameForTitle}&quot;">🔍</button><span class="name">${escapedName}</span>`;
            listElement.appendChild(listItem);
        });
        listElement.querySelectorAll('.search-item-btn').forEach(button => {
            button.addEventListener('click', function() {
                const listItem = this.closest('li');
                const nameSpan = listItem.querySelector('.name');
                if (nameSpan) {
                    const searchTerm = nameSpan.textContent.trim();
                    searchInput.value = searchTerm; // Set the search input value
                    closeModal(); // Close the stats modal
                    applyLocalFilters(); // Trigger the filter update
                }
            });
        });
    }

    populateList('keywordStatsList', stats.keywords);
    populateList('authorStatsList', stats.authors);
    populateList('researchAreaStatsList', stats.researchAreas);
    populateSimpleList('otherDetectedFeaturesStatsList', stats.otherDetectedFeatures);
    populateSimpleList('modelNamesStatsList', stats.modelNames);

    // ---- now the lists exist; build cloud if switch is on ----
    if (document.getElementById('cloudToggle').checked) {
        toggleCloud();                     // first render
    }
}

// --- Refactored Chart Data Preparation Functions ---
function prepareSMTvsTHTData() {
    const smtCount = latestCounts['is_smt'] || 0;
    const thtCount = latestCounts['is_through_hole'] || 0;
    return {
        labels: ['SMT', 'THT'],
        datasets: [{
            label: 'SMT vs THT Distribution',
            data: [smtCount, thtCount],
            backgroundColor: [
                'hsla(180, 32%, 52%, 0.95)', // Teal (from techniques)
                'hsla(260, 60%, 66%, 0.95)'  // Purple (from techniques)
            ],
            borderColor: "#333",
            borderWidth: 1,
            hoverOffset: 4
        }]
    };
}

function prepareScopeData(totalVisiblePaperCount, totalAllPaperCount) {
    let ontopicCount = 0;
    let offtopicCount = 0;

    if (document.body.id === 'html-export') {
        const allRowsInExport = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
        const totalRowsInExportLoaded = allRowsInExport.length;
        ontopicCount = totalVisiblePaperCount;
        offtopicCount = Math.max(0, totalRowsInExportLoaded - totalVisiblePaperCount);
    } else {
        ontopicCount = totalVisiblePaperCount;
        offtopicCount = Math.max(0, totalAllPaperCount - totalVisiblePaperCount); // Ensure non-negative
    }

    //console.log(`[prepareScopeData] Document ID: ${document.body.id}, Total Loaded (Export) / Total DB (Main): ${document.body.id === 'html-export' ? document.querySelectorAll('#papersTable tbody tr[data-paper-id]').length : totalAllPaperCount}, Visible (On-topic): ${ontopicCount}, Calculated Off-topic: ${offtopicCount}`); // Debug log

    return {
        labels: ['On-topic', 'Off-topic'],
        datasets: [{
            label: 'Dataset Scope (On-topic vs Off-topic)',
            data: [ontopicCount, offtopicCount],
            backgroundColor: [
                'hsla(96, 66%, 49%, 0.95)', // Green (from techniques)
                'hsla(347, 60%, 69%, 0.95)'  // Red (from techniques)
            ],
            borderColor: "#333",
            borderWidth: 1,
            hoverOffset: 4
        }]
    };
}

function prepareFeaturesData() {
    if (showPieCharts) {
        // --- Data for Pie Chart (Conditional Grouping Based on featureGroupToggle) ---
        let labels = [];
        let values = [];
        let backgroundColors = [];

        if (featureGroupToggle && featureGroupToggle.checked) {
            // --- Grouped Pie Chart Data ---
            // Calculate aggregated values based on featureColorGroups
            Object.keys(featureColorGroups).forEach(baseColorIndex => {
                const group = featureColorGroups[baseColorIndex];
                labels.push(group.label); // Use the group's label (e.g., 'PCB Features')
                // Sum the counts for all features within this group
                let groupSum = 0;
                group.fields.forEach(field => {
                    groupSum += (latestCounts[field] || 0);
                });
                values.push(groupSum);
                // Use the color associated with the base index for this group
                const colorIndex = parseInt(baseColorIndex);
                backgroundColors.push(featuresColorsOriginalOrder[colorIndex]);
            });
        } else {
            // --- Ungrouped Pie Chart Data (Shows Individual Features) ---
            // Use the same logic as the ungrouped bar chart
            const featuresData = FEATURE_FIELDS.map(field => ({
                label: FIELD_LABELS[field] || field,
                value: latestCounts[field] || 0,
                originalIndex: FEATURE_FIELD_INDEX_MAP[field] !== undefined ? FEATURE_FIELD_INDEX_MAP[field] : -1 // Get original color index
            }));

            // Determine if sorting is enabled based on the checkbox state (applies to ungrouped pie too)
            let processedData = featuresData; // Default to original order
            processedData = [...featuresData].sort((a, b) => b.value - a.value); // Use spread to avoid mutating original

            // Extract labels, values, and corresponding colors from the processed (or original) data
            labels = processedData.map(item => item.label);
            values = processedData.map(item => item.value);
            backgroundColors = processedData.map(item => featuresColorsOriginalOrder[item.originalIndex] || 'rgba(0,0,0,0.1)');
        }

        return {
            labels: labels,
            datasets: [{
                label: 'Features Count',
                data: values,
                backgroundColor: backgroundColors,
                borderColor: "#333",         // fixed color as the translucent mapping lacks contrast for bar or pie charts
                borderWidth: 1,
                hoverOffset: 4
            }]
        };
    } else {
        // --- Data for Bar Chart (Conditional Sorting Within Groups) ---
        let finalFeaturesLabels = [];
        let finalFeaturesValues = [];
        let finalFeaturesBackgroundColors = [];

        if (featureGroupToggle && featureGroupToggle.checked) {
            // --- Sorting Enabled: Sort each group by value, then concatenate ---
            Object.keys(featureColorGroups).forEach(baseColorIndexStr => {
                const baseColorIndex = parseInt(baseColorIndexStr);
                const group = featureColorGroups[baseColorIndex];
                const groupFields = group.fields;

                // Create an array of objects for this group's fields with their data and original index
                const groupData = groupFields.map(field => ({
                    label: FIELD_LABELS[field] || field,
                    value: latestCounts[field] || 0,
                    originalIndex: FEATURE_FIELD_INDEX_MAP[field] !== undefined ? FEATURE_FIELD_INDEX_MAP[field] : -1
                }));

                // Sort *within* this group by value descending
                groupData.sort((a, b) => b.value - a.value);

                // Append the sorted data for this group to the final arrays
                groupData.forEach(item => {
                    finalFeaturesLabels.push(item.label);
                    finalFeaturesValues.push(item.value);
                    // Use the color associated with the *base* color index for the group
                    // This ensures all items in the group have the same color
                    finalFeaturesBackgroundColors.push(featuresColorsOriginalOrder[baseColorIndex]);
                });
            });
        } else {
            // --- Data for Bar Chart (Conditional Sorting) ---
            const featuresData = FEATURE_FIELDS.map(field => ({
                label: FIELD_LABELS[field] || field,
                value: latestCounts[field] || 0,
                originalIndex: FEATURE_FIELD_INDEX_MAP[field] !== undefined ? FEATURE_FIELD_INDEX_MAP[field] : -1 // Get original color index
            }));

            // Determine if sorting is enabled based on the checkbox state
            let processedData = featuresData; // Default to original order
            processedData = [...featuresData].sort((a, b) => b.value - a.value); // Use spread to avoid mutating original
            // If checkbox is not checked or doesn't exist, processedData remains as original featuresData

            // Extract labels, values, and corresponding colors from the processed (or original) data
            finalFeaturesLabels = processedData.map(item => item.label);
            finalFeaturesValues = processedData.map(item => item.value);
            finalFeaturesBackgroundColors = processedData.map(item => featuresColorsOriginalOrder[item.originalIndex] || 'rgba(0,0,0,0.1)');
            // const finalFeaturesBorderColors = processedData.map(item => featuresBorderColorsOriginalOrder[item.originalIndex] || 'rgba(0,0,0,1)'); // If needed later
        }

        return {
            labels: finalFeaturesLabels,
            datasets: [{
                label: 'Features Count',
                data: finalFeaturesValues,
                backgroundColor: finalFeaturesBackgroundColors, // Now reflects grouped sorting if enabled
                borderColor: "#333",         // fixed color as the translucent mapping lacks contrast for bar or pie charts
                borderWidth: 1,
                hoverOffset: 4
            }]
        };
    }
}

function prepareTechniquesData() {
    const TECHNIQUE_FIELDS_NO_DATASET = TECHNIQUE_FIELDS_ALL.filter(field => field !== 'technique_available_dataset');
    // Read and sort the data for the distribution chart
    const techniquesData = TECHNIQUE_FIELDS_NO_DATASET.map(field => ({
        label: FIELD_LABELS[field] || field,
        value: latestCounts[field] || 0,
        originalIndex: TECHNIQUE_FIELD_COLOR_MAP[field] !== undefined ? TECHNIQUE_FIELD_COLOR_MAP[field] : -1 // Get original color index
    }));
    // Sort by value descending (largest first) for the distribution chart display
    techniquesData.sort((a, b) => b.value - a.value);
    // Extract sorted labels and values
    const sortedTechniquesLabels = techniquesData.map(item => item.label);
    const sortedTechniquesValues = techniquesData.map(item => item.value);
    // Map the sorted order back to the original colors using the stored originalIndex
    const sortedTechniquesBackgroundColors = techniquesData.map(item => techniquesColors[item.originalIndex] || 'rgba(0,0,0,0.1)');
    // const sortedTechniquesBorderColors = techniquesData.map(item => techniquesBorderColors[item.originalIndex] || 'rgba(0,0,0,1)');
    return {
        labels: sortedTechniquesLabels,
        datasets: [{
            label: 'Techniques Count',
            data: sortedTechniquesValues,
            backgroundColor: sortedTechniquesBackgroundColors, // Use mapped colors
            borderColor: "#333",         // fixed color as the translucent mapping lacks contrast for bar or pie charts
            borderWidth: 1,
            hoverOffset: 4
        }]
    };
}

function prepareSurveyVsImplDistData(totalVisiblePaperCount) {
    // Use the correct counts from latestCounts and total visible papers
    const surveyCount = latestCounts['is_survey'] || 0;
    // Calculate implementation count: total visible - survey count
    const implCount = totalVisiblePaperCount - surveyCount;
    return {
        labels: ['Survey', 'Primary'],
        datasets: [{
            label: 'Survey vs Primary Distribution',
            data: [
                surveyCount,
                implCount
            ],
            backgroundColor: [
                'hsla(204, 42%, 67%, 0.95)', // Blue (from line chart)
                'hsla(53, 50%, 69%, 0.95)' // Red-like (from line chart, adjusted hue/lightness)
            ],
            borderColor: "#333",
            borderWidth: 1,
            hoverOffset: 4
        }]
    };
}

function preparePubTypesDistData() {
    // Get unique types that actually appear in the *currently visible* data (from latestYearlyData.pubTypes)
    // This replicates the original logic more closely.
    const allPubTypesSet = new Set();
    // Iterate through the yearly data collected for *visible* rows
    Object.values(latestYearlyData.pubTypes || {}).forEach(yearData => {
        // Add the raw type keys (e.g., 'article', 'inproceedings') found in the data to the set
        Object.keys(yearData).forEach(rawType => allPubTypesSet.add(rawType));
    });
    // Convert the set to an array of *actual* types present
    const allPubTypes = Array.from(allPubTypesSet).sort(); // Sort for consistent order

    // Calculate the total count for each *actual* type found above
    const pubTypesDistData = allPubTypes.map(rawType => {
        let count = 0;
        // Sum the counts for this raw type across all years in the collected data
        Object.values(latestYearlyData.pubTypes || {}).forEach(yearData => {
            count += yearData[rawType] || 0;
        });
        return count;
    });

    // Translate the *actual* raw type names into the user-friendly labels using the map
    const pubTypesDistLabels = allPubTypes.map(rawType => mapPubType(rawType));

    // Generate colors dynamically based on the index of the *actual* types found (not the full map)
    const pubTypesDistColors = allPubTypes.map((rawType, index) => {
        const hue = (index * 137.508) % 360; // Golden angle approximation for spread
        return `hsla(${hue}, 30%, 65%, 0.85)`; // Slightly transparent for contrast
    });

    return {
        labels: pubTypesDistLabels, // Use the translated labels for the *actual* types
        datasets: [{
            label: 'Publication Types Distribution',
            data: pubTypesDistData, // Use the counts for the *actual* types
            backgroundColor: pubTypesDistColors, // Use colors for the *actual* types
            borderColor: "#333",
            borderWidth: 1,
            hoverOffset: 4
        }]
    };
}

function prepareRelevanceHistogramData(visibleRows) {
    const relevanceCounts = Array(11).fill(0); // Index 0-10 for scores 0-10
    visibleRows.forEach(row => {
        const relevanceCell = row.cells[relevanceCellIndex]; // Assume relevanceCellIndex is defined globally
        if (relevanceCell) {
            const relevanceText = relevanceCell.textContent.trim();
            const relevanceScore = parseInt(relevanceText, 10);
            if (!isNaN(relevanceScore) && relevanceScore >= 0 && relevanceScore <= 10) {
                relevanceCounts[relevanceScore]++;
            }
        }
    });
    return {
        labels: Array.from({ length: 11 }, (_, i) => i.toString()), // Labels "0", "1", ..., "10"
        datasets: [{
            label: 'Relevance Histogram',
            data: relevanceCounts,
            backgroundColor: 'hsla(204, 62%, 57%, 0.95)', // Blue (from techniques)
            borderColor: 'hsla(204, 82%, 28%, 0.75)', // Darker Blue border
            borderWidth: 1
        }]
    };
}

function prepareEstScoreHistogramData(visibleRows) {
    const estScoreCounts = Array(11).fill(0); // Index 0-10 for scores 0-10
    visibleRows.forEach(row => {
        const estScoreCell = row.cells[estScoreCellIndex]; // Assume estScoreCellIndex is defined globally
        if (estScoreCell) {
            const estScoreText = estScoreCell.textContent.trim();
            const estScore = parseInt(estScoreText, 10);
            if (!isNaN(estScore) && estScore >= 0 && estScore <= 10) {
                estScoreCounts[estScore]++;
            }
        }
    });
    return {
        labels: Array.from({ length: 11 }, (_, i) => i.toString()), // Labels "0", "1", ..., "10"
        datasets: [{
            label: 'Estimated Score Histogram',
            data: estScoreCounts,
            backgroundColor: 'hsla(52, 80%, 47%, 0.95)', // Yellow (from techniques)
            borderColor: 'hsla(42, 100%, 28%, 0.75)', // Darker Yellow border
            borderWidth: 1
        }]
    };
}

// --- Refactored Chart Rendering Functions ---
function destroyExistingCharts() {
    const chartInstances = [
        'featuresBarChartInstance', 'techniquesBarChartInstance',
        'surveyVsImplLineChartInstance', 'techniquesPerYearLineChartInstance',
        'featuresPerYearLineChartInstance', 'pubTypesPerYearLineChartInstance',
        'surveyVsImplDistChartInstance', 'pubTypesDistChartInstance',
        'smtVsThtDistChartInstance', 'scopeDistChartInstance',
        'relevanceHistogramInstance', 'estScoreHistogramInstance'
    ];
    chartInstances.forEach(instanceName => {
        if (window[instanceName]) {
            window[instanceName].destroy();
            delete window[instanceName];
        }
    });
}

// Helper function to determine label position based on bar value
function getBarLabelPosition(value, maxBarValue) {
    const halfMax = maxBarValue / 2;
    if (value < halfMax) {
        return { align: 'end', anchor: 'end' }; // Inside the bar at the end (right side for horizontal bars)
    } else {
        return { align: 'start', anchor: 'end' }; // Outside the bar at the end (right side for horizontal bars)
    }
}
function renderBarOrPieChart(ctx, chartData, chartLabel, chartType) {
    const isBar = chartType === 'bar';
    let datalabelsPluginConfig = {};
    let datalabelsPlugin = [];

    /* -------------------------------------------------
       1.  HORIZONTAL BAR – keep the old “smart” labels
       ------------------------------------------------- */

    if (isBar && ChartDataLabels) {
        // Calculate the maximum value across all datasets for this chart
        let maxBarValue = 0;
        if (chartData.datasets && chartData.datasets.length > 0) {
            chartData.datasets.forEach(dataset => {
                if (dataset.data && Array.isArray(dataset.data)) {
                    const datasetMax = Math.max(...dataset.data.map(v => Math.abs(v))); // Use abs in case of negative values
                    if (datasetMax > maxBarValue) {
                        maxBarValue = datasetMax;
                    }
                }
            });
        }

        datalabelsPluginConfig = {
            datalabels: {
                // Use a formatter function to return the value or an empty string if 0
                formatter: value => value > 0 ? value : '',
                color: '#444',
                font: { size: 11, weight: '400' },
                anchor: function(context) {
                    // Determine anchor based on value and maxBarValue
                    const value = context.dataset.data[context.dataIndex];
                    return getBarLabelPosition(value, maxBarValue).anchor;
                },
                align: function(context) {
                    // Determine align based on value and maxBarValue
                    const value = context.dataset.data[context.dataIndex];
                    return getBarLabelPosition(value, maxBarValue).align;
                },
                offset: 4 // Consistent offset for both inside and outside
            }
        };
        datalabelsPlugin = [ChartDataLabels];
    }

    /* -------------------------------------------------
       2.  PIE – show percentage inside every slice
       ------------------------------------------------- */
       //known issue: the percentages are right only when all slices are enabled!
    if (!isBar && ChartDataLabels) {
        datalabelsPluginConfig = {
            datalabels: {
                color: '#444',
                font: ctx => {                       // ← dynamic font
                    const h = ctx.chart.width || 280; // fallback
                    return {
                        size: Math.max(10, h * 0.035), // 10 px minimum
                        weight: '300'
                    };
                },
                anchor: 'end',
                align: 'start',
                offset: -2,
                formatter: (value, ctx) => {
                    const sum = ctx.dataset.data.reduce((a, b) => a + b, 0);
                    const pct = sum ? Math.round((value / sum) * 100) : 0;
                    return pct > 3  ? pct + '%' : '';
                }
            }
        };
        datalabelsPlugin = [ChartDataLabels];
    }

    /* -------------------------------------------------
       3.  Common Chart.js config
       ------------------------------------------------- */
    const options = {
        type: chartType,
        data: chartData,
        options: {
            ...(isBar ? { indexAxis: 'y' } : { radius: '90%' }),
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: getChartDPR(),
            plugins: {
                legend: {
                    display: !isBar,
                    position: 'top',
                    labels: { usePointStyle: true, pointStyle: 'circle' }
                },
                title: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.label}: ${ctx.raw}`
                    }
                },
                ...datalabelsPluginConfig
            },
            scales: {
                ...(isBar ? { x: { beginAtZero: true, ticks: { precision: 0 } } } : {})
            }
        },
        plugins: datalabelsPlugin
    };

    return new Chart(ctx, options);
}


function renderHistogram(ctx, chartData, title) {
    const options = {
        type: 'bar',
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: getChartDPR(),
            plugins: {
                legend: { display: false },
                title: { display: false, text: title }
            },
            scales: {
                x: {
                    title: {
                        display: false,
                        text: title.split(' ')[0] // Use first word as axis label (Relevance/Estimated)
                    },
                    ticks: { precision: 0 }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Frequency'
                    },
                    beginAtZero: true,
                    ticks: { precision: 0 }
                }
            }
        }
    };
    return new Chart(ctx, options);
}

function renderLineCharts() {
    const surveyImplData = latestYearlyData.surveyImpl || {};
    const yearsForSurveyImpl = Object.keys(surveyImplData).map(Number).sort((a, b) => a - b);
    const surveyCounts = yearsForSurveyImpl.map(year => surveyImplData[year].surveys || 0);
    const implCounts = yearsForSurveyImpl.map(year => surveyImplData[year].impl || 0);
    let surveyCountsFinal = surveyCounts;
    let implCountsFinal = implCounts;
    if (isCumulative) {
        surveyCountsFinal = calculateCumulativeData(surveyCounts);
        implCountsFinal = calculateCumulativeData(implCounts);
    }

    const surveyVsImplCtx = document.getElementById('surveyVsImplLineChart')?.getContext('2d');
    window.surveyVsImplLineChartInstance = new Chart(surveyVsImplCtx, {
        type: 'line',
        data: {
            labels: yearsForSurveyImpl,
            datasets: [
                {
                    label: 'Survey Papers',
                    data: surveyCountsFinal, // Use final data array
                    borderColor: 'hsl(204, 42%, 37%)', // Blue
                    backgroundColor: 'hsla(204, 42%, 67%, 0.95)',
                    fill: isStacked, // Fill is controlled by stacked option below
                    tension: 0.25
                },
                {
                    label: 'Primary Papers',
                    data: implCountsFinal, // Use final data array
                    borderColor: 'hsla(38, 70%, 49%, 1.00)', // Red
                    backgroundColor: 'hsla(42, 50%, 69%, 0.95)',
                    fill: isStacked, // Fill is controlled by stacked option below
                    tension: 0.25
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: getChartDPR(),
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        usePointStyle: true,  // Use the point style
                        pointStyle: 'circle',  // Specify the circle style
                        generateLabels: cumulativeLegendLabels   // <-- added
                    }
                },
                title: { display: false, text: 'Survey vs Primary Papers per Year' },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            return `${context.dataset.label}: ${context.raw}`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { precision: 0 },
                    stacked: isStacked // Apply stacking to Y-axis
                },
                x: {
                    ticks: { precision: 0 },
                    stacked: isStacked // Apply stacking to X-axis if needed (usually not for line charts, but for bar compatibility)
                }
            }
        }
    });

    // 2. Techniques per Year (Consistent Colors)
    const techniquesYearlyData = latestYearlyData.techniques || {};
    const yearsForTechniques = Object.keys(techniquesYearlyData).map(Number).sort((a, b) => a - b);
    // Create datasets for the line chart using the ORIGINAL field order and ORIGINAL colors
    // This ensures color consistency regardless of sorting in the bar chart
    const techniqueLineDatasets = TECHNIQUE_FIELDS_FOR_YEARLY.map(field => {
        const label = (typeof FIELD_LABELS !== 'undefined' && FIELD_LABELS[field]) ? FIELD_LABELS[field] : field;
        let data = yearsForTechniques.map(year => techniquesYearlyData[year]?.[field] || 0);
        if (isCumulative) {
            data = calculateCumulativeData(data);
        }
        const originalIndex = TECHNIQUE_FIELD_COLOR_MAP[field] !== undefined ? TECHNIQUE_FIELD_COLOR_MAP[field] : -1;
        // --- FIX: Use techniquesBorderColors for border, techniquesColors for background ---
        const borderColor = (originalIndex !== -1 && techniquesBorderColors[originalIndex]) ? techniquesBorderColors[originalIndex] : 'rgba(0, 0, 0, 1)'; // Use border colors array
        const backgroundColor = (originalIndex !== -1 && techniquesColors[originalIndex]) ? techniquesColors[originalIndex] : 'rgba(0, 0, 0, 0.1)'; // Use fill colors array (usually with alpha for line charts when stacked)
        return {
            label: label,
            data: data, // Use final data array
            borderColor: borderColor,       // Use the dedicated border color
            backgroundColor: backgroundColor, // Use the dedicated fill color (often with alpha)
            fill: isStacked, // Fill is controlled by stacked option below
            tension: 0.25
        };
    });

    const techniquesPerYearCtx = document.getElementById('techniquesPerYearLineChart')?.getContext('2d');
    if (techniquesPerYearCtx && techniqueLineDatasets.length > 0) {
        window.techniquesPerYearLineChartInstance = new Chart(techniquesPerYearCtx, {
            type: 'line',
            data: {
                labels: yearsForTechniques, // Use years sorted
                datasets: techniqueLineDatasets // Use datasets prepared with consistent colors
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            usePointStyle: true,  // Use the point style
                            pointStyle: 'circle',  // Specify the circle style
                            generateLabels: cumulativeLegendLabels   // <-- added
                        }
                    },
                    title: { display: false, text: 'Techniques per Year' },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return `${context.dataset.label}: ${context.raw}`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        stacked: isStacked // Apply stacking to Y-axis
                    },
                    x: {
                        ticks: { precision: 0 },
                        stacked: isStacked // Apply stacking to X-axis if needed
                    }
                }
            }
        });
    } else if (techniquesPerYearCtx) {
        window.techniquesPerYearLineChartInstance = new Chart(techniquesPerYearCtx, {
            type: 'line',
            data: { labels: [], datasets: [] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Techniques per Year (No Data)' }
                }
            }
        });
    }

    // 3. Features per Year (Summed by Color Group)
    const featuresYearlyData = latestYearlyData.features || {};
    const yearsForFeatures = Object.keys(featuresYearlyData).map(Number).sort((a, b) => a - b);
    // --- Create Aggregated Data by Color Group ---
    // Aggregate yearly data for each color group
    const aggregatedFeatureDataByColor = {};
    Object.keys(featureColorGroups).forEach(baseColorIndex => {
        const group = featureColorGroups[baseColorIndex];
        aggregatedFeatureDataByColor[group.label] = yearsForFeatures.map(year => {
            return group.fields.reduce((sum, field) => {
                return sum + (featuresYearlyData[year]?.[field] || 0);
            }, 0);
        });
    });

    const aggregatedFeatureDataByColorFinal = {};
    Object.keys(aggregatedFeatureDataByColor).forEach(label => {
        let data = aggregatedFeatureDataByColor[label];
        if (isCumulative) {
            data = calculateCumulativeData(data);
        }
        aggregatedFeatureDataByColorFinal[label] = data;
    });

    // Create datasets for the line chart using the aggregated data and corresponding colors
    const featureLineDatasets = Object.keys(featureColorGroups).map(baseColorIndex => {
        const group = featureColorGroups[baseColorIndex];
        const colorIndex = parseInt(baseColorIndex); // Use the base color index to get the actual color
        // --- FIX: Use featuresBorderColorsOriginalOrder for border, featuresColorsOriginalOrder for background ---
        const borderColor = (featuresBorderColorsOriginalOrder[colorIndex]) ? featuresBorderColorsOriginalOrder[colorIndex] : 'rgba(0, 0, 0, 1)'; // Use border colors array
        const backgroundColor = (featuresColorsOriginalOrder[colorIndex]) ? featuresColorsOriginalOrder[colorIndex] : 'rgba(0, 0, 0, 0.1)'; // Use fill colors array (usually with alpha for line charts when stacked)
        // --- END FIX ---
        return {
            label: group.label,
            data: aggregatedFeatureDataByColorFinal[group.label], // Use final data array
            borderColor: borderColor,       // Use the dedicated border color
            backgroundColor: backgroundColor, // Use the dedicated fill color (often with alpha)
            fill: isStacked, // Fill is controlled by stacked option below
            tension: 0.25
        };
    });

    const featuresPerYearCtx = document.getElementById('featuresPerYearLineChart')?.getContext('2d');
    if (featuresPerYearCtx && featureLineDatasets.length > 0) {
        window.featuresPerYearLineChartInstance = new Chart(featuresPerYearCtx, {
            type: 'line',
            data: {
                labels: yearsForFeatures, // Use years sorted
                datasets: featureLineDatasets // Use datasets prepared with aggregated data and consistent colors
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            usePointStyle: true,  // Use the point style
                            pointStyle: 'circle',  // Specify the circle style
                            generateLabels: cumulativeLegendLabels   // <-- added
                        }
                    },
                    title: { display: false, text: 'Features per Year' },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return `${context.dataset.label}: ${context.raw}`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        stacked: isStacked // Apply stacking to Y-axis
                    },
                    x: {
                        ticks: { precision: 0 },
                        stacked: isStacked // Apply stacking to X-axis if needed
                    }
                }
            }
        });
    } else if (featuresPerYearCtx) {
        window.featuresPerYearLineChartInstance = new Chart(featuresPerYearCtx, {
            type: 'line',
            data: { labels: [], datasets: [] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Features per Year (No Data)' }
                }
            }
        });
    }

    // --- 4. Publication Types per Year (Translated Labels) ---
    const pubTypesYearlyData = latestYearlyData.pubTypes || {};
    const yearsForPubTypes = Object.keys(pubTypesYearlyData).map(Number).sort((a, b) => a - b);
    // Create datasets for the line chart, one for each publication type
    const allPubTypes = Object.keys(PUB_TYPE_MAP); // Or get from yearly data if needed
    const pubTypeLineDatasets = allPubTypes.map((type, index) => { // Use original types for data fetching
        // Generate a distinct color for each type (simple hue rotation)
        // You might want to use a more sophisticated color palette
        const hue = (index * 137.508) % 360; // Golden angle approximation for spread
        const borderColor = `hsl(${hue}, 40%, 40%)`;
        const backgroundColor = `hsla(${hue}, 30%, 65%, 0.85)`;
        let data = yearsForPubTypes.map(year => pubTypesYearlyData[year]?.[type] || 0);
        if (isCumulative) {
            data = calculateCumulativeData(data);
        }
        return {
            label: mapPubType(type),
            data: data, // Use final data array
            borderColor: borderColor,
            backgroundColor: backgroundColor,
            fill: isStacked, // Fill is controlled by stacked option below
            tension: 0.25,
            hidden: false // Start visible
        };
    });

    // --- Render the Publication Types per Year Line Chart ---
    const pubTypesPerYearCtx = document.getElementById('pubTypesPerYearLineChart')?.getContext('2d'); // Get context for pub types chart
    if (pubTypesPerYearCtx && pubTypeLineDatasets.length > 0) {
        window.pubTypesPerYearLineChartInstance = new Chart(pubTypesPerYearCtx, {
            type: 'line',
            data: {
                labels: yearsForPubTypes, // Use sorted years
                datasets: pubTypeLineDatasets // Use datasets prepared above (with mapped labels)
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            usePointStyle: true,
                            pointStyle: 'circle',
                            generateLabels: cumulativeLegendLabels
                        }
                    },
                    title: { display: false, text: 'Publication Types per Year' },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                // Tooltip will now show the mapped label (e.g., "Journal", "Conference")
                                return `${context.dataset.label}: ${context.raw}`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        title: {
                            display: false,
                            text: 'Count'
                        },
                        stacked: isStacked // Apply stacking to Y-axis
                    },
                    x: {
                        ticks: { precision: 0 },
                        title: {
                            display: false,
                            text: 'Year'
                        },
                        stacked: isStacked // Apply stacking to X-axis if needed
                    }
                }
            }
        });
    } else if (pubTypesPerYearCtx) {
        // Handle case where there's no data
        window.pubTypesPerYearLineChartInstance = new Chart(pubTypesPerYearCtx, {
            type: 'line',
            data: { labels: [], datasets: [] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Publication Types per Year (No Data)' }
                }
            }
        });
    }
    // This ensures datasets are reordered for stacking *after* they are rendered,
    // whether the render was due to initial display, stacking toggle, or cumulative toggle.
    reorderDatasetsForStacking();
}


// --- Refactored displayStats function ---
function displayStats() {
    document.documentElement.classList.add('busyCursor');
    
    setTimeout(() => {
        updateCounts(); // Run updateCounts to get the latest data for visible rows

        // Initialize color mappings
        TECHNIQUE_FIELDS_FOR_YEARLY.forEach((field, index) => { TECHNIQUE_FIELD_COLOR_MAP[field] = index; });
        FEATURE_FIELDS_FOR_YEARLY.forEach((field, index) => { FEATURE_FIELD_INDEX_MAP[field] = index; });

        // *** ADD THIS LINE: Clear the fields arrays in featureColorGroups ***
        Object.keys(featureColorGroups).forEach(key => {
            featureColorGroups[key].fields = [];
        });

        // Populate the groups with the actual feature fields
        FEATURE_FIELDS_FOR_YEARLY.forEach(field => {
            const originalIndex = FEATURE_FIELD_INDEX_MAP[field];
            const originalColorHSLA = featuresColorsOriginalOrder[originalIndex];
            // Find the base color index that matches this feature's color:
            let baseColorIndex = null;
            for (let key in featureColorGroups) {
                const keyIndex = parseInt(key);
                if (featuresColorsOriginalOrder[keyIndex] === originalColorHSLA) {
                    baseColorIndex = keyIndex;
                    break;
                }
            }
            if (baseColorIndex !== null && featureColorGroups[baseColorIndex]) {
                featureColorGroups[baseColorIndex].fields.push(field);
            } else {
                console.warn(`Could not find matching base color for feature ${field}`);
            }
        });

        // --- Read Counts and Paper Counts ---
        // Get the total number of currently visible papers directly
        const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
        const totalVisiblePaperCount = visibleRows.length;
        // Get the total number of *all* papers from the footer cell
        const totalPaperCountCell = document.getElementById('total-papers-count');
        const totalAllPaperCount = totalPaperCountCell ? parseInt(totalPaperCountCell.textContent.trim(), 10) : 0;

        // --- Destroy existing charts if they exist (important for re-renders) ---
        destroyExistingCharts();

        // --- Prepare and Render Charts ---
        Chart.defaults.font = {
            size: 12.5,
            family: 'Arial Narrow',
            weight: '300'
        };

        // --- Distribution Charts (Bar/Pie) ---
        const featuresCtx = document.getElementById('featuresPieChart')?.getContext('2d');
        const featuresChartData = prepareFeaturesData();
        window.featuresBarChartInstance = renderBarOrPieChart(featuresCtx, featuresChartData, 'Features Count', showPieCharts ? 'pie' : 'bar');

        const techniquesCtx = document.getElementById('techniquesPieChart')?.getContext('2d');
        const techniquesChartData = prepareTechniquesData();
        window.techniquesBarChartInstance = renderBarOrPieChart(techniquesCtx, techniquesChartData, 'Techniques Count', showPieCharts ? 'pie' : 'bar');

        const surveyVsImplDistCtx = document.getElementById('surveyVsImplPieChart')?.getContext('2d');
        const surveyVsImplDistChartData = prepareSurveyVsImplDistData(totalVisiblePaperCount);
        window.surveyVsImplDistChartInstance = renderBarOrPieChart(surveyVsImplDistCtx, surveyVsImplDistChartData, 'Survey vs Primary Distribution', showPieCharts ? 'pie' : 'bar');

        const pubTypesDistCtx = document.getElementById('publTypePieChart')?.getContext('2d');
        const pubTypesDistChartData = preparePubTypesDistData();
        window.pubTypesDistChartInstance = renderBarOrPieChart(pubTypesDistCtx, pubTypesDistChartData, 'Publication Types Distribution', showPieCharts ? 'pie' : 'bar');

        const smtVsThtCtx = document.getElementById('SMTvsTHTPieChart')?.getContext('2d');
        const smtVsThtDistChartData = prepareSMTvsTHTData();
        window.smtVsThtDistChartInstance = renderBarOrPieChart(smtVsThtCtx, smtVsThtDistChartData, 'SMT vs THT Distribution', showPieCharts ? 'pie' : 'bar');

        const scopeCtx = document.getElementById('OffTopicPieChart')?.getContext('2d');
        const scopeChartData = prepareScopeData(totalVisiblePaperCount, totalAllPaperCount);
        window.scopeDistChartInstance = renderBarOrPieChart(scopeCtx, scopeChartData, 'Dataset Scope (On-topic vs Off-topic)', showPieCharts ? 'pie' : 'bar');

        // --- Histogram Charts ---
        const relevanceHistogramCtx = document.getElementById('RelevanceHistogram')?.getContext('2d');
        const relevanceHistogramData = prepareRelevanceHistogramData(visibleRows);
        window.relevanceHistogramInstance = renderHistogram(relevanceHistogramCtx, relevanceHistogramData, 'Relevance Histogram');

        const estScoreHistogramCtx = document.getElementById('estScoreHistogram')?.getContext('2d');
        const estScoreHistogramData = prepareEstScoreHistogramData(visibleRows);
        window.estScoreHistogramInstance = renderHistogram(estScoreHistogramCtx, estScoreHistogramData, 'Estimated Score Histogram');

        // --- Line Charts ---
        renderLineCharts();

        // --- Populate Client-side Journal/Conference Lists ---
        const { journals, conferences } = calculateJournalConferenceStats();

        function populateListFromClient(listElementId, dataArray) { //for items with count >=2
            const listElement = document.getElementById(listElementId);
            listElement.innerHTML = '';
            if (!dataArray || dataArray.length === 0) {
                listElement.innerHTML = '<li><span class="count"><span class="name">No items with count > 1.</span></li>';
                return;
            }
            dataArray.forEach(item => {
                const listItem = document.createElement('li');
                const escapedName = (item.name || '').toString()
                    .replace(/&/g, "&amp;").replace(/</g, "<")
                    .replace(/>/g, ">").replace(/"/g, "&quot;")
                    .replace(/'/g, "&#39;");
                // --- Preserve Original Structure ---
                const countSpan = document.createElement('span');
                countSpan.className = 'count';
                countSpan.textContent = item.count;
                const nameSpan = document.createElement('span');
                nameSpan.className = 'name';
                nameSpan.textContent = escapedName;
                const searchButton = document.createElement('button');
                searchButton.type = 'button';
                searchButton.className = 'search-item-btn';
                searchButton.title = `Search for "${item.name}"`;
                searchButton.textContent = '🔍';
                searchButton.addEventListener('click', function (event) {
                    event.stopPropagation();
                    searchInput.value = item.name;
                    closeModal();
                    const inputEvent = new Event('input', { bubbles: true });
                    searchInput.dispatchEvent(inputEvent);
                });
                listItem.appendChild(countSpan);
                listItem.appendChild(searchButton);
                listItem.appendChild(nameSpan);
                listElement.appendChild(listItem);
            });
        }

        populateListFromClient('journalStatsList', journals);
        populateListFromClient('conferenceStatsList', conferences);

        // --- Populate Metrics Table ---
        function populateMetricsTableDirectly() {
            const tableElement = document.getElementById('metricsTableStatsList');
            if (!tableElement) {
                console.error("Metrics table element with ID 'metricsTableStatsList' not found.");
                return;
            }
            // Clear previous content
            tableElement.innerHTML = '';
            // Calculate metrics based on latestCounts and the lists already assumed to be populated
            const distinctJournalsCount = journals.length; // Client-side calculation
            const distinctConferencesCount = conferences.length; // Client-side calculation
            const authorListElement = document.getElementById('authorStatsList');
            let distinctAuthorsCount = 0;
            if (authorListElement) {
                distinctAuthorsCount = authorListElement.querySelectorAll('li').length;
            } else {
                console.warn("Author stats list element with ID 'authorStatsList' not found for counting authors.");
            }
            // Count papers providing datasets
            const papersWithDatasetCount = latestCounts['technique_available_dataset'] || 0;
            // Create table rows - Modified to support HTML in the label
            const createRow = (labelHtml, value) => {
                const row = document.createElement('tr');
                const labelCell = document.createElement('td');
                labelCell.innerHTML = labelHtml; // Use innerHTML for formatted labels
                const valueCell = document.createElement('td');
                valueCell.innerHTML = '<strong>' + value + '</strong>'; // Use innerHTML for bold value
                labelCell.className = 'metric-label';
                valueCell.className = 'metric-value';
                row.appendChild(labelCell);
                row.appendChild(valueCell);
                return row;
            };
            // Append rows to the table
            tableElement.appendChild(createRow('Total <strong>filtered</strong> articles:', totalVisiblePaperCount));
            tableElement.appendChild(createRow('Total unique <strong>journals</strong>:', distinctJournalsCount));
            tableElement.appendChild(createRow('Total unique <strong>conferences</strong>:', distinctConferencesCount));
            tableElement.appendChild(createRow('Total unique <strong>authors</strong>:', distinctAuthorsCount)); // Relies on pre-populated list
            tableElement.appendChild(createRow('Articles mentioning <strong>available dataset</strong>:', papersWithDatasetCount));
        }

        populateMetricsTableDirectly();
        setTimeout(() => {
            // Trigger reflow to ensure styles are applied before adding the active class
            // This helps ensure the transition plays correctly on the first open
            modal.offsetHeight;
            // Add the active class to trigger the animation
            modal.classList.add('modal-active');
            document.documentElement.classList.remove('busyCursor');
        }, 250);
    }, 0);
}

function displayAbout() {
    modalSmall.offsetHeight;
    modalSmall.classList.add('modal-active');
}

function closeSmallModal() { modalSmall.classList.remove('modal-active'); }

function closeModal() { modal.classList.remove('modal-active'); } //for stats modal:

function buildKeywordCloud() {
  /* ----------  collect & normalise data  ---------- */
  const liNodes = document.querySelectorAll('#keywordStatsList li');
  const raw = Array.from(liNodes)
    .map(li => {
      const nameEl = li.querySelector('.name');
      const countEl = li.querySelector('.count');
      if (!nameEl || !countEl) return null;
      return { text: nameEl.textContent.trim(), size: +countEl.textContent };
    })
    .filter(Boolean);

  if (!raw.length) {                       // empty list → wipe previous SVG
    const prevSvg = document.querySelector('#keywordCloudCanvas svg');
    if (prevSvg) prevSvg.remove();
    return;
  }

  const topK = raw.slice(0, 50);

  /* ----------  dimensions  ---------- */
  const width = document.querySelector('#keywordCloudCanvas').clientWidth || 500;
  const height = 280;

  /* ----------  font scale  ---------- */
  const sizeScale = d3.scaleLinear()
    .domain([topK[topK.length - 1].size, topK[0].size])
    .range([9 , 54]);

  /* ----------  layout (unchanged)  ---------- */
  const layout = d3.layout.cloud()
    .size([width, height])
    .words(topK.map(d => ({ ...d, size: sizeScale(d.size) })))
    .padding(1)
    .rotate(() => (Math.random() - 0.5) * 0)   // 0° for all words
    .font('sans-serif')
    .fontSize(d => d.size)
    .on('end', draw);

  layout.start();

  /* ----------  SVG rendering (like the example)  ---------- */
  function draw(words) {
    /* remove previous cloud if any */
    d3.select('#keywordCloudCanvas').select('svg').remove();

    const svg = d3.select('#keywordCloudCanvas')
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    svg.append('g')
      .attr('transform', `translate(${width / 2},${height / 2})`)
      .selectAll('text')
      .data(words)
      .enter().append('text')
      .style('font-size', d => `${d.size}px`)
      .style('font-family', 'sans-serif')
      .style('fill', d =>
        techniquesBorderColors[d.text.length % techniquesBorderColors.length])
      .attr('text-anchor', 'middle')
      .attr('transform', d => `translate(${d.x},${d.y})rotate(${d.rotate})`)
      .text(d => d.text);
  }
}

function toggleCloud() {
    const list = document.getElementById('keywordStatsList');
    const canvas = document.getElementById('keywordCloudCanvas');
    const on = document.getElementById('cloudToggle').checked;
    list.style.display = on ? 'none' : 'block';
    canvas.style.display = on ? 'block' : 'none';
    if (!on) return; // ← don’t build if turning off
    const liNodes = list.querySelectorAll('li');
    if (liNodes.length === 0) return; // ← don’t build if no keywords
    buildKeywordCloud(); // ← safe to build
}

function prepareLineChartData() {
    const surveyImplData = latestYearlyData.surveyImpl || {};
    const yearsForSurveyImpl = Object.keys(surveyImplData).map(Number).sort((a, b) => a - b);
    const surveyCounts = yearsForSurveyImpl.map(year => surveyImplData[year].surveys || 0);
    const implCounts = yearsForSurveyImpl.map(year => surveyImplData[year].impl || 0);

    let surveyCountsFinal = surveyCounts;
    let implCountsFinal = implCounts;
    if (isCumulative) {
        surveyCountsFinal = calculateCumulativeData(surveyCounts);
        implCountsFinal = calculateCumulativeData(implCounts);
    }

    const surveyVsImplDatasets = [
        {
            label: 'Survey Papers',
            data: surveyCountsFinal,
            borderColor: 'hsl(204, 42%, 37%)',
            backgroundColor: 'hsla(204, 42%, 67%, 0.95)',
            fill: isStacked,
            tension: 0.25
        },
        {
            label: 'Primary Papers',
            data: implCountsFinal,
            borderColor: 'hsla(38, 70%, 49%, 1.00)',
            backgroundColor: 'hsla(42, 50%, 69%, 0.95)',
            fill: isStacked,
            tension: 0.25
        }
    ];

    const techniquesYearlyData = latestYearlyData.techniques || {};
    const yearsForTechniques = Object.keys(techniquesYearlyData).map(Number).sort((a, b) => a - b);
    const techniqueLineDatasets = TECHNIQUE_FIELDS_FOR_YEARLY.map(field => {
        const label = FIELD_LABELS[field] || field;
        let data = yearsForTechniques.map(year => techniquesYearlyData[year]?.[field] || 0);
        if (isCumulative) {
            data = calculateCumulativeData(data);
        }
        const originalIndex = TECHNIQUE_FIELD_COLOR_MAP[field] !== undefined ? TECHNIQUE_FIELD_COLOR_MAP[field] : -1;
        const borderColor = (originalIndex !== -1 && techniquesBorderColors[originalIndex]) ? techniquesBorderColors[originalIndex] : 'rgba(0, 0, 0, 1)';
        const backgroundColor = (originalIndex !== -1 && techniquesColors[originalIndex]) ? techniquesColors[originalIndex] : 'rgba(0, 0, 0, 0.1)';
        return {
            label: label,
            data: data,
            borderColor: borderColor,
            backgroundColor: backgroundColor,
            fill: isStacked,
            tension: 0.25
        };
    });

    const featuresYearlyData = latestYearlyData.features || {};
    const yearsForFeatures = Object.keys(featuresYearlyData).map(Number).sort((a, b) => a - b);
    const aggregatedFeatureDataByColor = {};
    Object.keys(featureColorGroups).forEach(baseColorIndex => {
        const group = featureColorGroups[baseColorIndex];
        aggregatedFeatureDataByColor[group.label] = yearsForFeatures.map(year => {
            return group.fields.reduce((sum, field) => {
                return sum + (featuresYearlyData[year]?.[field] || 0);
            }, 0);
        });
    });

    const aggregatedFeatureDataByColorFinal = {};
    Object.keys(aggregatedFeatureDataByColor).forEach(label => {
        let data = aggregatedFeatureDataByColor[label];
        if (isCumulative) {
            data = calculateCumulativeData(data);
        }
        aggregatedFeatureDataByColorFinal[label] = data;
    });

    const featureLineDatasets = Object.keys(featureColorGroups).map(baseColorIndex => {
        const group = featureColorGroups[baseColorIndex];
        const colorIndex = parseInt(baseColorIndex);
        const borderColor = featuresBorderColorsOriginalOrder[colorIndex];
        const backgroundColor = featuresColorsOriginalOrder[colorIndex];
        return {
            label: group.label,
            data: aggregatedFeatureDataByColorFinal[group.label],
            borderColor: borderColor,
            backgroundColor: backgroundColor,
            fill: isStacked,
            tension: 0.25
        };
    });

    const pubTypesYearlyData = latestYearlyData.pubTypes || {};
    const yearsForPubTypes = Object.keys(pubTypesYearlyData).map(Number).sort((a, b) => a - b);
    const pubTypeLineDatasets = Object.keys(PUB_TYPE_MAP).map((type, index) => {
        const hue = (index * 137.508) % 360;
        const borderColor = `hsl(${hue}, 40%, 40%)`;
        const backgroundColor = `hsla(${hue}, 30%, 65%, 0.85)`;
        let data = yearsForPubTypes.map(year => pubTypesYearlyData[year]?.[type] || 0);
        if (isCumulative) {
            data = calculateCumulativeData(data);
        }
        return {
            label: mapPubType(type),
            data: data,
            borderColor: borderColor,
            backgroundColor: backgroundColor,
            fill: isStacked,
            tension: 0.25,
            hidden: false // Consider preserving hidden state if needed
        };
    });

    return {
        surveyImpl: { labels: yearsForSurveyImpl, datasets: surveyVsImplDatasets },
        techniques: { labels: yearsForTechniques, datasets: techniqueLineDatasets },
        features: { labels: yearsForFeatures, datasets: featureLineDatasets },
        pubTypes: { labels: yearsForPubTypes, datasets: pubTypeLineDatasets }
    };
}







/**
 * Generates LaTeX for Journals and Conferences table (>=2 occurrences), new format with shading.
 */
function generateLatexJournalsConfs() {
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const journalCounts = {};
    const conferenceCounts = {};

    visibleRows.forEach(row => {
        const journalCell = row.cells[journalCellIndex];
        const typeCell = row.cells[typeCellIndex];
        if (journalCell && typeCell) {
            const journalName = journalCell.textContent.trim();
            const type = (typeCell.getAttribute('title') || typeCell.textContent.trim()).toLowerCase();

            if (journalName) {
                 if (type === 'article') {
                    journalCounts[journalName] = (journalCounts[journalName] || 0) + 1;
                } else if (type === 'inproceedings' || type === 'proceedings' || type === 'conference') {
                    conferenceCounts[journalName] = (conferenceCounts[journalName] || 0) + 1;
                }
            }
        }
    });

    // Filter and sort Journals
    const filteredJournals = Object.entries(journalCounts)
        .filter(([name, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1]);

    // Filter and sort Conferences
     const filteredConferences = Object.entries(conferenceCounts)
        .filter(([name, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1]);

    // Prepare data array for the specific format requested
    const dataArray = [];

    // Add journals
    filteredJournals.forEach(([name, count], index) => {
        // Escape potential special characters in the name
        const escapedName = name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        dataArray.push({
            rowContent: `${count} & Revista & ${escapedName}`,
            type: 'journal'
        });
    });

    // Add an empty row separator if both journals and conferences exist
    if (filteredJournals.length > 0 && filteredConferences.length > 0) {
        dataArray.push({
            rowContent: " & & ", // Creates an empty row visually separating journals and conferences
            type: 'separator'    // Not actually used in row content, just for logic if needed later
        });
    }

    // Add conferences
    filteredConferences.forEach(([name, count], index) => {
        // Escape potential special characters in the name
        const escapedName = name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        dataArray.push({
            rowContent: `${count} & Conferência & ${escapedName}`,
            type: 'conference'
        });
    });

    const config = {
        caption: "Veículos de Publicação mais Comuns",
        label: "cap32_journals_confs_new", // Change label as needed
        headers: ["Artigos", "Tipo de Veículo", "Veículo"],
        columnSpec: "{@{}llX@{}}", // Adjust column spec for the new format
        useShading: true // Enable shading for this table
    };

    return generateLatexTabularx(dataArray, config);
}/**
 * Generates LaTeX for Authors table (>=2 occurrences), split into Primary and Survey articles, with shading.
 */
function generateLatexAuthors() {
    // Recalculate based on visible rows and survey status
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const primaryAuthorCounts = {}; // Author -> Count for primary papers
    const surveyAuthorCounts = {};  // Author -> Count for survey papers

    visibleRows.forEach(row => {
        const authorsCell = row.querySelector('td[data-field="authors"]');
        if (!authorsCell) return;

        // Check for survey status
        const isSurveyCell = row.querySelector('td[data-field="is_survey"]');
        const isSurvey = isSurveyCell && isSurveyCell.textContent.trim() === '✔️';

        const authorsText = authorsCell.textContent.trim();
        if (authorsText) {
            const authorsList = authorsText.split(';')
                .map(author => author.trim())
                .filter(author => author.length > 0);

            authorsList.forEach(author => {
                if (isSurvey) {
                    surveyAuthorCounts[author] = (surveyAuthorCounts[author] || 0) + 1;
                } else {
                    primaryAuthorCounts[author] = (primaryAuthorCounts[author] || 0) + 1;
                }
            });
        }
    });

    // Filter authors with count >= 2 for each category
    const filteredPrimaryAuthors = Object.entries(primaryAuthorCounts)
        .filter(([name, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1]); // Sort by count descending

    const filteredSurveyAuthors = Object.entries(surveyAuthorCounts)
        .filter(([name, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1]); // Sort by count descending

    // Prepare data arrays for LaTeX generation
    const primaryData = filteredPrimaryAuthors.map(([name, count]) => ({ name: name, count: count }));
    const surveyData = filteredSurveyAuthors.map(([name, count]) => ({ name: name, count: count }));

    // Determine the maximum number of rows to iterate over
    const maxRows = Math.max(primaryData.length, surveyData.length);

    // Prepare data array for the split table format
    const dataArray = [];
    for (let i = 0; i < maxRows; i++) {
        const primaryRow = primaryData[i];
        const surveyRow = surveyData[i];

        // Initialize cells for this row
        let primaryQty = "", primaryAuthor = "", surveyQty = "", surveyAuthor = "";

        // Fill primary cells if data exists
        if (primaryRow) {
            primaryQty = primaryRow.count;
            // Escape special characters in author name
            primaryAuthor = primaryRow.name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        } else {
            // Leave cells empty if no data
            primaryQty = "";
            primaryAuthor = "";
        }

        // Fill survey cells if data exists
        if (surveyRow) {
            surveyQty = surveyRow.count;
            // Escape special characters in author name
            surveyAuthor = surveyRow.name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        } else {
            // Leave cells empty if no data
            surveyQty = "";
            surveyAuthor = "";
        }

        // Add the row data object
        dataArray.push({
            rowContent: `${primaryQty} & ${primaryAuthor} & ${surveyQty} & ${surveyAuthor}`
        });
    }

    // Custom LaTeX generation for this specific double-table format with shading
    let latexCode = "\\begin{table}[ht]\n";
    latexCode += "\\centering\n";
    latexCode += "\\small % or \\footnotesize for even smaller\n";
    latexCode += "\t\\caption{Autores por tipo de artigo (>=2 ocorrências)}\n"; // Change caption as needed
    latexCode += "\\label{tab:cap32_authors_split}\n"; // Change label as needed

    // Use tabularx with two columns for the double table structure, adding a vertical line separator (|)
    latexCode += "\\begin{tabularx}{\\textwidth}{@{}lX|lX@{}}\n";
    latexCode += "\\toprule\n";

    // Headers for both sides - now includes the vertical line separator in the header row too
    latexCode += "\\multicolumn{2}{c}{\\textbf{Artigos primários}} & \\multicolumn{2}{c}{\\textbf{Artigos de revisão}} \\\\\n";
    latexCode += "\\midrule\n";
    latexCode += "\\textbf{Qtd.} & \\textbf{Autor} & \\textbf{Qtd.} & \\textbf{Autor} \\\\\n";
    latexCode += "\\midrule\n";

    // Add data rows with shading applied using the modified loop structure
    dataArray.forEach((item, index) => {
        // Apply shading if index is odd (0-based, data starts on row after midrule)
        // Shading applies to the whole row across both halves due to how \rowcolor works
        if ((index + 1) % 2 === 1) { // +1 because headers are before first data row
            latexCode += "\\rowcolor{tableshade}";
        }
        latexCode += item.rowContent + " \\\\\n";
    });

    // Add footnote if there are survey authors with count 1 (as per the example image)
    const allSurveyAuthorsWithCount1 = Object.entries(surveyAuthorCounts)
        .filter(([name, count]) => count === 1);

    if (allSurveyAuthorsWithCount1.length > 0) {
        latexCode += "\\midrule\n";
        latexCode += "\\multicolumn{4}{l}{\\textit{* Todos os outros autores que publicaram revisões aparecem apenas uma vez.}} \\\\\n";
    }

    latexCode += "\\bottomrule\n";
    latexCode += "\\end{tabularx}\n";
    latexCode += "\\fonte{\\me{2026}}\n"; // Adjust source macro as needed
    latexCode += "\\end{table}\n";

    return latexCode;
}

/**
 * Generates LaTeX for Models table (>=2 occurrences), arranged in multiple columns (3 per row, Count first), with shading.
 */
function generateLatexModels() {
     const listElement = document.getElementById('modelNamesStatsList');
    if (!listElement) {
        console.error("Model names stats list element not found.");
        return "";
    }

    // Collect all models with count >= 2 from the currently displayed list
    const rawModelData = [];
    listElement.querySelectorAll('li').forEach(li => {
        const countSpan = li.querySelector('.count');
        const nameSpan = li.querySelector('.name');
        if (countSpan && nameSpan) {
            const count = parseInt(countSpan.textContent, 10);
            const name = nameSpan.textContent.trim();
             // Only include if count is >= 2, matching the requirement
            if (count >= 2) {
                // Escape special characters in name *before* adding to array
                const escapedName = name.replace(/_/g, "\\_").replace(/&/g, "\\&");
                rawModelData.push({ name: escapedName, count: count });
            }
        }
    });

    // Data should already be sorted by populateSimpleList (count desc, then name asc)
    // No need to re-sort here if populateSimpleList ensures it

    if (rawModelData.length === 0) {
         console.warn("No models with count >= 2 found for LaTeX generation.");
         // Return an empty table or a comment
         return "% No models with count >= 2 found for table.\n";
    }

    // Define number of columns per row (3 as requested)
    const modelsPerRow = 3;

    // Prepare the rows for the table
    const tableRows = [];
    for (let i = 0; i < rawModelData.length; i += modelsPerRow) {
        const rowData = rawModelData.slice(i, i + modelsPerRow);
        // Each row will have 2 * modelsPerRow cells: Count, Name, Count, Name, ...
        let rowCells = [];
        for (let j = 0; j < modelsPerRow; j++) {
            if (j < rowData.length) {
                // Add count and name for existing model in this slot
                rowCells.push(rowData[j].count.toString()); // Count first, convert to string
                rowCells.push(rowData[j].name);           // Name second
            } else {
                // Add empty cells if there aren't enough models for this row
                rowCells.push(""); // Empty count cell
                rowCells.push(""); // Empty name cell
            }
        }
        // Join the cells for this row with " & "
        tableRows.push(rowCells.join(" & "));
    }

    // Calculate the column specification string
    // Need 2 columns (Count, Name) repeated modelsPerRow times
    // Use 'r' for the count column (numbers, fits content well) and 'X' for the name column (expands)
    let columnSpec = "{@{}";
    for (let k = 0; k < modelsPerRow; k++) {
        columnSpec += "cX"; // Count column (right-aligned, fits content), Name column (expands)
    }
    columnSpec += "@{}}";

    // Custom LaTeX generation for the multicolumn model table
    let latexCode = "\\begin{table}[ht]\n";
    latexCode += "\\centering\n";
    latexCode += "\\small % or \\footnotesize for even smaller\n";
    latexCode += "\t\\caption{Modelos mais comuns (>=2 ocorrências, " + modelsPerRow + " por linha, Contagem primeiro)}\n"; // Change caption as needed
    latexCode += "\\label{tab:cap32_model_names_multi_cn}\n"; // Change label as needed
    latexCode += `\\begin{tabularx}{\\textwidth}${columnSpec}\n`;
    latexCode += "\\toprule\n";

    // Generate headers: Count, Name, Count, Name, ...
    let headerCells = [];
    for (let h = 0; h < modelsPerRow; h++) {
        headerCells.push("\\textbf{Contagem}"); // Count header first
        headerCells.push("\\textbf{Nome}");     // Name header second
    }
    latexCode += headerCells.join(" & ") + " \\\\\n";
    latexCode += "\\midrule\n";

    // Add data rows with shading
    tableRows.forEach((rowContent, index) => {
        // Apply shading if index is odd (0-based, data starts after headers)
        if ((index + 1) % 2 === 1) { // +1 because headers are on row 0, data starts on row 1
            latexCode += "\\rowcolor{tableshade}";
        }
        latexCode += rowContent + " \\\\\n";
    });

    latexCode += "\\bottomrule\n";
    latexCode += "\\end{tabularx}\n";
    latexCode += "\\fonte{\\me{2026}}\n"; // Adjust source macro as needed
    latexCode += "\\end{table}\n";

    return latexCode;
}

/**
 * Generates LaTeX for Metrics table (with survey/non-survey breakdown), with shading.
 * Calculates counts split by paper type (primary/survey) for all metrics.
 */
function generateLatexMetrics() {
    // Recalculate based on visible rows and survey status
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    let primaryPaperCount = 0, surveyPaperCount = 0;
    const primaryJournalsSet = new Set(); // Unique journals for primary papers
    const surveyJournalsSet = new Set();  // Unique journals for survey papers
    const primaryConfsSet = new Set();    // Unique conferences for primary papers
    const surveyConfsSet = new Set();     // Unique conferences for survey papers
    const primaryAuthorsSet = new Set();  // Unique authors for primary papers
    const surveyAuthorsSet = new Set();   // Unique authors for survey papers

    visibleRows.forEach(row => {
        const journalCell = row.cells[journalCellIndex];
        const typeCell = row.cells[typeCellIndex];
        const authorsCell = row.querySelector('td[data-field="authors"]');

        // Check for survey status using the data-field attribute
        const isSurveyCell = row.querySelector('td[data-field="is_survey"]');
        const isSurvey = isSurveyCell && isSurveyCell.textContent.trim() === '✔️';

        // Determine primary/survey *paper* counts (mutually exclusive per paper)
        if (isSurvey) {
            surveyPaperCount++;
        } else {
            primaryPaperCount++; // Assuming anything not marked as survey is primary
        }

        // Gather Journals/Conferences - split by paper type
        if (journalCell && typeCell) {
            const journalName = journalCell.textContent.trim();
            const type = (typeCell.getAttribute('title') || typeCell.textContent.trim()).toLowerCase();

            if (journalName) {
                 if (type === 'article') { // Journal
                     if (isSurvey) {
                         surveyJournalsSet.add(journalName);
                     } else {
                         primaryJournalsSet.add(journalName);
                     }
                 } else if (type === 'inproceedings' || type === 'proceedings' || type === 'conference') { // Conference
                     if (isSurvey) {
                         surveyConfsSet.add(journalName);
                     } else {
                         primaryConfsSet.add(journalName);
                     }
                 }
                 // Note: Other types are implicitly ignored for this metric unless explicitly handled.
            }
        }

        // Gather Authors - split by paper type
        if (authorsCell) {
            const authorsText = authorsCell.textContent.trim();
            if (authorsText) {
                const authorsList = authorsText.split(';')
                    .map(author => author.trim())
                    .filter(author => author.length > 0);

                authorsList.forEach(author => {
                    if (isSurvey) {
                        surveyAuthorsSet.add(author); // Add to set of unique survey authors
                    } else {
                        primaryAuthorsSet.add(author); // Add to set of unique primary authors
                    }
                });
            }
        }
    });

    // Calculate totals based on the split sets
    const totalFilteredPapers = primaryPaperCount + surveyPaperCount;
    const primaryJournalsCount = primaryJournalsSet.size;
    const surveyJournalsCount = surveyJournalsSet.size;
    const totalJournalsCount = new Set([...primaryJournalsSet, ...surveyJournalsSet]).size; // Union size

    const primaryConfsCount = primaryConfsSet.size;
    const surveyConfsCount = surveyConfsSet.size;
    const totalConfsCount = new Set([...primaryConfsSet, ...surveyConfsSet]).size; // Union size

    const primaryAuthorsCount = primaryAuthorsSet.size;
    const surveyAuthorsCount = surveyAuthorsSet.size;
    const totalAuthorsCount = new Set([...primaryAuthorsSet, ...surveyAuthorsSet]).size; // Union size

    // Define the data structure for the specific table format requested
    // Now correctly reflecting split counts for all metrics
    const metricRows = [
        { label: "Artigos filtrados:", primary: primaryPaperCount, survey: surveyPaperCount, total: totalFilteredPapers },
        { label: "Revistas:", primary: primaryJournalsCount, survey: surveyJournalsCount, total: totalJournalsCount },
        { label: "Conferências:", primary: primaryConfsCount, survey: surveyConfsCount, total: totalConfsCount },
        { label: "Autores:", primary: primaryAuthorsCount, survey: surveyAuthorsCount, total: totalAuthorsCount }
    ];

    // Prepare data array for the generic generator
    const dataArray = metricRows.map(row => {
        const escapedLabel = row.label.replace(/_/g, "\\_").replace(/&/g, "\\&"); // Escape label
        return {
            rowContent: `${escapedLabel} & ${row.primary} & ${row.survey} & ${row.total}`
        };
    });

    const config = {
        caption: "Métricas detalhadas por tipo de artigo", // Change caption as needed
        label: "cap32_metrics_detailed", // Change label as needed
        headers: ["Tipo de Métrica", "Primários", "Revisão", "Total"], // Change headers as needed
        columnSpec: "{@{}X X X X @{}}", // Adjust column spec for the new format
        useShading: true // Enable shading
    };

    return generateLatexTabularx(dataArray, config);
}

// Update the core function to accept a shading flag and row index
/**
 * Generates a LaTeX tabularx table string from provided data and configuration.
 * @param {Array<Object>} dataArray - Array of objects containing 'name' and 'count'.
 * @param {Object} config - Configuration object specifying table details.
 * @param {string} config.caption - The LaTeX caption text.
 * @param {string} config.label - The LaTeX label text.
 * @param {Array<string>} config.headers - Array of header strings for the table.
 * @param {string} config.columnSpec - The column specification for tabularx (e.g., "{@{}lXl@{}}").
 * @param {boolean} config.useShading - Whether to apply row shading.
 * @returns {string} The complete LaTeX table code.
 */
function generateLatexTabularx(dataArray, config) {
    const { caption, label, headers, columnSpec, useShading } = config;

    if (!dataArray || dataArray.length === 0) {
        console.warn("No data provided for LaTeX table generation.");
        return `% No data available for table: ${caption}\n`;
    }

    let latexCode = "\\begin{table}[ht]\n";
    latexCode += "\\centering\n";
    latexCode += "\\small % or \\footnotesize for even smaller\n";
    latexCode += `\t\\caption{${caption}}\n`;
    latexCode += `\\label{tab:${label}}\n`;
    latexCode += `\\begin{tabularx}{\\textwidth}${columnSpec}\n`;
    latexCode += "\\toprule\n";

    // Add headers
    latexCode += headers.join(" & ") + " \\\\\n";
    latexCode += "\\midrule\n";

    // Add data rows with optional shading
    dataArray.forEach((item, index) => {
        // Apply shading if enabled and index is odd (0-based, so 1st data row is index 0 -> no shade, 2nd is index 1 -> shade)
        if (useShading && (index + 1) % 2 === 1) { // +1 because headers are on row 0, data starts on row 1
            latexCode += "\\rowcolor{tableshade}";
        }

        // Assuming the item object structure matches the expected columns for the specific table calling this
        // For generic use, we might need a more flexible mapping, but for our current specific uses, this is okay.
        // The specific functions will format the row content correctly.
        latexCode += item.rowContent + " \\\\\n"; // Use the pre-formatted row content
    });

    latexCode += "\\bottomrule\n";
    latexCode += "\\end{tabularx}\n";
    latexCode += "\\fonte{\\me{2026}}\n";
    latexCode += "\\end{table}\n";

    return latexCode;
}











document.addEventListener('DOMContentLoaded', function () {
    const stackingToggle = document.getElementById('stackingToggle');
    const cumulativeToggle = document.getElementById('cumulativeToggle');
    const pieToggle = document.getElementById('pieToggle');
    const cloudToggle = document.getElementById('cloudToggle');
    const featureGroupToggle = document.getElementById('featureGroupToggle');

    stackingToggle.checked = false;
    cumulativeToggle.checked = false;
    pieToggle.checked = false;
    cloudToggle.checked = false;
    featureGroupToggle.checked = true; // default on for this one

    statsBtn.addEventListener('click', function () {
        document.documentElement.classList.add('busyCursor');
        buildStatsLists();
        displayStats();
    });

    stackingToggle.addEventListener('change', function () {
        isStacked = this.checked; // Update the state variable
        // Update the chart options for stacking
        if (window.surveyVsImplLineChartInstance) {
            window.surveyVsImplLineChartInstance.options.scales.y.stacked = isStacked;
            window.surveyVsImplLineChartInstance.options.scales.x.stacked = isStacked;
            window.surveyVsImplLineChartInstance.data.datasets.forEach(dataset => {
                dataset.fill = isStacked;
            });
            window.surveyVsImplLineChartInstance.update(); // Update the chart
        }
        if (window.techniquesPerYearLineChartInstance) {
            window.techniquesPerYearLineChartInstance.options.scales.y.stacked = isStacked;
            window.techniquesPerYearLineChartInstance.options.scales.x.stacked = isStacked;
            window.techniquesPerYearLineChartInstance.data.datasets.forEach(dataset => {
                dataset.fill = isStacked;
            });
            window.techniquesPerYearLineChartInstance.update();
        }
        if (window.featuresPerYearLineChartInstance) {
            window.featuresPerYearLineChartInstance.options.scales.y.stacked = isStacked;
            window.featuresPerYearLineChartInstance.options.scales.x.stacked = isStacked;
            window.featuresPerYearLineChartInstance.data.datasets.forEach(dataset => {
                dataset.fill = isStacked;
            });
            window.featuresPerYearLineChartInstance.update();
        }
        if (window.pubTypesPerYearLineChartInstance) {
            window.pubTypesPerYearLineChartInstance.options.scales.y.stacked = isStacked;
            window.pubTypesPerYearLineChartInstance.options.scales.x.stacked = isStacked;
            window.pubTypesPerYearLineChartInstance.data.datasets.forEach(dataset => {
                dataset.fill = isStacked;
            });
            window.pubTypesPerYearLineChartInstance.update();
        }
        reorderDatasetsForStacking();
    });

    cumulativeToggle.addEventListener('change', function () {
        isCumulative = this.checked; // Update the state variable

        // Prepare the updated data based on the new cumulative state
        const updatedLineChartData = prepareLineChartData();

        // Update each line chart instance with the new data
        if (window.surveyVsImplLineChartInstance) {
            window.surveyVsImplLineChartInstance.data.labels = updatedLineChartData.surveyImpl.labels;
            window.surveyVsImplLineChartInstance.data.datasets = updatedLineChartData.surveyImpl.datasets;
            // No need to update scales for cumulative, just data and potentially legend
            // Legend update might be handled by cumulativeLegendLabels already, but update() triggers it
            window.surveyVsImplLineChartInstance.update(); // Update the chart
        }
        if (window.techniquesPerYearLineChartInstance) {
            window.techniquesPerYearLineChartInstance.data.labels = updatedLineChartData.techniques.labels;
            window.techniquesPerYearLineChartInstance.data.datasets = updatedLineChartData.techniques.datasets;
            window.techniquesPerYearLineChartInstance.update();
        }
        if (window.featuresPerYearLineChartInstance) {
            window.featuresPerYearLineChartInstance.data.labels = updatedLineChartData.features.labels;
            window.featuresPerYearLineChartInstance.data.datasets = updatedLineChartData.features.datasets;
            window.featuresPerYearLineChartInstance.update();
        }
        if (window.pubTypesPerYearLineChartInstance) {
            window.pubTypesPerYearLineChartInstance.data.labels = updatedLineChartData.pubTypes.labels;
            window.pubTypesPerYearLineChartInstance.data.datasets = updatedLineChartData.pubTypes.datasets;
            window.pubTypesPerYearLineChartInstance.update();
        }
        // reorderDatasetsForStacking(); // Call this *after* updating data if stacking is enabled and cumulative changed
        if (isStacked) {
            reorderDatasetsForStacking();
        }
    });

    featureGroupToggle.addEventListener('change', function () {
        // Re-render the Features bar chart based on the new toggle state
        if (window.featuresBarChartInstance) {
            const featuresCtx = document.getElementById('featuresPieChart')?.getContext('2d');
            if (featuresCtx) {
                // Prepare data considering the new toggle state
                const featuresChartData = prepareFeaturesData(); // This function now checks the toggle
                // Destroy the old instance
                window.featuresBarChartInstance.destroy();
                // Create the new chart instance using the existing render function
                window.featuresBarChartInstance = renderBarOrPieChart(featuresCtx, featuresChartData, 'Features Count', showPieCharts ? 'pie' : 'bar');
            }
        }
    });
    
    pieToggle.addEventListener('change', function () {
        showPieCharts = this.checked; // Update the state variable

        // Prepare the updated data based on the new showPieCharts state
        const featuresChartData = prepareFeaturesData();
        const techniquesChartData = prepareTechniquesData();
        const surveyVsImplDistChartData = prepareSurveyVsImplDistData(
            // You need to get the current totalVisiblePaperCount here.
            // It's calculated in displayStats but not stored globally.
            // Option 1: Store it in a global variable like latestCounts/YearlyData
            // Option 2: Recalculate it here (less efficient but simpler for this change)
            document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)').length
        );
        const pubTypesDistChartData = preparePubTypesDistData();
        const smtVsThtDistChartData = prepareSMTvsTHTData();
        const scopeChartData = prepareScopeData(
            // Similarly, you need the visible and total counts here
            document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)').length,
            parseInt(document.getElementById('total-papers-count')?.textContent.trim() || '0', 10)
        );

        // Determine the chart type ('bar' or 'pie')
        const chartType = showPieCharts ? 'pie' : 'bar';

        // Update each distribution chart instance with the new data and type
        // Features Chart
        if (window.featuresBarChartInstance) {
            // Destroy the old instance
            window.featuresBarChartInstance.destroy();
            // Get the context again
            const featuresCtx = document.getElementById('featuresPieChart')?.getContext('2d');
            if (featuresCtx) {
                // Create the new chart instance
                window.featuresBarChartInstance = renderBarOrPieChart(featuresCtx, featuresChartData, 'Features Count', chartType);
            }
        }

        // Techniques Chart
        if (window.techniquesBarChartInstance) {
            window.techniquesBarChartInstance.destroy();
            const techniquesCtx = document.getElementById('techniquesPieChart')?.getContext('2d');
            if (techniquesCtx) {
                window.techniquesBarChartInstance = renderBarOrPieChart(techniquesCtx, techniquesChartData, 'Techniques Count', chartType);
            }
        }

        // Survey vs Impl Distribution Chart
        if (window.surveyVsImplDistChartInstance) {
            window.surveyVsImplDistChartInstance.destroy();
            const surveyVsImplDistCtx = document.getElementById('surveyVsImplPieChart')?.getContext('2d');
            if (surveyVsImplDistCtx) {
                window.surveyVsImplDistChartInstance = renderBarOrPieChart(surveyVsImplDistCtx, surveyVsImplDistChartData, 'Survey vs Primary Distribution', chartType);
            }
        }

        // Publication Types Distribution Chart
        if (window.pubTypesDistChartInstance) {
            window.pubTypesDistChartInstance.destroy();
            const pubTypesDistCtx = document.getElementById('publTypePieChart')?.getContext('2d');
            if (pubTypesDistCtx) {
                window.pubTypesDistChartInstance = renderBarOrPieChart(pubTypesDistCtx, pubTypesDistChartData, 'Publication Types Distribution', chartType);
            }
        }

        // SMT vs THT Distribution Chart
        if (window.smtVsThtDistChartInstance) {
            window.smtVsThtDistChartInstance.destroy();
            const smtVsThtCtx = document.getElementById('SMTvsTHTPieChart')?.getContext('2d');
            if (smtVsThtCtx) {
                window.smtVsThtDistChartInstance = renderBarOrPieChart(smtVsThtCtx, smtVsThtDistChartData, 'SMT vs THT Distribution', chartType);
            }
        }

        // Scope Distribution Chart
        if (window.scopeDistChartInstance) {
            window.scopeDistChartInstance.destroy();
            const scopeCtx = document.getElementById('OffTopicPieChart')?.getContext('2d');
            if (scopeCtx) {
                window.scopeDistChartInstance = renderBarOrPieChart(scopeCtx, scopeChartData, 'Dataset Scope (On-topic vs Off-topic)', chartType);
            }
        }
        // Note: Line charts (window.surveyVsImplLineChartInstance, etc.) are NOT touched here.
    });

    
    const journalConfTabularxBtn = document.getElementById('journalconf-tabularx-btn');
    journalConfTabularxBtn.addEventListener('click', function(event) {
        event.stopPropagation(); // Prevent closing the modal if clicking the button area closes it
        const originalText = this.innerHTML;
        this.innerHTML = 'Copied!';

        const latexCode = generateLatexJournalsConfs();
        if (latexCode) {
                navigator.clipboard.writeText(latexCode)
                .then(() => {
                    console.log("LaTeX for Journals/Confs copied to clipboard");
                    // Feedback is given by changing button text
                })
                .catch(err => {
                    console.error('Failed to copy LaTeX to clipboard:', err);
                    alert('Failed to copy LaTeX code to clipboard.');
                    this.innerHTML = originalText; // Revert on failure immediately
                });
        } else {
                console.warn("No LaTeX code generated for Journals/Confs.");
                this.innerHTML = originalText; // Revert if no code
        }

        // Revert button text after delay regardless of success/failure
        setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    });

    const authorsTabularxBtn = document.getElementById('authors-tabularx-btn');
    authorsTabularxBtn.addEventListener('click', function(event) {
        event.stopPropagation();
        const originalText = this.innerHTML;
        this.innerHTML = 'Copied!';

        const latexCode = generateLatexAuthors();
        if (latexCode) {
                navigator.clipboard.writeText(latexCode)
                .then(() => {
                    console.log("LaTeX for Authors copied to clipboard");
                })
                .catch(err => {
                    console.error('Failed to copy LaTeX to clipboard:', err);
                    alert('Failed to copy LaTeX code to clipboard.');
                    this.innerHTML = originalText;
                });
        } else {
                console.warn("No LaTeX code generated for Authors.");
                this.innerHTML = originalText;
        }

            setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    });

    const modelsTabularxBtn = document.getElementById('models-tabularx-btn');
    modelsTabularxBtn.addEventListener('click', function(event) {
        event.stopPropagation();
        const originalText = this.innerHTML;
        this.innerHTML = 'Copied!';

        const latexCode = generateLatexModels();
        if (latexCode) {
                navigator.clipboard.writeText(latexCode)
                .then(() => {
                    console.log("LaTeX for Models copied to clipboard");
                })
                .catch(err => {
                    console.error('Failed to copy LaTeX to clipboard:', err);
                    alert('Failed to copy LaTeX code to clipboard.');
                    this.innerHTML = originalText;
                });
        } else {
                console.warn("No LaTeX code generated for Models.");
                this.innerHTML = originalText;
        }

            setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    });

    const metricsTabularxBtn = document.getElementById('metrics-tabularx-btn');
    metricsTabularxBtn.addEventListener('click', function(event) {
        event.stopPropagation();
        const originalText = this.innerHTML;
        this.innerHTML = 'Copied!';

        const latexCode = generateLatexMetrics();
        if (latexCode) {
                navigator.clipboard.writeText(latexCode)
                .then(() => {
                    console.log("LaTeX for Metrics copied to clipboard");
                })
                .catch(err => {
                    console.error('Failed to copy LaTeX to clipboard:', err);
                    alert('Failed to copy LaTeX code to clipboard.');
                    this.innerHTML = originalText;
                });
        } else {
                console.warn("No LaTeX code generated for Metrics.");
                this.innerHTML = originalText;
        }

            setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    });



    aboutBtn.addEventListener('click', displayAbout);

    // --- Close Modal
    spanClose.addEventListener('click', closeModal);
    smallClose.addEventListener('click', closeSmallModal);


    

    // --- Add F1 Shortcut ---
    document.addEventListener('keydown', function(event) {
        if (event.key === 'F1') {
            event.preventDefault();
            displayAbout();
        }
    });

    // --- Add F4 shortcut ---
    document.addEventListener('keydown', function (event) {
        // Check if the pressed key is 'Escape' and if the modal is currently active
        if (event.key === 'Escape') {
            closeModal();
            closeSmallModal();
            if (document.body.id !== "html-export") {
                // Assuming these functions exist in the global scope or are imported
                closeBatchModal(); /* from comms.js */
                closeExporthModal();
                closeImportModal()
            }
        }
        // Add the F4 key check for opening the stats panel
        if (event.key === 'F4') {
            event.preventDefault(); // Prevent any default F4 behavior (though browsers often don't have one)
            document.documentElement.classList.add('busyCursor');
            closeSmallModal();
            if (document.body.id !== "html-export") {
                // Assuming these functions exist in the global scope or are imported
                closeBatchModal(); /* from comms.js */
                closeExporthModal();
                closeImportModal()
            }
            buildStatsLists(); // Ensure lists are built before displaying
            displayStats();
        }
    });

    cloudToggle.addEventListener('change', toggleCloud);
    cloudToggle.checked = true;          // 1. UI match

    window.addEventListener('click', function (event) {
        if (event.target === modal || event.target === modalSmall) {
            closeModal();
            closeSmallModal();
        }
        if (document.body.id !== 'html-export') {
            if (event.target === batchModal || event.target === importModal || event.target === exportModal) {
                closeBatchModal(); /* from comms.js */
                closeImportModal();
                closeExporthModal();
            }
        }
    });
});