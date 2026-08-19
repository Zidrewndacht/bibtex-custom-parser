// stats_core.js
let latestCounts = {};
let latestYearlyData = {};
let isStacked = false;
let isCumulative = false;
let showPieCharts = false;

const statsBtn = document.getElementById('stats-btn');
const aboutBtn = document.getElementById('about-btn');
const modal = document.getElementById('statsModal');
const modalSmall = document.getElementById('aboutModal');
const spanClose = document.querySelector('#statsModal .close');
const smallClose = document.querySelector('#aboutModal .close');

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

function collectStatsData() {
    const counts = {};
    const yearlySurveyImpl = {};
    const yearlyPubTypes = {};
    const yearlyModels = {};

    APP_CONFIG.groups.forEach(group => {
        if (group.filter_type === 'tri_state') counts[group.json_path] = 0;
        else if (['inclusion', 'none'].includes(group.filter_type)) {
            group.fields.forEach(f => counts[`${group.json_path}.${f.key}`] = 0);
        }
    });
    
    Object.assign(counts, { pdf_present: 0, pdf_annotated: 0, pdf_paywalled: 0, is_offtopic: 0, verified: 0, changed_by: 0, verified_by: 0, user_comment_state: 0, model: 0 });

    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const visiblePaperCount = visibleRows.length;
    const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
    const loadedPaperCount = allRows.length;

    visibleRows.forEach(row => {
        const pdfCell = row.cells[0];
        const pdfContent = pdfCell.textContent.trim();
        if (pdfContent === '📕') counts.pdf_present++;
        else if (pdfContent === '📗') { counts.pdf_annotated++; counts.pdf_present++; }
        else if (pdfContent === '💰') counts.pdf_paywalled++;

        if (row.querySelector('[data-field="is_offtopic"]').textContent.trim() === '✔️') counts.is_offtopic++;
        if (row.querySelector('[data-field="verified"]').textContent.trim() === '✔️') counts.verified++;
        if (row.querySelector('[data-field="changed_by"]').innerHTML.includes('👤')) counts.changed_by++;
        if (row.querySelector('[data-field="verified_by"]').innerHTML.includes('👤')) counts.verified_by++;
        if (row.querySelector('[data-field="user_comment_state"]').textContent.trim() === '✔️') counts.user_comment_state++;

        APP_CONFIG.groups.forEach(group => {
            if (group.filter_type === 'tri_state') {
                if (row.querySelector(`[data-field="${group.json_path}"]`).textContent.trim() === '✔️') counts[group.json_path]++;
            } else if (['inclusion', 'none'].includes(group.filter_type)) {
                group.fields.forEach(f => {
                    if (row.querySelector(`[data-field="${group.json_path}.${f.key}"]`).textContent.trim() === '✔️') counts[`${group.json_path}.${f.key}`]++;
                });
            }
        });

        const modelCell = row.querySelector('td.hidden-data-cell[data-field="technique_model"]') || row.querySelector('td[data-field="model"]') || row.querySelector('td[data-field="model_name"]');
        if (modelCell) {
            const modelText = modelCell.textContent.trim();
            if (modelText) counts.model += modelText.split(/[,;]/).map(m => m.trim()).filter(m => m !== '').length;
        }

        const yearCell = row.cells[2];
        const year = parseInt(yearCell.textContent.trim(), 10);

        if (!isNaN(year)) {
            if (!yearlySurveyImpl[year]) yearlySurveyImpl[year] = { surveys: 0, impl: 0 };
            if (!yearlyPubTypes[year]) yearlyPubTypes[year] = {};
            if (!yearlyModels[year]) yearlyModels[year] = {};

            const isSurvey = row.querySelector('[data-field="is_survey"]').textContent.trim() === '✔️';
            isSurvey ? yearlySurveyImpl[year].surveys++ : yearlySurveyImpl[year].impl++;

            const typeCell = row.cells[5];
            const rawType = (typeCell.getAttribute('title') || typeCell.textContent.trim() || '').toLowerCase();
            if (rawType) {
                const mappedType = mapPubType(rawType);
                yearlyPubTypes[year][mappedType] = (yearlyPubTypes[year][mappedType] || 0) + 1;
            }

            if (modelCell && modelCell.textContent.trim()) {
                modelCell.textContent.trim().split(/[,;]/).map(m => m.trim()).filter(m => m).forEach(m => {
                    yearlyModels[year][m] = (yearlyModels[year][m] || 0) + 1;
                });
            }
        }
    });

    latestCounts = counts;
    latestYearlyData = { surveyImpl: yearlySurveyImpl, pubTypes: yearlyPubTypes, models: yearlyModels };
    
    if (typeof collectDomainYearlyData === 'function') collectDomainYearlyData(visibleRows);

    if (document.body.id === 'html-export') {
        document.getElementById('visible-count-cell').innerHTML = `<strong>${visiblePaperCount}</strong> paper${visiblePaperCount !== 1 ? 's' : ''} of <strong>${document.getElementById('total-papers-count').textContent}</strong>`;
    } else {
        document.getElementById('loaded-papers-count').textContent = loadedPaperCount;
        document.getElementById('visible-papers-count').textContent = visiblePaperCount;
    }

    const updateCountCell = (field, count) => {
        const cell = document.querySelector(`[data-count-field="${field}"]`) || document.getElementById(`count-${field.replace(/\./g, '_')}`);
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

function buildStatsLists() {
    const stats = { journals: {}, conferences: {}, keywords: {}, authors: {}, researchAreas: {}, slot1: {}, slot2: {} };
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    
    // Dynamically map the first two YAML fields marked with stats_list: true
    const statsListFields = APP_CONFIG.editable_fields.filter(f => f.stats_list).slice(0, 2);
    const slot1Field = statsListFields[0];
    const slot2Field = statsListFields[1];

    visibleRows.forEach(row => {
        const journalCell = row.cells[4];
        const typeCell = row.cells[5];
        
        const journalConfName = journalCell.textContent.trim();
        const typeValue = (typeCell.getAttribute('title') || typeCell.textContent.trim()).toLowerCase();
        if (journalConfName) {
            const mappedType = mapPubType(typeValue);
            if (mappedType === 'Journal') stats.journals[journalConfName] = (stats.journals[journalConfName] || 0) + 1;
            else if (mappedType === 'Conference') stats.conferences[journalConfName] = (stats.conferences[journalConfName] || 0) + 1;
        }

        const keywordsCell = row.querySelector('td.hidden-data-cell[data-field="keywords"]');
        if (keywordsCell && keywordsCell.textContent.trim()) {
            keywordsCell.textContent.trim().split(';').map(kw => kw.trim()).filter(kw => kw.length > 0).forEach(keyword => {
                stats.keywords[keyword] = (stats.keywords[keyword] || 0) + 1;
            });
        }

        const authorsCell = row.querySelector('td.hidden-data-cell[data-field="authors"]');
        if (authorsCell && authorsCell.textContent.trim()) {
            authorsCell.textContent.trim().split(';').map(a => a.trim()).filter(a => a.length > 0).forEach(author => {
                stats.authors[author] = (stats.authors[author] || 0) + 1;
            });
        }

        APP_CONFIG.editable_fields.forEach(field => {
            if (field.json_path === 'research_area') {
                const cell = row.querySelector(`td.hidden-data-cell[data-field="${field.json_path.replace(/\./g, '_')}"]`);
                if (cell && cell.textContent.trim()) {
                    stats.researchAreas[cell.textContent.trim()] = (stats.researchAreas[cell.textContent.trim()] || 0) + 1;
                }
            }
        });

        if (slot1Field) {
            const cell = row.querySelector(`td.hidden-data-cell[data-field="${slot1Field.json_path.replace(/\./g, '_')}"]`);
            if (cell && cell.textContent.trim()) {
                cell.textContent.trim().split(/[,;]/).map(m => m.trim()).filter(m => m.length > 0).forEach(val => {
                    stats.slot1[val] = (stats.slot1[val] || 0) + 1;
                });
            }
        }

        if (slot2Field) {
            const cell = row.querySelector(`td.hidden-data-cell[data-field="${slot2Field.json_path.replace(/\./g, '_')}"]`);
            if (cell && cell.textContent.trim()) {
                cell.textContent.trim().split(/[,;]/).map(m => m.trim()).filter(m => m.length > 0 && m.toLowerCase() !== 'none' && m.toLowerCase() !== 'n/a').forEach(val => {
                    stats.slot2[val] = (stats.slot2[val] || 0) + 1;
                });
            }
        }
    });

    populateList('journalStatsList', stats.journals);
    populateList('conferenceStatsList', stats.conferences);
    populateList('keywordStatsList', stats.keywords);
    populateList('authorStatsList', stats.authors);
    populateList('researchAreaStatsList', stats.researchAreas);
    //Dynamic YAML-configurable lists:
    populateSimpleList('slot1StatsList', stats.slot1);
    populateSimpleList('slot2StatsList', stats.slot2);

    if (document.getElementById('cloudToggle').checked) toggleCloud();
}

function populateList(listElementId, dataObj) {
    const listElement = document.getElementById(listElementId);
    listElement.innerHTML = '';
    const sortedEntries = Object.entries(dataObj).filter(([name, count]) => count >= 1).sort((a, b) => b[1] !== a[1] ? b[1] - a[1] : a[0].localeCompare(b[0]));
    if (sortedEntries.length === 0) { listElement.innerHTML = '<li><span class="count"></span><span class="name">No items with count >= 1.</span></li>'; return; }
    sortedEntries.forEach(([name, count]) => {
        const listItem = document.createElement('li');
        const escapedName = name.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        listItem.innerHTML = `<span class="count">${count}</span><button type="button" class="search-item-btn" title="Search for &quot;${escapedName.replace(/"/g, "&quot;")}&quot;">🔍</button><span class="name">${escapedName}</span>`;
        listElement.appendChild(listItem);
    });
    listElement.querySelectorAll('.search-item-btn').forEach(button => {
        button.addEventListener('click', function() {
            const nameSpan = this.closest('li').querySelector('.name');
            const searchInput = document.getElementById('search-input');
            searchInput.value = nameSpan.textContent.trim(); 
            closeModal(); 
            applyLocalFilters();
        });
    });
}

function populateSimpleList(listElementId, dataObj) {
    const listElement = document.getElementById(listElementId);
    listElement.innerHTML = '';
    const sortedEntries = Object.entries(dataObj).sort((a, b) => b[1] !== a[1] ? b[1] - a[1] : a[0].localeCompare(b[0]));
    if (sortedEntries.length === 0) { listElement.innerHTML = '<li><span class="count"></span><span class="name">No items found.</span></li>'; return; }
    sortedEntries.forEach(([name, count]) => {
        const listItem = document.createElement('li');
        const escapedName = name.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        listItem.innerHTML = `<span class="count">${count}</span><button type="button" class="search-item-btn" title="Search for &quot;${escapedName.replace(/"/g, "&quot;")}&quot;">🔍</button><span class="name">${escapedName}</span>`;
        listElement.appendChild(listItem);
    });
    listElement.querySelectorAll('.search-item-btn').forEach(button => {
        button.addEventListener('click', function() {
            const nameSpan = this.closest('li').querySelector('.name');
            const searchInput = document.getElementById('search-input');
            searchInput.value = nameSpan.textContent.trim(); 
            closeModal(); 
            applyLocalFilters();
        });
    });
}

function buildKeywordCloud() {
    const liNodes = document.querySelectorAll('#keywordStatsList li');
    const raw = Array.from(liNodes).map(li => {
        const nameEl = li.querySelector('.name');
        const countEl = li.querySelector('.count');
        if (!nameEl || !countEl) return null;
        return { text: nameEl.textContent.trim(), size: +countEl.textContent };
    }).filter(Boolean);

    if (!raw.length) {
        const prevSvg = document.querySelector('#keywordCloudCanvas svg');
        if (prevSvg) prevSvg.remove();
        return;
    }
    const topK = raw.slice(0, 50);
    const width = document.querySelector('#keywordCloudCanvas').clientWidth || 500;
    const height = 280;
    
    if (typeof d3 === 'undefined' || !d3.layout || !d3.layout.cloud) return;

    const sizeScale = d3.scaleLinear().domain([topK[topK.length - 1].size, topK[0].size]).range([9 , 54]);
    const layout = d3.layout.cloud().size([width, height]).words(topK.map(d => ({ ...d, size: sizeScale(d.size) })))
        .padding(1).rotate(() => 0).font('sans-serif').fontSize(d => d.size).on('end', draw);
    layout.start();

    function draw(words) {
        d3.select('#keywordCloudCanvas').select('svg').remove();
        const svg = d3.select('#keywordCloudCanvas').append('svg').attr('width', width).attr('height', height);
        const colors = (typeof techniquesBorderColors !== 'undefined') ? techniquesBorderColors : ['#333', '#666', '#999'];
        svg.append('g').attr('transform', `translate(${width / 2},${height / 2})`)
            .selectAll('text').data(words).enter().append('text')
            .style('font-size', d => `${d.size}px`).style('font-family', 'sans-serif')
            .style('fill', d => colors[d.text.length % colors.length])
            .attr('text-anchor', 'middle').attr('transform', d => `translate(${d.x},${d.y})rotate(${d.rotate})`)
            .text(d => d.text);
    }
}

function toggleCloud() {
    const list = document.getElementById('keywordStatsList');
    const canvas = document.getElementById('keywordCloudCanvas');
    const on = document.getElementById('cloudToggle').checked;
    list.style.display = on ? 'none' : 'block';
    canvas.style.display = on ? 'block' : 'none';
    if (!on) return;
    if (list.querySelectorAll('li').length === 0) return;
    buildKeywordCloud();
}

function prepareSurveyVsImplDistData(totalVisiblePaperCount) {
    const surveyCount = latestCounts['is_survey'] || 0;
    const implCount = totalVisiblePaperCount - surveyCount;
    return {
        labels: ['Survey', 'Primary'],
        datasets: [{ label: 'Survey vs Primary Distribution', data: [surveyCount, implCount], backgroundColor: ['hsla(204, 42%, 67%, 0.95)', 'hsla(53, 50%, 69%, 0.95)'], borderColor: "#333", borderWidth: 1, hoverOffset: 4 }]
    };
}

function preparePubTypesDistData() {
    const allPubTypesSet = new Set();
    Object.values(latestYearlyData.pubTypes || {}).forEach(yearData => Object.keys(yearData).forEach(mappedType => allPubTypesSet.add(mappedType)));
    const allPubTypes = Array.from(allPubTypesSet).sort();
    const pubTypesDistData = allPubTypes.map(mappedType => {
        let count = 0;
        Object.values(latestYearlyData.pubTypes || {}).forEach(yearData => count += yearData[mappedType] || 0);
        return count;
    });
    const pubTypesDistColors = allPubTypes.map((type, index) => `hsla(${(index * 137.508) % 360}, 30%, 65%, 0.85)`);
    return { labels: allPubTypes, datasets: [{ label: 'Publication Types Distribution', data: pubTypesDistData, backgroundColor: pubTypesDistColors, borderColor: "#333", borderWidth: 1, hoverOffset: 4 }] };
}

function prepareScopeData(totalVisiblePaperCount, totalAllPaperCount) {
    let ontopicCount = 0, offtopicCount = 0;
    if (document.body.id === 'html-export') {
        ontopicCount = totalVisiblePaperCount;
        offtopicCount = Math.max(0, document.querySelectorAll('#papersTable tbody tr[data-paper-id]').length - totalVisiblePaperCount);
    } else {
        ontopicCount = totalVisiblePaperCount;
        offtopicCount = Math.max(0, totalAllPaperCount - totalVisiblePaperCount);
    }
    return { labels: ['On-topic', 'Off-topic'], datasets: [{ label: 'Dataset Scope', data: [ontopicCount, offtopicCount], backgroundColor: ['hsla(96, 66%, 49%, 0.95)', 'hsla(347, 60%, 69%, 0.95)'], borderColor: "#333", borderWidth: 1, hoverOffset: 4 }] };
}

function prepareRelevanceHistogramData(visibleRows) {
    const relevanceCounts = Array(11).fill(0);
    visibleRows.forEach(row => {
        const relevanceCell = row.querySelector('[data-field="relevance"]');
        const relevanceScore = parseInt(relevanceCell.textContent.trim(), 10);
        if (!isNaN(relevanceScore) && relevanceScore >= 0 && relevanceScore <= 10) relevanceCounts[relevanceScore]++;
    });
    return { labels: Array.from({ length: 11 }, (_, i) => i.toString()), datasets: [{ label: 'Relevance Histogram', data: relevanceCounts, backgroundColor: 'hsla(204, 62%, 57%, 0.95)', borderColor: 'hsla(204, 82%, 28%, 0.75)', borderWidth: 1 }] };
}

function prepareEstScoreHistogramData(visibleRows) {
    const estScoreCounts = Array(11).fill(0);
    visibleRows.forEach(row => {
        const estScoreCell = row.querySelector('[data-field="estimated_score"]');
        const estScore = parseInt(estScoreCell.textContent.trim(), 10);
        if (!isNaN(estScore) && estScore >= 0 && estScore <= 10) estScoreCounts[estScore]++;
    });
    return { labels: Array.from({ length: 11 }, (_, i) => i.toString()), datasets: [{ label: 'Estimated Score Histogram', data: estScoreCounts, backgroundColor: 'hsla(52, 80%, 47%, 0.95)', borderColor: 'hsla(42, 100%, 28%, 0.75)', borderWidth: 1 }] };
}

function calculateJournalConferenceStats() {
    const journalCounts = {}, conferenceCounts = {};
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    visibleRows.forEach(row => {
        const journalCell = row.cells[4];
        const typeCell = row.cells[5];
        const journalName = journalCell.textContent.trim();
        const type = (typeCell.getAttribute('title') || typeCell.textContent.trim()).toLowerCase();
        if (journalName) {
            const mappedType = mapPubType(type);
            if (mappedType === 'Journal') journalCounts[journalName] = (journalCounts[journalName] || 0) + 1;
            else if (mappedType === 'Conference') conferenceCounts[journalName] = (conferenceCounts[journalName] || 0) + 1;
        }
    });
    return {
        journals: Object.entries(journalCounts).filter(([n, c]) => c >= 1).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count })),
        conferences: Object.entries(conferenceCounts).filter(([n, c]) => c >= 1).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }))
    };
}

