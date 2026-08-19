/**
 * Domain-specific statistics logic (PCB AOI).
 */

registerStatsHook('collectData', collectDomainYearlyData);
registerStatsHook('renderCharts', renderDomainCharts);

// --- Color Definitions ---
const techniquesColors = [
    'hsla(347, 60%, 69%, 0.95)', 'hsla(204, 62%, 57%, 0.95)', 'hsla(52, 80%, 47%, 0.95)',
    'hsla(180, 32%, 52%, 0.95)', 'hsla(260, 60%, 66%, 0.95)', 'hsla(25, 70%, 63%, 0.95)',
    'hsla(0, 0%, 68%, 0.95)', 'hsla(96, 66%, 49%, 0.95)'
];
const techniquesBorderColors = [
    'hsla(347, 70%, 39%, 0.75)', 'hsla(204, 82%, 28%, 0.75)', 'hsla(42, 100%, 28%, 0.75)',
    'hsla(180, 48%, 28%, 0.75)', 'hsla(260, 100%, 40%, 0.75)', 'hsla(30, 100%, 33%, 0.75)',
    'hsla(0, 0%, 38%, 0.75)', 'hsla(147, 48%, 38%, 0.75)'
];
const featuresColorsOriginalOrder = [
    'hsla(130, 27%, 60%, 0.95)', 'hsla(130, 27%, 60%, 0.95)', 'hsla(130, 27%, 60%, 0.95)',
    'hsla(0, 0%, 68%, 0.95)', 'hsla(0, 0%, 68%, 0.95)', 'hsla(0, 0%, 68%, 0.95)',
    'hsla(0, 0%, 68%, 0.95)', 'hsla(0, 0%, 68%, 0.95)', 'hsla(347, 70%, 72%, 0.95)',
    'hsla(347, 70%, 72%, 0.95)', 'hsla(347, 70%, 72%, 0.95)', 'hsla(347, 70%, 72%, 0.95)',
    'hsla(204, 88%, 70%, 0.95)', 'hsla(284, 88%, 70%, 0.95)'
];
const featuresBorderColorsOriginalOrder = [
    'hsla(144, 83%, 28%, 0.75)', 'hsla(144, 82%, 28%, 0.75)', 'hsla(144, 82%, 28%, 0.75)',
    'hsla(0, 0%, 38%, 0.75)', 'hsla(0, 0%, 38%, 0.75)', 'hsla(0, 0%, 38%, 0.75)',
    'hsla(0, 0%, 38%, 0.75)', 'hsla(0, 0%, 38%, 0.75)', 'hsla(347, 70%, 39%, 0.75)',
    'hsla(347, 70%, 39%, 0.75)', 'hsla(347, 70%, 39%, 0.75)', 'hsla(347, 70%, 39%, 0.75)',
    'hsla(219, 100%, 40%, 0.75)', 'hsla(284, 82%, 47%, 0.75)'
];

// --- Field Mappings ---
const FIELD_LABELS = {
    'features.tracks': '(Bare PCB) Tracks', 'features.holes': '(Bare PCB) Holes', 'features.bare_pcb_other': '(Bare PCB) Other',
    'features.solder_insufficient': '(Solder) Insufficient', 'features.solder_excess': '(Solder) Excess', 'features.solder_void': '(Solder) Voids',
    'features.solder_crack': '(Solder) Cracks', 'features.solder_other': '(Solder) Other', 'features.orientation': '(PCBA) Orientation/Polarity',
    'features.wrong_component': '(PCBA) Wrong Component', 'features.missing_component': '(PCBA) Missing Component', 'features.component_other': '(PCBA) Other',
    'features.cosmetic': 'Cosmetic', 'features.other': 'Other',
    'technique.classic_cv_based': 'Classic CV', 'technique.ml_traditional': 'Traditional ML', 'technique.dl_cnn_classifier': 'CNN Classifier',
    'technique.dl_cnn_detector': 'CNN Detector', 'technique.dl_rcnn_detector': 'R-CNN Detector', 'technique.dl_transformer': 'Transformer',
    'technique.dl_other': 'Other DL', 'technique.hybrid': 'Hybrid', 'technique.available_dataset': 'Datasets'
};

const TECHNIQUE_FIELDS = [
    'technique.classic_cv_based', 'technique.ml_traditional', 'technique.dl_cnn_classifier', 'technique.dl_cnn_detector', 
    'technique.dl_rcnn_detector', 'technique.dl_transformer', 'technique.dl_other', 'technique.hybrid'
];
const TECHNIQUE_FIELD_COLOR_MAP = {
    'technique.classic_cv_based': 0, 'technique.ml_traditional': 1, 'technique.dl_cnn_classifier': 2, 'technique.dl_cnn_detector': 3,
    'technique.dl_rcnn_detector': 4, 'technique.dl_transformer': 5, 'technique.dl_other': 6, 'technique.hybrid': 7
};

