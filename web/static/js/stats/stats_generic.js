/**
 * Generic domain-agnostic statistics logic.
 */

registerStatsHook('collectData', collectGenericStatsData);
registerStatsHook('renderCharts', renderGenericStats);

function collectGenericStatsData(visibleRows) {
    buildStatsLists(visibleRows);
}

function buildStatsLists(visibleRows) {
    const stats = { journals: {}, conferences: {}, keywords: {}, authors: {}, researchAreas: {}, slot1: {}, slot2: {} };
    
    const statsListFields = APP_CONFIG.editable_fields.filter(f => f.stats_list).slice(0, 2);
    const slot1Field = statsListFields[0];
    const slot2Field = statsListFields[1];

    visibleRows.forEach(row => {
        const journalCell = row.cells[COL_IDX_JOURNAL];
        const typeCell = row.cells[COL_IDX_TYPE];
        
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
            document.getElementById('search-input').value = nameSpan.textContent.trim(); 
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
            document.getElementById('search-input').value = nameSpan.textContent.trim(); 
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
        
        const colors = [    'hsla(347, 70%, 39%, 0.75)', 'hsla(204, 82%, 28%, 0.75)',  'hsla(42, 100%, 28%, 0.75)',
                            'hsla(180, 48%, 28%, 0.75)', 'hsla(260, 100%, 40%, 0.75)', 'hsla(30, 100%, 33%, 0.75)',
                            'hsla(0, 0%, 38%, 0.75)',    'hsla(147, 48%, 38%, 0.75)'];
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

function calculateJournalConferenceStats(visibleRows) {
    const journalCounts = {}, conferenceCounts = {};
    visibleRows.forEach(row => {
        const journalCell = row.cells[COL_IDX_JOURNAL];
        const typeCell = row.cells[COL_IDX_TYPE];
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
    
    destroyChartInstance('surveyVsImplLineChart');
    registerChartInstance('surveyVsImplLineChart', renderGenericLineChart(
        document.getElementById('surveyVsImplLineChart').getContext('2d'), 
        lineData.surveyImpl, 
        'Survey vs Primary Papers per Year'
    ));

    destroyChartInstance('pubTypesPerYearLineChart');
    registerChartInstance('pubTypesPerYearLineChart', renderGenericLineChart(
        document.getElementById('pubTypesPerYearLineChart').getContext('2d'), 
        lineData.pubTypes, 
        'Publication Types per Year'
    ));
}

function renderGenericStats() {
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const totalVisiblePaperCount = visibleRows.length;
    
    let totalAllPaperCount;
    if (document.body.id === 'html-export') {
        // In a static export, the "total" is simply all the rows that were exported into the file
        totalAllPaperCount = document.querySelectorAll('#papersTable tbody tr[data-paper-id]').length;
    } else {
        // In the live app, read from the server-rendered footer
        const totalPaperCountCell = document.getElementById('total-papers-count');
        totalAllPaperCount = totalPaperCountCell ? parseInt(totalPaperCountCell.textContent.trim(), 10) : 0;
    }
    
    destroyChartInstance('surveyVsImplDistChart');
    registerChartInstance('surveyVsImplDistChart', renderBarOrPieChart(
        document.getElementById('surveyVsImplPieChart').getContext('2d'), 
        prepareSurveyVsImplDistData(totalVisiblePaperCount), 
        'Survey vs Primary', 
        showPieCharts ? 'pie' : 'bar'
    ));
    
    destroyChartInstance('pubTypesDistChart');
    registerChartInstance('pubTypesDistChart', renderBarOrPieChart(
        document.getElementById('publTypePieChart').getContext('2d'), 
        preparePubTypesDistData(), 
        'Pub Types', 
        showPieCharts ? 'pie' : 'bar'
    ));
    
    destroyChartInstance('scopeDistChart');
    registerChartInstance('scopeDistChart', renderBarOrPieChart(
        document.getElementById('OffTopicPieChart').getContext('2d'), 
        prepareScopeData(totalVisiblePaperCount, totalAllPaperCount), 
        'Scope', 
        showPieCharts ? 'pie' : 'bar'
    ));

    destroyChartInstance('relevanceHistogram');
    registerChartInstance('relevanceHistogram', renderHistogram(
        document.getElementById('RelevanceHistogram').getContext('2d'), 
        prepareRelevanceHistogramData(visibleRows), 
        'Relevance Histogram'
    ));
    
    destroyChartInstance('estScoreHistogram');
    registerChartInstance('estScoreHistogram', renderHistogram(
        document.getElementById('estScoreHistogram').getContext('2d'), 
        prepareEstScoreHistogramData(visibleRows), 
        'Estimated Score Histogram'
    ));
    
    renderGenericLineCharts();

    const { journals, conferences } = calculateJournalConferenceStats(visibleRows);
    populateMetricsTableDirectly(journals, conferences);
}

document.addEventListener('DOMContentLoaded', function () {
    const cloudToggle = document.getElementById('cloudToggle');
    cloudToggle.checked = true;
    cloudToggle.addEventListener('change', function() { toggleCloud(); });
});