function populateMetricsTableDirectly(journals, conferences) {
    const tableElement = document.getElementById('metricsTableStatsList');
    tableElement.innerHTML = '';
    const totalVisiblePaperCount = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)').length;
    const distinctAuthorsCount = document.getElementById('authorStatsList').querySelectorAll('li').length;
    let papersWithDatasetCount = 0;
    const datasetGroup = APP_CONFIG.groups.find(g => g.name === 'dataset' || g.json_path === 'technique.available_dataset');
    if (datasetGroup) papersWithDatasetCount = latestCounts[datasetGroup.json_path] || 0;
    
    const createRow = (labelHtml, value) => {
        const row = document.createElement('tr');
        const labelCell = document.createElement('td'); labelCell.innerHTML = labelHtml; labelCell.className = 'metric-label';
        const valueCell = document.createElement('td'); valueCell.innerHTML = '<strong>' + value + '</strong>'; valueCell.className = 'metric-value';
        row.appendChild(labelCell); row.appendChild(valueCell); return row;
    };
    tableElement.appendChild(createRow('Total <strong>filtered</strong> articles:', totalVisiblePaperCount));
    tableElement.appendChild(createRow('Total unique <strong>journals</strong>:', journals.length));
    tableElement.appendChild(createRow('Total unique <strong>conferences</strong>:', conferences.length));
    tableElement.appendChild(createRow('Total unique <strong>authors</strong>:', distinctAuthorsCount));
    // if (papersWithDatasetCount > 0 || APP_CONFIG.groups.some(g => g.name === 'dataset')) {
    //     tableElement.appendChild(createRow('Articles mentioning <strong>available dataset</strong>:', papersWithDatasetCount));
    // }
}

