// stats_latex.js

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

/**
 * Generic LaTeX generator for any populated stats list (>= 2 occurrences).
 * Arranges items in 3 columns per row (Count first, Name second) with shading.
 */
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
    latexCode += `\t\\caption{${caption} (>=2 ocorrências)}\n`;
    latexCode += `\\label{tab:${listElementId}_latex}\n`;
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

    // Dynamically bind LaTeX buttons for the generalized slots if they are configured
    const statsListFields = APP_CONFIG.editable_fields.filter(f => f.stats_list).slice(0, 2);
    
    if (statsListFields[0]) {
        btns.push({ 
            id: 'slot1-tabularx-btn', 
            fn: () => generateLatexList('slot1StatsList', statsListFields[0].label) 
        });
    }
    
    if (statsListFields[1]) {
        btns.push({ 
            id: 'slot2-tabularx-btn', 
            fn: () => generateLatexList('slot2StatsList', statsListFields[1].label) 
        });
    }

    btns.forEach(({ id, fn }) => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const originalText = this.innerHTML;
                this.innerHTML = 'Copied!';
                const latex = fn();
                if (latex) {
                    navigator.clipboard.writeText(latex).catch(() => alert('Failed to copy LaTeX.'));
                }
                setTimeout(() => { this.innerHTML = originalText; }, 2000);
            });
        }
    });
});