const FEATURE_FIELDS = [
    'features.tracks', 'features.holes', 'features.bare_pcb_other',
    'features.solder_insufficient', 'features.solder_excess', 'features.solder_void', 'features.solder_crack', 'features.solder_other',
    'features.orientation', 'features.missing_component', 'features.wrong_component', 'features.component_other',
    'features.cosmetic', 'features.other'
];
const FEATURE_FIELD_INDEX_MAP = {
    'features.tracks': 0, 'features.holes': 1, 'features.bare_pcb_other': 2,
    'features.solder_insufficient': 3, 'features.solder_excess': 4, 'features.solder_void': 5, 'features.solder_crack': 6, 'features.solder_other': 7,
    'features.orientation': 8, 'features.missing_component': 9, 'features.wrong_component': 10, 'features.component_other': 11,
    'features.cosmetic': 12, 'features.other': 13
};

const featureColorGroups = {
    0: { label: 'Bare PCB Defects', fields: ['features.tracks', 'features.holes', 'features.bare_pcb_other'] },
    3: { label: 'Solder Defects', fields: ['features.solder_insufficient', 'features.solder_excess', 'features.solder_void', 'features.solder_crack', 'features.solder_other'] },
    8: { label: 'PCB Assembly Defects', fields: ['features.orientation', 'features.missing_component', 'features.wrong_component', 'features.component_other'] },
    12: { label: 'Cosmetic', fields: ['features.cosmetic'] },
    13: { label: 'Other', fields: ['features.other'] }
};

// --- Data Collection Hook ---
function collectDomainYearlyData(visibleRows) {
    const yearlyTechniques = {};
    const yearlyFeatures = {};
    
    visibleRows.forEach(row => {
        const yearCell = row.cells[COL_IDX_YEAR]; 
        const yearText = yearCell ? yearCell.textContent.trim() : '';
        const year = yearText ? parseInt(yearText, 10) : null;
        
        if (year && !isNaN(year)) {
            if (!yearlyTechniques[year]) {
                yearlyTechniques[year] = {};
                TECHNIQUE_FIELDS.forEach(f => yearlyTechniques[year][f] = 0);
            }
            if (!yearlyFeatures[year]) {
                yearlyFeatures[year] = {};
                FEATURE_FIELDS.forEach(f => yearlyFeatures[year][f] = 0);
            }
            
            TECHNIQUE_FIELDS.forEach(field => {
                const techCell = row.querySelector(`[data-field="${field}"]`);
                if (techCell && techCell.textContent.trim() === '✔️') yearlyTechniques[year][field]++;
            });
            
            FEATURE_FIELDS.forEach(field => {
                const featCell = row.querySelector(`[data-field="${field}"]`);
                if (featCell && featCell.textContent.trim() === '✔️') yearlyFeatures[year][field]++;
            });
        }
    });
    
    latestYearlyData.techniques = yearlyTechniques;
    latestYearlyData.features = yearlyFeatures;
}