function prepareLineChartData() {
    const surveyImplData = latestYearlyData.surveyImpl || {};
    const yearsForSurveyImpl = Object.keys(surveyImplData).map(Number).sort((a, b) => a - b);
    const surveyCounts = yearsForSurveyImpl.map(year => surveyImplData[year].surveys || 0);
    const implCounts = yearsForSurveyImpl.map(year => surveyImplData[year].impl || 0);
    let surveyCountsFinal = isCumulative ? calculateCumulativeData(surveyCounts) : surveyCounts;
    let implCountsFinal = isCumulative ? calculateCumulativeData(implCounts) : implCounts;
    const surveyVsImplDatasets = [
        { label: 'Survey Papers', data: surveyCountsFinal, borderColor: 'hsl(204, 42%, 37%)', backgroundColor: 'hsla(204, 42%, 67%, 0.95)', fill: isStacked, tension: 0.25 },
        { label: 'Primary Papers', data: implCountsFinal, borderColor: 'hsla(38, 70%, 49%, 1.00)', backgroundColor: 'hsla(42, 50%, 69%, 0.95)', fill: isStacked, tension: 0.25 }
    ];
    const pubTypesYearlyData = latestYearlyData.pubTypes || {};
    const yearsForPubTypes = Object.keys(pubTypesYearlyData).map(Number).sort((a, b) => a - b);
    const allPubTypesSet = new Set();
    Object.values(pubTypesYearlyData).forEach(y => Object.keys(y).forEach(k => allPubTypesSet.add(k)));
    const allPubTypes = Array.from(allPubTypesSet).sort();
    const pubTypeLineDatasets = allPubTypes.map((type, index) => {
        const hue = (index * 137.508) % 360;
        let data = yearsForPubTypes.map(year => pubTypesYearlyData[year]?.[type] || 0);
        if (isCumulative) data = calculateCumulativeData(data);
        return { label: type, data: data, borderColor: `hsl(${hue}, 40%, 40%)`, backgroundColor: `hsla(${hue}, 30%, 65%, 0.85)`, fill: isStacked, tension: 0.25 };
    });
    
    return {
        surveyImpl: { labels: yearsForSurveyImpl, datasets: surveyVsImplDatasets },
        pubTypes: { labels: yearsForPubTypes, datasets: pubTypeLineDatasets }
    };
}

