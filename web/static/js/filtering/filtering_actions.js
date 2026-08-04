// static/js/filtering_actions.js
/** Clipboard utilities and LaTeX export actions.
 *  Shared between server-based full page and client-only HTML export. */

/**
 * Copies the provided paper ID to the clipboard in the specified format.
 */
function copyPaperId(paperId, buttonElement, format = 'raw') {
    if (!paperId) {
        console.warn('Paper ID is empty or undefined.');
        alert('Paper ID is empty and cannot be copied.');
        return;
    }
    const originalText = buttonElement.innerHTML;
    buttonElement.innerHTML = 'Copied!';
    let textToCopy = paperId;
    if (format === 'cite') {
        textToCopy = `\\cite{${paperId}}`;
    } else if (format === 'citen') {
        textToCopy = `\\citen{${paperId}}`;
    }
    navigator.clipboard.writeText(textToCopy)
        .then(() => {
            setTimeout(() => { buttonElement.innerHTML = originalText; }, 2000);
        })
        .catch(err => {
            console.error(`Failed to copy: `, err);
            alert(`Failed to copy to clipboard.`);
            buttonElement.innerHTML = originalText;
        });
}

/**
 * Copies the provided BibTeX string to the clipboard.
 */
function copyBibtex(bibtexString, buttonElement) {
    if (bibtexString) {
        const originalText = buttonElement.textContent;
        buttonElement.textContent = 'Copied!';
        navigator.clipboard.writeText(bibtexString)
            .then(() => {
                setTimeout(() => { buttonElement.textContent = originalText; }, 2000);
            })
            .catch(err => {
                console.error('Failed to copy BibTeX: ', err);
                alert('Failed to copy BibTeX to clipboard.');
                buttonElement.textContent = originalText;
            });
    } else {
        console.warn('BibTeX content is empty.');
        alert('BibTeX content is empty and cannot be copied.');
    }
}

/**
 * Generates a LaTeX longtable based on the currently visible (filtered) rows.
 */
function copyLatexLongtable() {
    const buttonElement = document.getElementById('longtable-btn');
    if (!buttonElement) {
        console.error("Button #longtable-btn not found.");
        alert('Error: Could not find the LaTeX copy button.');
        return;
    }
    const originalText = buttonElement.innerHTML;
    const rows = tbody.querySelectorAll('tr[data-paper-id]:not(.filter-hidden)');
    if (rows.length === 0) {
        alert('No visible rows found to generate LaTeX table.');
        buttonElement.innerHTML = originalText;
        return;
    }

    let latexContent = `
% Ensure packages are loaded in your preamble:
% \\usepackage{longtable}
% \\usepackage{xcolor}
% \\usepackage{pdflscape} % For landscape pages
% \\usepackage[margin=1.5cm]{geometry} % Set smaller margins for the table area
\\begin{landscape} % Start landscape environment
% ----------------------------------------------------------
\\chapter{Lista completa de artigos julgados como relevantes através do ResearchParça}
% ----------------------------------------------------------
\\definecolor{tableshade}{HTML}{EEEEEE}
\\scriptsize % Use smaller font to fit more data
\\begin{longtable}{p{2cm}p{8cm}p{5cm}c c p{6cm}}
\\textbf{Tipo} & \\textbf{Título} & \\textbf{Autores} & \\textbf{Ano} & \\textbf{Páginas} & \\textbf{Periódico/Conferência} \\\\
\\hline % Line only under the header row
\\endfirsthead
\\multicolumn{6}{c}{{\\bfseries \\tablename\\ \\thetable{} -- continuação dá página anterior}} \\\\
\\rowcolor{tableshade}
\\textbf{Tipo} & \\textbf{Título} & \\textbf{Autores} & \\textbf{Ano} & \\textbf{Páginas} & \\textbf{Periódico/Conferência} \\\\
\\hline % Line only under the header row on subsequent pages
\\endhead
\\hline % Line before the footer
\\multicolumn{6}{|r|}{{Continua na próxima página}} \\\\
\\hline % Line after the footer text
\\endfoot
\\hline % Line before the last footer
\\endlastfoot
`;

    rows.forEach((row, index) => {
        const typeCell = row.cells[typeCellIndex];
        const typeTitle = typeCell ? typeCell.getAttribute('title') || typeCell.textContent.trim() : '';
        const titleCell = row.cells[titleCellIndex];
        const titleText = titleCell ? titleCell.textContent.trim() : '';
        const authorsCell = row.querySelector('td.hidden-data-cell[data-field="authors"]');
        const authorsText = authorsCell ? authorsCell.textContent.trim() : '';
        const yearCell = row.cells[yearCellIndex];
        const yearText = yearCell ? yearCell.textContent.trim() : '';
        const pageCountCell = row.cells[pageCountCellIndex];
        const pageCountText = pageCountCell ? pageCountCell.textContent.trim() : '';
        const venueCell = row.cells[journalCellIndex];
        const venueText = venueCell ? venueCell.textContent.trim() : '';

        const sanitizeForLatex = (str) => typeof str !== 'string' ? String(str) : str;
        const type = sanitizeForLatex(typeTitle);
        const title = sanitizeForLatex(titleText);
        const authors = sanitizeForLatex(authorsText);
        const year = sanitizeForLatex(yearText);
        const pages = sanitizeForLatex(pageCountText);
        const venue = sanitizeForLatex(venueText);

        const rowColor = (index % 2 === 0) ? '' : '\\rowcolor{tableshade} ';
        latexContent += `${rowColor}${type} & ${title} & ${authors} & ${year} & ${pages} & ${venue} \\\\\n`;
    });

    latexContent += `\\hline\n`;
    latexContent += `\\end{longtable}\n\\end{landscape}\n`;

    navigator.clipboard.writeText(latexContent)
        .then(() => {
            buttonElement.innerHTML = 'Copied!';
            setTimeout(() => { buttonElement.innerHTML = originalText; }, 2000);
        })
        .catch(err => {
            console.error('Failed to copy LaTeX table: ', err);
            alert('Failed to copy LaTeX table to clipboard.');
            buttonElement.innerHTML = originalText;
        });
}