// --- Chart Data Preparation ---
function prepareFeaturesData() {
    const featureGroupToggle = document.getElementById('featureGroupToggle');
    const isGrouped = featureGroupToggle && featureGroupToggle.checked;
    const counts = latestCounts;

    if (showPieCharts) {
        let labels = [], values = [], backgroundColors = [];
        if (isGrouped) {
            Object.keys(featureColorGroups).forEach(baseColorIndex => {
                const group = featureColorGroups[baseColorIndex];
                labels.push(group.label);
                let groupSum = 0;
                group.fields.forEach(field => { groupSum += (counts[field] || 0); });
                values.push(groupSum);
                backgroundColors.push(featuresColorsOriginalOrder[parseInt(baseColorIndex)]);
            });
        } else {
            const featuresData = FEATURE_FIELDS.map(field => ({
                label: FIELD_LABELS[field] || field, value: counts[field] || 0,
                originalIndex: FEATURE_FIELD_INDEX_MAP[field] !== undefined ? FEATURE_FIELD_INDEX_MAP[field] : -1
            }));
            let processedData = [...featuresData].sort((a, b) => b.value - a.value);
            labels = processedData.map(item => item.label);
            values = processedData.map(item => item.value);
            backgroundColors = processedData.map(item => featuresColorsOriginalOrder[item.originalIndex] || 'rgba(0,0,0,0.1)');
        }
        return { labels, datasets: [{ label: 'Features Count', data: values, backgroundColor: backgroundColors, borderColor: "#333", borderWidth: 1, hoverOffset: 4 }] };
    } else {
        let finalFeaturesLabels = [], finalFeaturesValues = [], finalFeaturesBackgroundColors = [];
        if (isGrouped) {
            Object.keys(featureColorGroups).forEach(baseColorIndexStr => {
                const baseColorIndex = parseInt(baseColorIndexStr);
                const group = featureColorGroups[baseColorIndex];
                const groupData = group.fields.map(field => ({
                    label: FIELD_LABELS[field] || field, value: counts[field] || 0,
                    originalIndex: FEATURE_FIELD_INDEX_MAP[field] !== undefined ? FEATURE_FIELD_INDEX_MAP[field] : -1
                }));
                groupData.sort((a, b) => b.value - a.value);
                groupData.forEach(item => {
                    finalFeaturesLabels.push(item.label);
                    finalFeaturesValues.push(item.value);
                    finalFeaturesBackgroundColors.push(featuresColorsOriginalOrder[baseColorIndex]);
                });
            });
        } else {
            const featuresData = FEATURE_FIELDS.map(field => ({
                label: FIELD_LABELS[field] || field, value: counts[field] || 0,
                originalIndex: FEATURE_FIELD_INDEX_MAP[field] !== undefined ? FEATURE_FIELD_INDEX_MAP[field] : -1
            }));
            let processedData = [...featuresData].sort((a, b) => b.value - a.value);
            finalFeaturesLabels = processedData.map(item => item.label);
            finalFeaturesValues = processedData.map(item => item.value);
            finalFeaturesBackgroundColors = processedData.map(item => featuresColorsOriginalOrder[item.originalIndex] || 'rgba(0,0,0,0.1)');
        }
        return { labels: finalFeaturesLabels, datasets: [{ label: 'Features Count', data: finalFeaturesValues, backgroundColor: finalFeaturesBackgroundColors, borderColor: "#333", borderWidth: 1, hoverOffset: 4 }] };
    }
}

function prepareTechniquesData() {
    const counts = latestCounts;
    const techniquesData = TECHNIQUE_FIELDS.map(field => ({
        label: FIELD_LABELS[field] || field, value: counts[field] || 0,
        originalIndex: TECHNIQUE_FIELD_COLOR_MAP[field] !== undefined ? TECHNIQUE_FIELD_COLOR_MAP[field] : -1
    }));
    techniquesData.sort((a, b) => b.value - a.value);
    return {
        labels: techniquesData.map(item => item.label),
        datasets: [{
            label: 'Techniques Count', data: techniquesData.map(item => item.value),
            backgroundColor: techniquesData.map(item => techniquesColors[item.originalIndex] || 'rgba(0,0,0,0.1)'),
            borderColor: "#333", borderWidth: 1, hoverOffset: 4
        }]
    };
}

function prepareSMTvsTHTData() {
    const counts = latestCounts;
    const smtCount = counts['is_smt'] || 0;
    const thtCount = counts['is_through_hole'] || 0;
    return {
        labels: ['SMT', 'THT'],
        datasets: [{
            label: 'SMT vs THT Distribution',
            data: [smtCount, thtCount],
            backgroundColor: ['hsla(180, 32%, 52%, 0.95)', 'hsla(260, 60%, 66%, 0.95)'],
            borderColor: "#333", borderWidth: 1, hoverOffset: 4
        }]
    };
}

