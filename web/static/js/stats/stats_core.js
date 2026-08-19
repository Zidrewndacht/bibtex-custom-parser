// stats_core.js
let latestCounts = {};
let latestYearlyData = {};
let isStacked = false;
let isCumulative = false;
let showPieCharts = false;

// Table Column Indices
const COL_IDX_PDF = 0;
const COL_IDX_YEAR = 2;
const COL_IDX_JOURNAL = 4;
const COL_IDX_TYPE = 5;

const PUB_TYPE_MAP = {
    'article': 'Journal', 'inproceedings': 'Conference', 'proceedings': 'Conference',
    'conference': 'Conference', 'techreport': 'Report', 'book': 'Book',
    'mastersthesis': 'Thesis', 'phdthesis': 'Thesis'
};

function mapPubType(type) {
    if (!type) return 'Other';
    return PUB_TYPE_MAP[type.toLowerCase().trim()] || type;
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

// --- Hook System ---
const statsHooks = {
    collectData: [],
    renderCharts: []
};

function registerStatsHook(hookName, fn) {
    if (!statsHooks[hookName]) statsHooks[hookName] = [];
    statsHooks[hookName].push(fn);
}

/** 
 * updateCounts() is used by filtering.js and comms.js! 
 * Replaces the old updateCounts and the intermediate collectCoreStatsData.
 */
function updateCounts() {
    const counts = {};
    APP_CONFIG.groups.forEach(group => {
        if (group.filter_type === 'tri_state') counts[group.json_path] = 0;
        else if (['inclusion', 'none'].includes(group.filter_type)) {
            group.fields.forEach(f => counts[`${group.json_path}.${f.key}`] = 0);
        }
    });
    
    Object.assign(counts, { 
        pdf_present: 0, pdf_annotated: 0, pdf_paywalled: 0, 
        is_offtopic: 0, verified: 0, changed_by: 0, verified_by: 0, 
        user_comment_state: 0, model: 0 
    });

    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const visiblePaperCount = visibleRows.length;
    const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
    const loadedPaperCount = allRows.length;

    const yearlySurveyImpl = {};
    const yearlyPubTypes = {};

    visibleRows.forEach(row => {
        // 1. PDF Counts
        const pdfCell = row.cells[COL_IDX_PDF];
        if (pdfCell) {
            const pdfContent = pdfCell.textContent.trim();
            if (pdfContent === '📕') counts.pdf_present++;
            else if (pdfContent === '📗') { counts.pdf_annotated++; counts.pdf_present++; }
            else if (pdfContent === '💰') counts.pdf_paywalled++;
        }

        // 2. Universal & Domain Counts
        const offTopicCell = row.querySelector('[data-field="is_offtopic"]');
        if (offTopicCell && offTopicCell.textContent.trim() === '✔️') counts.is_offtopic++;
        
        const verifiedCell = row.querySelector('[data-field="verified"]');
        if (verifiedCell && verifiedCell.textContent.trim() === '✔️') counts.verified++;
        
        const changedByCell = row.querySelector('[data-field="changed_by"]');
        if (changedByCell && changedByCell.innerHTML.includes('👤')) counts.changed_by++;
        
        const verifiedByCell = row.querySelector('[data-field="verified_by"]');
        if (verifiedByCell && verifiedByCell.innerHTML.includes('👤')) counts.verified_by++;
        
        const userCommentCell = row.querySelector('[data-field="user_comment_state"]');
        if (userCommentCell && userCommentCell.textContent.trim() === '✔️') counts.user_comment_state++;

        APP_CONFIG.groups.forEach(group => {
            if (group.filter_type === 'tri_state') {
                const cell = row.querySelector(`[data-field="${group.json_path}"]`);
                if (cell && cell.textContent.trim() === '✔️') counts[group.json_path]++;
            } else if (['inclusion', 'none'].includes(group.filter_type)) {
                group.fields.forEach(f => {
                    const cell = row.querySelector(`[data-field="${group.json_path}.${f.key}"]`);
                    if (cell && cell.textContent.trim() === '✔️') counts[`${group.json_path}.${f.key}`]++;
                });
            }
        });

        // 3. Model Counts
        const modelCell = row.querySelector('td.hidden-data-cell[data-field="technique_model"]') || 
                          row.querySelector('td[data-field="model"]') || 
                          row.querySelector('td[data-field="model_name"]');
        if (modelCell) {
            const modelText = modelCell.textContent.trim();
            if (modelText) counts.model += modelText.split(/[,;]/).map(m => m.trim()).filter(m => m !== '').length;
        }

        // 4. Yearly Data
        const yearCell = row.cells[COL_IDX_YEAR];
        if (yearCell) {
            const year = parseInt(yearCell.textContent.trim(), 10);
            if (!isNaN(year)) {
                if (!yearlySurveyImpl[year]) yearlySurveyImpl[year] = { surveys: 0, impl: 0 };
                if (!yearlyPubTypes[year]) yearlyPubTypes[year] = {};
                
                const isSurveyCell = row.querySelector('[data-field="is_survey"]');
                const isSurvey = isSurveyCell && isSurveyCell.textContent.trim() === '✔️';
                isSurvey ? yearlySurveyImpl[year].surveys++ : yearlySurveyImpl[year].impl++;
                
                const typeCell = row.cells[COL_IDX_TYPE];
                if (typeCell) {
                    const rawType = (typeCell.getAttribute('title') || typeCell.textContent.trim() || '').toLowerCase();
                    if (rawType) {
                        const mappedType = mapPubType(rawType);
                        yearlyPubTypes[year][mappedType] = (yearlyPubTypes[year][mappedType] || 0) + 1;
                    }
                }
            }
        }
    });

    latestCounts = counts;
    latestYearlyData = { surveyImpl: yearlySurveyImpl, pubTypes: yearlyPubTypes };

    // --- Update Filtered/Loaded Counts in Footer ---
    if (document.body.id === 'html-export') {
        const visibleCountCell = document.getElementById('visible-count-cell');
        if (visibleCountCell) {
            visibleCountCell.innerHTML = `<strong>${visiblePaperCount}</strong> paper${visiblePaperCount !== 1 ? 's' : ''}`;
        }
    } else {
        const loadedPapersCountCell = document.getElementById('loaded-papers-count');
        const visiblePapersCountCell = document.getElementById('visible-papers-count');
        if (loadedPapersCountCell) loadedPapersCountCell.textContent = loadedPaperCount;
        if (visiblePapersCountCell) visiblePapersCountCell.textContent = visiblePaperCount;
    }

    // --- Update Individual Field Counts (PDF, Offtopic, Verified, etc.) ---
    const updateCountCell = (field, count) => {
        const cell = document.querySelector(`[data-count-field="${field}"]`) || document.getElementById(`count-${field.replace(/\./g, '_')}`);
        if (!cell) return;
        if (field === 'pdf_present') {
            cell.textContent = counts.pdf_present;
            cell.title = `Stored PDFs: ${counts.pdf_present}, Annotated: ${counts.pdf_annotated}, Paywalled: ${counts.pdf_paywalled}.`;
        } else {
            cell.textContent = count;
        }
    };

    updateCountCell('pdf_present', counts.pdf_present);
    updateCountCell('is_offtopic', counts.is_offtopic);
    updateCountCell('verified', counts.verified);
    updateCountCell('changed_by', counts.changed_by);
    updateCountCell('verified_by', counts.verified_by);
    updateCountCell('user_comment_state', counts.user_comment_state);
    
    APP_CONFIG.groups.forEach(group => {
        if (group.filter_type === 'tri_state') updateCountCell(group.json_path, counts[group.json_path]);
        else if (['inclusion', 'none'].includes(group.filter_type)) {
            group.fields.forEach(f => updateCountCell(`${group.json_path}.${f.key}`, counts[`${group.json_path}.${f.key}`]));
        }
    });
}

// --- Orchestration ---
function displayStats() {
    document.documentElement.classList.add('busyCursor');
    setTimeout(() => {
        updateCounts();
        
        const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
        statsHooks.collectData.forEach(fn => fn(visibleRows));
        
        destroyAllCharts();
        
        Chart.defaults.font = { size: 12.5, family: 'Arial Narrow', weight: '300' };
        
        statsHooks.renderCharts.forEach(fn => fn());
        
        document.getElementById('statsModal').offsetHeight;
        document.getElementById('statsModal').classList.add('modal-active');
        document.documentElement.classList.remove('busyCursor');
    }, 250); //to sync with chart animations, do NOT change or remove this
}

function displayAbout() { 
    document.getElementById('aboutModal').offsetHeight; 
    document.getElementById('aboutModal').classList.add('modal-active'); 
}
function closeSmallModal() { document.getElementById('aboutModal').classList.remove('modal-active'); }
function closeModal() { document.getElementById('statsModal').classList.remove('modal-active'); }

// --- Event Listeners ---
document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('stackingToggle').checked = false;
    document.getElementById('cumulativeToggle').checked = false;
    document.getElementById('pieToggle').checked = false;

    document.getElementById('stats-btn').addEventListener('click', function () { 
        document.documentElement.classList.add('busyCursor'); 
        displayStats(); 
    });
    document.getElementById('about-btn').addEventListener('click', displayAbout);
    document.querySelector('#statsModal .close').addEventListener('click', closeModal);
    document.querySelector('#aboutModal .close').addEventListener('click', closeSmallModal);

    document.getElementById('stackingToggle').addEventListener('change', function () {
        isStacked = this.checked;
        Object.values(window.chartRegistry).forEach(chart => {
            if (chart.options.scales?.y) {
                chart.options.scales.y.stacked = isStacked;
                chart.options.scales.x.stacked = isStacked;
            }
            chart.data.datasets.forEach(dataset => { dataset.fill = isStacked; });
            chart.update();
        });
        reorderDatasetsForStacking();
    });

    document.getElementById('cumulativeToggle').addEventListener('change', function () {
        isCumulative = this.checked;
        statsHooks.renderCharts.forEach(fn => fn());
        if (isStacked) reorderDatasetsForStacking();
    });

    document.getElementById('pieToggle').addEventListener('change', function () {
        showPieCharts = this.checked;
        statsHooks.renderCharts.forEach(fn => fn());
    });

    //Keyboard shortcuts:
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeModal(); closeSmallModal();
            if (document.body.id !== "html-export") {
                if (typeof closeBatchModal === 'function') closeBatchModal();
                if (typeof closeExporthModal === 'function') closeExporthModal();
                if (typeof closeImportModal === 'function') closeImportModal();
            }
        }
        if (event.key === 'F1') { event.preventDefault(); displayAbout(); }
        if (event.key === 'F3') { event.preventDefault();searchInput.focus(); }
        if (event.key === 'F4') {
            event.preventDefault(); document.documentElement.classList.add('busyCursor'); closeSmallModal();
            if (document.body.id !== "html-export") {
                if (typeof closeBatchModal === 'function') closeBatchModal();
                if (typeof closeExporthModal === 'function') closeExporthModal();
                if (typeof closeImportModal === 'function') closeImportModal();
            }
            displayStats();
        }
    });

    window.addEventListener('click', function (event) {
        if (event.target === document.getElementById('statsModal') || event.target === document.getElementById('aboutModal')) { 
            closeModal(); closeSmallModal(); 
        }
        if (document.body.id !== 'html-export') {
            const batchModal = document.getElementById("batchModal");
            const importModal = document.getElementById("importModal");
            const exportModal = document.getElementById("exportModal");
            if (event.target === batchModal || event.target === importModal || event.target === exportModal) {
                if (typeof closeBatchModal === 'function') closeBatchModal();
                if (typeof closeImportModal === 'function') closeImportModal();
                if (typeof closeExporthModal === 'function') closeExporthModal();
            }
        }
    });
});