function renderGenericLineCharts() {
    const lineData = prepareLineChartData();
    
    const surveyCtx = document.getElementById('surveyVsImplLineChart').getContext('2d');
    if (window.surveyVsImplLineChartInstance) { window.surveyVsImplLineChartInstance.destroy(); window.surveyVsImplLineChartInstance = null; }
    window.surveyVsImplLineChartInstance = renderGenericLineChart(surveyCtx, lineData.surveyImpl, 'Survey vs Primary Papers per Year');

    const pubTypesCtx = document.getElementById('pubTypesPerYearLineChart').getContext('2d');
    if (window.pubTypesPerYearLineChartInstance) { window.pubTypesPerYearLineChartInstance.destroy(); window.pubTypesPerYearLineChartInstance = null; }
    window.pubTypesPerYearLineChartInstance = renderGenericLineChart(pubTypesCtx, lineData.pubTypes, 'Publication Types per Year');
}

function displayStats() {
    document.documentElement.classList.add('busyCursor');
    setTimeout(() => {
        collectStatsData();
        buildStatsLists();
        destroyExistingCharts();
        Chart.defaults.font = { size: 12.5, family: 'Arial Narrow', weight: '300' };
        const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
        const totalVisiblePaperCount = visibleRows.length;
        const totalAllPaperCount = parseInt(document.getElementById('total-papers-count').textContent.trim(), 10);

        const surveyVsImplDistCtx = document.getElementById('surveyVsImplPieChart').getContext('2d');
        window.surveyVsImplDistChartInstance = renderBarOrPieChart(surveyVsImplDistCtx, prepareSurveyVsImplDistData(totalVisiblePaperCount), 'Survey vs Primary', showPieCharts ? 'pie' : 'bar');
        
        const pubTypesDistCtx = document.getElementById('publTypePieChart').getContext('2d');
        window.pubTypesDistChartInstance = renderBarOrPieChart(pubTypesDistCtx, preparePubTypesDistData(), 'Pub Types', showPieCharts ? 'pie' : 'bar');
        
        const scopeCtx = document.getElementById('OffTopicPieChart').getContext('2d');
        window.scopeDistChartInstance = renderBarOrPieChart(scopeCtx, prepareScopeData(totalVisiblePaperCount, totalAllPaperCount), 'Scope', showPieCharts ? 'pie' : 'bar');

        const relevanceHistogramCtx = document.getElementById('RelevanceHistogram').getContext('2d');
        window.relevanceHistogramInstance = renderHistogram(relevanceHistogramCtx, prepareRelevanceHistogramData(visibleRows), 'Relevance Histogram');
        
        const estScoreHistogramCtx = document.getElementById('estScoreHistogram').getContext('2d');
        window.estScoreHistogramInstance = renderHistogram(estScoreHistogramCtx, prepareEstScoreHistogramData(visibleRows), 'Estimated Score Histogram');
        
        renderGenericLineCharts();
        renderDomainCharts();

        const { journals, conferences } = calculateJournalConferenceStats();
        populateMetricsTableDirectly(journals, conferences);
        modal.offsetHeight;
        modal.classList.add('modal-active');
        document.documentElement.classList.remove('busyCursor');
    }, 50);
}

