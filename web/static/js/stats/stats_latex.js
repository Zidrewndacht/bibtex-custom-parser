/**
 * LaTeX generation logic.
 */

function generateLatexJournalsConfs() {
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const journalCounts = {};
    const conferenceCounts = {};

    visibleRows.forEach(row => {
        const journalCell = row.cells[COL_IDX_JOURNAL];
        const typeCell = row.cells[COL_IDX_TYPE];
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

    const filteredJournals = Object.entries(journalCounts).filter(([name, count]) => count >= 2).sort((a, b) => b[1] - a[1]);
    const filteredConferences = Object.entries(conferenceCounts).filter(([name, count]) => count >= 2).sort((a, b) => b[1] - a[1]);

    const dataArray = [];

    filteredJournals.forEach(([name, count]) => {
        const escapedName = name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        dataArray.push({ rowContent: `${count} & Revista & ${escapedName}`, type: 'journal' });
    });

    if (filteredJournals.length > 0 && filteredConferences.length > 0) {
        dataArray.push({ rowContent: " & & ", type: 'separator' });
    }

    filteredConferences.forEach(([name, count]) => {
        const escapedName = name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        dataArray.push({ rowContent: `${count} & Conferência & ${escapedName}`, type: 'conference' });
    });

    const config = {
        caption: "Veículos de Publicação mais Comuns",
        label: "cap32_journals_confs_new", 
        headers: ["Artigos", "Tipo de Veículo", "Veículo"],
        columnSpec: "{@{}llX@{}}", 
        useShading: true 
    };

    return generateLatexTabularx(dataArray, config);
}

function generateLatexAuthors() {
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    const primaryAuthorCounts = {}; 
    const surveyAuthorCounts = {};  

    visibleRows.forEach(row => {
        const authorsCell = row.querySelector('td[data-field="authors"]');
        if (!authorsCell) return;

        const isSurveyCell = row.querySelector('td[data-field="is_survey"]');
        const isSurvey = isSurveyCell && isSurveyCell.textContent.trim() === '✔️';

        const authorsText = authorsCell.textContent.trim();
        if (authorsText) {
            const authorsList = authorsText.split(';').map(author => author.trim()).filter(author => author.length > 0);
            authorsList.forEach(author => {
                if (isSurvey) surveyAuthorCounts[author] = (surveyAuthorCounts[author] || 0) + 1;
                else primaryAuthorCounts[author] = (primaryAuthorCounts[author] || 0) + 1;
            });
        }
    });

    const filteredPrimaryAuthors = Object.entries(primaryAuthorCounts).filter(([name, count]) => count >= 2).sort((a, b) => b[1] - a[1]);
    const filteredSurveyAuthors = Object.entries(surveyAuthorCounts).filter(([name, count]) => count >= 2).sort((a, b) => b[1] - a[1]);

    const primaryData = filteredPrimaryAuthors.map(([name, count]) => ({ name: name, count: count }));
    const surveyData = filteredSurveyAuthors.map(([name, count]) => ({ name: name, count: count }));
    const maxRows = Math.max(primaryData.length, surveyData.length);

    const dataArray = [];
    for (let i = 0; i < maxRows; i++) {
        const primaryRow = primaryData[i];
        const surveyRow = surveyData[i];

        let primaryQty = "", primaryAuthor = "", surveyQty = "", surveyAuthor = "";
        if (primaryRow) {
            primaryQty = primaryRow.count;
            primaryAuthor = primaryRow.name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        }
        if (surveyRow) {
            surveyQty = surveyRow.count;
            surveyAuthor = surveyRow.name.replace(/_/g, "\\_").replace(/&/g, "\\&");
        }

        dataArray.push({ rowContent: `${primaryQty} & ${primaryAuthor} & ${surveyQty} & ${surveyAuthor}` });
    }

    let latexCode = "\\begin{table}[ht]\n";
    latexCode += "\\centering\n\\small\n";
    latexCode += "\t\\caption{Autores por tipo de artigo (>=2 ocorrências)}\n"; 
    latexCode += "\\label{tab:cap32_authors_split}\n"; 
    latexCode += "\\begin{tabularx}{\\textwidth}{@{}lX|lX@{}}\n\\toprule\n";
    latexCode += "\\multicolumn{2}{c}{\\textbf{Artigos primários}} & \\multicolumn{2}{c}{\\textbf{Artigos de revisão}} \\\\\n\\midrule\n";
    latexCode += "\\textbf{Qtd.} & \\textbf{Autor} & \\textbf{Qtd.} & \\textbf{Autor} \\\\\n\\midrule\n";

    dataArray.forEach((item, index) => {
        if ((index + 1) % 2 === 1) latexCode += "\\rowcolor{tableshade}";
        latexCode += item.rowContent + " \\\\\n";
    });

    const allSurveyAuthorsWithCount1 = Object.entries(surveyAuthorCounts).filter(([name, count]) => count === 1);
    if (allSurveyAuthorsWithCount1.length > 0) {
        latexCode += "\\midrule\n\\multicolumn{4}{l}{\\textit{* Todos os outros autores que publicaram revisões aparecem apenas uma vez.}} \\\\\n";
    }

    latexCode += "\\bottomrule\n\\end{tabularx}\n\\fonte{\\me{2026}}\n\\end{table}\n";
    return latexCode;
}

function generateLatexMetrics() {
    const visibleRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]:not(.filter-hidden)');
    let primaryPaperCount = 0, surveyPaperCount = 0;
    const primaryJournalsSet = new Set(), surveyJournalsSet = new Set();
    const primaryConfsSet = new Set(), surveyConfsSet = new Set();
    const primaryAuthorsSet = new Set(), surveyAuthorsSet = new Set();

    visibleRows.forEach(row => {
        const journalCell = row.cells[COL_IDX_JOURNAL];
        const typeCell = row.cells[COL_IDX_TYPE];
        const authorsCell = row.querySelector('td[data-field="authors"]');
        const isSurveyCell = row.querySelector('td[data-field="is_survey"]');
        const isSurvey = isSurveyCell && isSurveyCell.textContent.trim() === '✔️';

        if (isSurvey) surveyPaperCount++;
        else primaryPaperCount++;

        if (journalCell && typeCell) {
            const journalName = journalCell.textContent.trim();
            const type = (typeCell.getAttribute('title') || typeCell.textContent.trim()).toLowerCase();
            if (journalName) {
                 if (type === 'article') { 
                     if (isSurvey) surveyJournalsSet.add(journalName);
                     else primaryJournalsSet.add(journalName);
                 } else if (type === 'inproceedings' || type === 'proceedings' || type === 'conference') { 
                     if (isSurvey) surveyConfsSet.add(journalName);
                     else primaryConfsSet.add(journalName);
                 }
            }
        }

        if (authorsCell) {
            const authorsText = authorsCell.textContent.trim();
            if (authorsText) {
                authorsText.split(';').map(author => author.trim()).filter(author => author.length > 0).forEach(author => {
                    if (isSurvey) surveyAuthorsSet.add(author);
                    else primaryAuthorsSet.add(author);
                });
            }
        }
    });

    const totalFilteredPapers = primaryPaperCount + surveyPaperCount;
    const totalJournalsCount = new Set([...primaryJournalsSet, ...surveyJournalsSet]).size; 
    const totalConfsCount = new Set([...primaryConfsSet, ...surveyConfsSet]).size; 
    const totalAuthorsCount = new Set([...primaryAuthorsSet, ...surveyAuthorsSet]).size; 

    const metricRows = [
        { label: "Artigos filtrados:", primary: primaryPaperCount, survey: surveyPaperCount, total: totalFilteredPapers },
        { label: "Revistas:", primary: primaryJournalsSet.size, survey: surveyJournalsSet.size, total: totalJournalsCount },
        { label: "Conferências:", primary: primaryConfsSet.size, survey: surveyConfsSet.size, total: totalConfsCount },
        { label: "Autores:", primary: primaryAuthorsSet.size, survey: surveyAuthorsSet.size, total: totalAuthorsCount }
    ];

    const dataArray = metricRows.map(row => {
        const escapedLabel = row.label.replace(/_/g, "\\_").replace(/&/g, "\\&"); 
        return { rowContent: `${escapedLabel} & ${row.primary} & ${row.survey} & ${row.total}` };
    });

    const config = {
        caption: "Métricas detalhadas por tipo de artigo", 
        label: "cap32_metrics_detailed", 
        headers: ["Tipo de Métrica", "Primários", "Revisão", "Total"], 
        columnSpec: "{@{}X X X X @{}}", 
        useShading: true 
    };

    return generateLatexTabularx(dataArray, config);
}

function generateLatexTabularx(dataArray, config) {
    const { caption, label, headers, columnSpec, useShading } = config;

    if (!dataArray || dataArray.length === 0) {
        console.warn("No data provided for LaTeX table generation.");
        return `% No data available for table: ${caption}\n`;
    }

    let latexCode = "\\begin{table}[ht]\n\\centering\n\\small\n";
    latexCode += `\t\\caption{${caption}}\n\\label{tab:${label}}\n`;
    latexCode += `\\begin{tabularx}{\\textwidth}${columnSpec}\n\\toprule\n`;
    latexCode += headers.join(" & ") + " \\\\\n\\midrule\n";

    dataArray.forEach((item, index) => {
        if (useShading && (index + 1) % 2 === 1) latexCode += "\\rowcolor{tableshade}";
        latexCode += item.rowContent + " \\\\\n"; 
    });

    latexCode += "\\bottomrule\n\\end{tabularx}\n\\fonte{\\me{2026}}\n\\end{table}\n";
    return latexCode;
}

function generateLatexList(listElementId, caption) {
    const listElement = document.getElementById(listElementId);
    if (!listElement) return "";

    const rawData = [];
    listElement.querySelectorAll('li').forEach(li => {
        const countSpan = li.querySelector('.count');
        const nameSpan = li.querySelector('.name');
        if (countSpan && nameSpan) {
            const count = parseInt(countSpan.textContent, 10);
            const name = nameSpan.textContent.trim();
            if (count >= 2) {
                const escapedName = name.replace(/_/g, "\\_").replace(/&/g, "\\&");
                rawData.push({ name: escapedName, count: count });
            }
        }
    });

    if (rawData.length === 0) return `% No items with count >= 2 found for table.\n`;

    const modelsPerRow = 3;
    const tableRows = [];
    for (let i = 0; i < rawData.length; i += modelsPerRow) {
        const rowData = rawData.slice(i, i + modelsPerRow);
        let rowCells = [];
        for (let j = 0; j < modelsPerRow; j++) {
            if (j < rowData.length) {
                rowCells.push(rowData[j].count.toString());
                rowCells.push(rowData[j].name);
            } else {
                rowCells.push("");
                rowCells.push("");
            }
        }
        tableRows.push(rowCells.join(" & "));
    }

    let columnSpec = "{@{}";
    for (let k = 0; k < modelsPerRow; k++) columnSpec += "cX";
    columnSpec += "@{}}";

    let latexCode = "\\begin{table}[ht]\n\\centering\n\\small\n";
    latexCode += `\t\\caption{${caption} (>=2 ocorrências)}\n\\label{tab:${listElementId}_latex}\n`;
    latexCode += `\\begin{tabularx}{\\textwidth}${columnSpec}\n\\toprule\n`;

    let headerCells = [];
    for (let h = 0; h < modelsPerRow; h++) {
        headerCells.push("\\textbf{Contagem}");
        headerCells.push("\\textbf{Nome}");
    }
    latexCode += headerCells.join(" & ") + " \\\\\n\\midrule\n";

    tableRows.forEach((rowContent, index) => {
        if ((index + 1) % 2 === 1) latexCode += "\\rowcolor{tableshade}";
        latexCode += rowContent + " \\\\\n";
    });

    latexCode += "\\bottomrule\n\\end{tabularx}\n\\fonte{\\me{2026}}\n\\end{table}\n";
    return latexCode;
}


document.addEventListener('DOMContentLoaded', () => {
    const btns = [
        { id: 'journalconf-tabularx-btn', fn: generateLatexJournalsConfs },
        { id: 'authors-tabularx-btn', fn: generateLatexAuthors },
        { id: 'metrics-tabularx-btn', fn: generateLatexMetrics }
    ];

    const statsListFields = APP_CONFIG.editable_fields.filter(f => f.stats_list).slice(0, 2);
    if (statsListFields[0]) btns.push({ id: 'slot1-tabularx-btn', fn: () => generateLatexList('slot1StatsList', statsListFields[0].label) });
    if (statsListFields[1]) btns.push({ id: 'slot2-tabularx-btn', fn: () => generateLatexList('slot2StatsList', statsListFields[1].label) });

    btns.forEach(({ id, fn }) => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const originalText = this.innerHTML;
                this.innerHTML = 'Copied!';
                const latex = fn();
                if (latex) navigator.clipboard.writeText(latex).catch(() => alert('Failed to copy LaTeX.'));
                setTimeout(() => { this.innerHTML = originalText; }, 2000);
            });
        }
    });
});