// --- Chart Rendering ---
function renderDomainLineCharts() {
    // 1. Techniques per Year
    const techniquesYearlyData = latestYearlyData.techniques || {};
    const yearsForTechniques = Object.keys(techniquesYearlyData).map(Number).sort((a, b) => a - b);
    
    const techniqueLineDatasets = TECHNIQUE_FIELDS.map(field => {
        const label = FIELD_LABELS[field] || field;
        let data = yearsForTechniques.map(year => techniquesYearlyData[year]?.[field] || 0);
        if (isCumulative) data = calculateCumulativeData(data);
        
        const originalIndex = TECHNIQUE_FIELD_COLOR_MAP[field] !== undefined ? TECHNIQUE_FIELD_COLOR_MAP[field] : -1;
        const borderColor = (originalIndex !== -1 && techniquesBorderColors[originalIndex]) ? techniquesBorderColors[originalIndex] : 'rgba(0, 0, 0, 1)';
        const backgroundColor = (originalIndex !== -1 && techniquesColors[originalIndex]) ? techniquesColors[originalIndex] : 'rgba(0, 0, 0, 0.1)';
        
        return { label, data, borderColor, backgroundColor, fill: isStacked, tension: 0.25 };
    });

    const techniquesPerYearCtx = document.getElementById('techniquesPerYearLineChart').getContext('2d');
    destroyChartInstance('techniquesPerYearLineChart');
    if (techniqueLineDatasets.length > 0) {
        registerChartInstance('techniquesPerYearLineChart', new Chart(techniquesPerYearCtx, {
            type: 'line',
            data: { labels: yearsForTechniques, datasets: techniqueLineDatasets },
            options: {
                responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle', generateLabels: cumulativeLegendLabels } },
                    title: { display: false, text: 'Techniques per Year' },
                    tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${context.raw}` } }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 }, stacked: isStacked },
                    x: { ticks: { precision: 0 }, stacked: isStacked }
                }
            }
        }));
    } else {
        registerChartInstance('techniquesPerYearLineChart', new Chart(techniquesPerYearCtx, {
            type: 'line', data: { labels: [], datasets: [] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: 'Techniques per Year (No Data)' } } }
        }));
    }

    // 2. Features per Year
    const featuresYearlyData = latestYearlyData.features || {};
    const yearsForFeatures = Object.keys(featuresYearlyData).map(Number).sort((a, b) => a - b);
    
    const aggregatedFeatureDataByColor = {};
    Object.keys(featureColorGroups).forEach(baseColorIndex => {
        const group = featureColorGroups[baseColorIndex];
        aggregatedFeatureDataByColor[group.label] = yearsForFeatures.map(year => {
            return group.fields.reduce((sum, field) => sum + (featuresYearlyData[year]?.[field] || 0), 0);
        });
    });
    
    const aggregatedFeatureDataByColorFinal = {};
    Object.keys(aggregatedFeatureDataByColor).forEach(label => {
        let data = aggregatedFeatureDataByColor[label];
        if (isCumulative) data = calculateCumulativeData(data);
        aggregatedFeatureDataByColorFinal[label] = data;
    });

    const featureLineDatasets = Object.keys(featureColorGroups).map(baseColorIndex => {
        const group = featureColorGroups[baseColorIndex];
        const colorIndex = parseInt(baseColorIndex);
        const borderColor = featuresBorderColorsOriginalOrder[colorIndex] || 'rgba(0,0,0,1)';
        const backgroundColor = featuresColorsOriginalOrder[colorIndex] || 'rgba(0,0,0,0.1)';
        
        return {
            label: group.label, data: aggregatedFeatureDataByColorFinal[group.label],
            borderColor, backgroundColor, fill: isStacked, tension: 0.25
        };
    });

    const featuresPerYearCtx = document.getElementById('featuresPerYearLineChart').getContext('2d');
    destroyChartInstance('featuresPerYearLineChart');
    if (featureLineDatasets.length > 0) {
        registerChartInstance('featuresPerYearLineChart', new Chart(featuresPerYearCtx, {
            type: 'line',
            data: { labels: yearsForFeatures, datasets: featureLineDatasets },
            options: {
                responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle', generateLabels: cumulativeLegendLabels } },
                    title: { display: false, text: 'Features per Year' },
                    tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${context.raw}` } }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 }, stacked: isStacked },
                    x: { ticks: { precision: 0 }, stacked: isStacked }
                }
            }
        }));
    } else {
        registerChartInstance('featuresPerYearLineChart', new Chart(featuresPerYearCtx, {
            type: 'line', data: { labels: [], datasets: [] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: 'Features per Year (No Data)' } } }
        }));
    }
    
    if (isStacked) reorderDatasetsForStacking();
}

function renderDomainCharts() {
    destroyChartInstance('techniquesChart');
    registerChartInstance('techniquesChart', renderBarOrPieChart(
        document.getElementById('techniquesPieChart').getContext('2d'), 
        prepareTechniquesData(), 
        'Techniques Count', 
        showPieCharts ? 'pie' : 'bar'
    ));

    destroyChartInstance('featuresChart');
    registerChartInstance('featuresChart', renderBarOrPieChart(
        document.getElementById('featuresPieChart').getContext('2d'), 
        prepareFeaturesData(), 
        'Features Count', 
        showPieCharts ? 'pie' : 'bar'
    ));
    
    destroyChartInstance('smtVsThtChart');
    registerChartInstance('smtVsThtChart', renderBarOrPieChart(
        document.getElementById('SMTvsTHTPieChart').getContext('2d'), 
        prepareSMTvsTHTData(), 
        'SMT vs THT', 
        showPieCharts ? 'pie' : 'bar'
    ));
    
    renderDomainLineCharts();
}

// --- Event Listeners ---
document.addEventListener('DOMContentLoaded', () => {
    const featureGroupToggle = document.getElementById('featureGroupToggle');
    featureGroupToggle.addEventListener('change', function () {
        const ctx = document.getElementById('featuresPieChart').getContext('2d');
        destroyChartInstance('featuresChart');
        registerChartInstance('featuresChart', renderBarOrPieChart(ctx, prepareFeaturesData(), 'Features Count', showPieCharts ? 'pie' : 'bar'));
    });
});