function displayAbout() { modalSmall.offsetHeight; modalSmall.classList.add('modal-active'); }
function closeSmallModal() { modalSmall.classList.remove('modal-active'); }
function closeModal() { modal.classList.remove('modal-active'); }

document.addEventListener('DOMContentLoaded', function () {
    const stackingToggle = document.getElementById('stackingToggle');
    const cumulativeToggle = document.getElementById('cumulativeToggle');
    const pieToggle = document.getElementById('pieToggle');
    const cloudToggle = document.getElementById('cloudToggle');

    stackingToggle.checked = false;
    cumulativeToggle.checked = false;
    pieToggle.checked = false;
    cloudToggle.checked = true;

    statsBtn.addEventListener('click', function () { document.documentElement.classList.add('busyCursor'); displayStats(); });
    aboutBtn.addEventListener('click', displayAbout);
    spanClose.addEventListener('click', closeModal);
    smallClose.addEventListener('click', closeSmallModal);

    stackingToggle.addEventListener('change', function () {
        isStacked = this.checked;
        const charts = [window.surveyVsImplLineChartInstance, window.pubTypesPerYearLineChartInstance, window.techniquesPerYearLineChartInstance, window.featuresPerYearLineChartInstance].filter(Boolean);
        charts.forEach(chart => {
            chart.options.scales.y.stacked = isStacked;
            chart.options.scales.x.stacked = isStacked;
            chart.data.datasets.forEach(dataset => { dataset.fill = isStacked; });
            chart.update();
        });
        reorderDatasetsForStacking();
    });

    cumulativeToggle.addEventListener('change', function () {
        isCumulative = this.checked;
        const updatedLineChartData = prepareLineChartData();
        if (window.surveyVsImplLineChartInstance && updatedLineChartData.surveyImpl) {
            window.surveyVsImplLineChartInstance.data.labels = updatedLineChartData.surveyImpl.labels;
            window.surveyVsImplLineChartInstance.data.datasets = updatedLineChartData.surveyImpl.datasets;
            window.surveyVsImplLineChartInstance.update();
        }
        if (window.pubTypesPerYearLineChartInstance && updatedLineChartData.pubTypes) {
            window.pubTypesPerYearLineChartInstance.data.labels = updatedLineChartData.pubTypes.labels;
            window.pubTypesPerYearLineChartInstance.data.datasets = updatedLineChartData.pubTypes.datasets;
            window.pubTypesPerYearLineChartInstance.update();
        }
        
        renderDomainCharts();
        
        if (isStacked) reorderDatasetsForStacking();
    });

    pieToggle.addEventListener('change', function () {
        showPieCharts = this.checked;
        const chartType = showPieCharts ? 'pie' : 'bar';
        const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
        const totalVisiblePaperCount = visibleRows.length;
        const totalAllPaperCount = parseInt(document.getElementById('total-papers-count').textContent.trim(), 10);
        
        const genericCharts = [
            { instance: window.surveyVsImplDistChartInstance, ctxId: 'surveyVsImplPieChart', dataFn: () => prepareSurveyVsImplDistData(totalVisiblePaperCount) },
            { instance: window.pubTypesDistChartInstance, ctxId: 'publTypePieChart', dataFn: preparePubTypesDistData },
            { instance: window.scopeDistChartInstance, ctxId: 'OffTopicPieChart', dataFn: () => prepareScopeData(totalVisiblePaperCount, totalAllPaperCount) }
        ];
        genericCharts.forEach(c => {
            if (c.instance) c.instance.destroy();
            const ctx = document.getElementById(c.ctxId).getContext('2d');
            const newInst = renderBarOrPieChart(ctx, c.dataFn(), '', chartType);
            if (c.ctxId === 'surveyVsImplPieChart') window.surveyVsImplDistChartInstance = newInst;
            if (c.ctxId === 'publTypePieChart') window.pubTypesDistChartInstance = newInst;
            if (c.ctxId === 'OffTopicPieChart') window.scopeDistChartInstance = newInst;
        });
        renderDomainCharts();
    });

    cloudToggle.addEventListener('change', function() { toggleCloud(); });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeModal(); closeSmallModal();
            if (document.body.id !== "html-export") {
                closeBatchModal();
                closeExporthModal();
                closeImportModal();
            }
        }
        if (event.key === 'F1') { event.preventDefault(); displayAbout(); }
        if (event.key === 'F4') {
            event.preventDefault(); document.documentElement.classList.add('busyCursor'); closeSmallModal();
            if (document.body.id !== "html-export") {
                closeBatchModal();
                closeExporthModal();
                closeImportModal();
            }
            displayStats();
        }
    });

    window.addEventListener('click', function (event) {
        if (event.target === modal || event.target === modalSmall) { closeModal(); closeSmallModal(); }
        if (document.body.id !== 'html-export') {
            const batchModal = document.getElementById("batchModal");
            const importModal = document.getElementById("importModal");
            const exportModal = document.getElementById("exportModal");
            if (event.target === batchModal || event.target === importModal || event.target === exportModal) {
                closeBatchModal();
                closeImportModal();
                closeExporthModal();
            }
        }
    });
});